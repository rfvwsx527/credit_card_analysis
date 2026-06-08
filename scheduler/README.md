# 每晚自動爬蟲 + 清理 — 部署說明

每天 **21:00(Asia/Taipei)** 自動執行:派工爬蟲 → 等爬完 → 資料清理。

排程器只負責「派工 + 等待 + 清理」,**真正爬蟲仍由常駐 worker 執行**,所以部署前
worker 必須在線(沿用既有 `docker-compose-card-crawler-worker.yml`)。

## 流程

```
21:00  ① producer 清空三張原始表一次 → 任務送進 ptt / banks / card_stats 佇列
        ② 輪詢佇列深度 + worker 進行中任務,直到全部清空(= 爬完)
        ③ clean_credit_cards.py:原始表 → 清理 → *_clean / dashboard_agg
```

清空只在派工時做一次,worker 全程 `append`,避免多個平行 worker 互相清空。

## 新增 / 異動的檔案

| 檔案 | 說明 |
|------|------|
| `crawler/scheduler.py` | **新增**。每晚排程器:派工 → 等爬完 → 清理 |
| `docker-compose-card-scheduler.yml` | **新增**。排程器的 Swarm 部署檔 |
| `requirements.txt` | **異動**。加入 `APScheduler`、`loguru` |
| `Dockerfile` | **異動**。COPY 加入 `clean_credit_cards.py`、`ctbc_cards.csv` |

## 部署步驟

```bash
# 0) 前置(若尚未啟動):overlay 網路、MySQL、RabbitMQ、常駐 worker
docker network create -d overlay my_swarm_network          # 已存在可略過
docker stack deploy -c mysql.yml mysql
docker stack deploy -c rabbitmq.yml rabbitmq
docker stack deploy -c docker-compose-card-crawler-worker.yml card_crawler

# 1) 重新建置映像(已把 scheduler.py / clean_credit_cards.py / 套件打包進去)
docker build -t rfvwsx527/credit-card-crawler:1.0 .
docker push    rfvwsx527/credit-card-crawler:1.0

# 2) 部署排程器(常駐,每天 21:00 自動跑)
docker stack deploy -c docker-compose-card-scheduler.yml card_scheduler

# 3) 看 log
docker service logs card_scheduler_card_scheduler -f
```

## 立即驗證(不想等到晚上)

兩種方式擇一:

```bash
# A) 把 RUN_ON_START 設成 1 後再部署 → 容器一啟動就先跑一輪
#    (改 docker-compose-card-scheduler.yml 內 RUN_ON_START=1,再 stack deploy)

# B) 暫時把觸發時間改成接近現在(例如改 CRAWL_HOUR / CRAWL_MINUTE 後重新部署)
```

## 可調參數(環境變數,寫在 compose)

| 變數 | 預設 | 說明 |
|------|------|------|
| `CRAWL_HOUR` / `CRAWL_MINUTE` | `21` / `0` | 每天觸發時間 |
| `RUN_ON_START` | `0` | 設 `1` → 啟動後立即先跑一輪(測試) |
| `WAIT_TIMEOUT_SEC` | `10800` | 等爬完的逾時上限(秒) |
| `POLL_INTERVAL_SEC` | `20` | 輪詢佇列間隔(秒) |
| `IDLE_CONFIRM` | `3` | 連續幾次判定閒置才算爬完 |

> **注意**:`db_common` 讀 `MYSQL_ACCOUNT`、`clean_credit_cards` 讀 `MYSQL_USER`,
> compose 內兩者已設成相同值(`root`),請保持一致。

## 怎麼確認跑完了

```bash
# 排程器 log 會依序印出 ①/②/③ 三階段;清理完成會看到:
#   ③ 資料清理完成 → *_clean / dashboard_agg 已更新

# 也可手動查佇列是否歸 0(三個佇列 messages 與 unacked 都為 0 = 爬完)
docker exec $(docker ps -qf name=rabbitmq_rabbitmq) \
  rabbitmqctl list_queues name messages messages_unacknowledged \
  | grep -E "^ptt|^banks|^card_stats"
```
