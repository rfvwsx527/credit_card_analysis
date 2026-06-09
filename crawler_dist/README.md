# 🏦 台灣信用卡資料爬蟲

自動抓取台灣各大銀行信用卡資訊、金管會統計數據與 PTT 討論文章。

---

## 📁 專案結構

```
crawler_dist/
├── scraper_banks.py                # 各銀行官網爬蟲（Playwright 動態渲染，11 家）
├── fac_crawler.py                  # 金管會統計資料爬蟲（下載 banking66.csv）
├── ptt_credit_card_crawler.py      # PTT 信用卡版爬蟲
├── ctbc_cards.py                   # 中信卡片清單處理（CSV 後備 + 自動同步）
├── ctbc_cards.csv                  # 中信卡片靜態清單（WAF 防護時的 fallback）
├── card_common.py                  # 爬蟲共用模組
├── db_common.py                    # MySQL 讀寫共用模組
├── clean_credit_cards.py           # 資料清理 + 特徵工程 → 寫回 MySQL
├── crawler/                        # Celery 分散式套件
│   ├── config.py                   # 連線與資料表設定（全走環境變數）
│   ├── worker.py                   # Celery app（佇列路由）
│   ├── tasks_ptt.py                # PTT 任務定義
│   ├── tasks_banks.py              # 各銀行任務定義
│   ├── tasks_fac.py                # 金管會任務定義
│   ├── producer_ptt.py             # PTT 派工程式
│   ├── producer_banks.py           # 各銀行派工程式
│   ├── producer_card_stats.py      # 金管會派工程式
│   └── scheduler.py                # ⭐ 每晚排程器（派工 → 等爬完 → 清理）
├── Dockerfile                      # 爬蟲映像（含 Playwright/chromium、排程器、清理程式）
├── mysql.yml                       # MySQL 8 + phpMyAdmin（Swarm）
├── rabbitmq.yml                    # RabbitMQ + Flower（Swarm，任務佇列與監控）
├── docker-compose-card-crawler-worker.yml      # Swarm worker 部署
├── docker-compose-card-crawler-producer.yml    # Swarm producer 部署
├── docker-compose-card-scheduler.yml           # ⭐ Swarm 排程器部署（每晚 21:00）
├── requirements.txt                # Python 套件版本清單（含 celery / apscheduler / loguru）
├── pyproject.toml / uv.lock        # uv 專案設定與鎖定檔
├── debug_*.png                     # 各銀行除錯截圖（--debug 產生）
├── scraper_banks.log               # 銀行爬蟲執行日誌
└── README.md                       # 本說明文件
```

> 單機執行時直接跑各 `*_crawler.py` / `scraper_banks.py`；分散式部署則透過 `crawler/` 內的 producer 派工、worker 消費（詳見下方「分散式爬蟲」章節），佇列與監控由 `rabbitmq.yml`（RabbitMQ + Flower）提供。每晚自動化（爬蟲 → 清理）則由 `crawler/scheduler.py` 排程（見「排程自動化」章節）。

---

## 環境安裝

```bash
uv sync
uv run playwright install chromium
```

---

## 🧰 需求環境

**單機執行（直接跑爬蟲）**

| 項目 | 需求 |
|------|------|
| 作業系統 | macOS（Apple Silicon）或 Linux |
| Python | 3.12+ |
| 套件管理 | uv（或 pip） |
| 瀏覽器核心 | Playwright chromium（`uv run playwright install chromium`，銀行爬蟲用） |
| 資料庫 | MySQL 8（資料庫 `mydb`，可選；無 DB 時仍會輸出 CSV） |

**主要 Python 套件**

- 爬蟲：`requests`、`beautifulsoup4`、`playwright`（+ chromium）
- 資料庫：`sqlalchemy`、`pymysql`、`cryptography`
- 資料處理：`pandas`
- 分散式與排程：`celery`、`pika`、`apscheduler`、`loguru`

**分散式部署額外需求**（見下方「分散式爬蟲」章節）

| 項目 | 需求 |
|------|------|
| 容器平台 | Docker Desktop / Docker Engine（已啟用 **Swarm 模式**） |
| 容器管理 | Portainer |
| 資料庫 | MySQL `mysql:8.0`（swarm 服務 `mysql_mysql` / 資料庫 `mydb`，由 `mysql.yml` 部署） |
| 訊息佇列 | RabbitMQ `3.6-management-alpine`（含管理介面 `:15672`） |
| 任務監控 | Flower `mher/flower:2.0.0`（`:5555`） |
| overlay 網路 | `my_swarm_network`（需事先 `docker network create -d overlay`） |
| 額外套件 | `celery`、`pika`、`apscheduler`、`loguru`（打包進爬蟲映像） |

> 完整套件版本見 `requirements.txt`；映像由 `Dockerfile` 建置（套件以 **uv** 安裝）。

---

## 🕷️ 爬蟲說明與使用方式

### `scraper_banks.py`（各銀行官網）

使用 Playwright 動態渲染，支援 11 家銀行，具備：

- **雙策略擷取**：JS 注入（卡名葉子節點偵測）+ href 連結比對，兩種方式互補
- **反偵測強化**：抹除 `webdriver` 指紋、偽裝 UA / sec-ch-ua / WebGL，優先使用系統真實 Chrome
- **導覽區排除**：自動跳過 nav / header / footer / sidebar，避免選單文字混入卡名
- **卡名雜訊過濾**：黑名單關鍵字、長度限制、標點密度過濾、結尾必須為「卡/Card」
- **中信特殊處理**：中信官網有 WAF（APP-1053）防護，預設改讀 `ctbc_cards.csv` 靜態清單；加 `--ctbc-dynamic` 參數可嘗試動態爬取，抓到新卡自動寫回 CSV

支援銀行：

| 代碼 | 銀行名稱 | 爬取方式 | 官網網址 |
|------|---------|---------|----------|
| `esun` | 玉山銀行 | Playwright 動態 | https://www.esunbank.com/zh-tw/personal/credit-card/intro |
| `cathaybk` | 國泰世華銀行 | Playwright 動態 | https://www.cathaybk.com.tw/cathaybk/personal/credit-card/ |
| `fubon` | 台北富邦銀行 | Playwright 動態 | https://www.fubon.com/banking/personal/credit_card/all_card/all_card.htm |
| `taishin` | 台新銀行 | Playwright 動態 | https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/ |
| `sinopac` | 永豐銀行 | Playwright 動態 | https://bank.sinopac.com/sinopacBT/personal/credit-card/introduction/list.html |
| `yuanta` | 元大銀行 | Playwright 動態（含分頁） | https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do |
| `kgi` | 凱基銀行 | Playwright 動態 | https://www.kgibank.com.tw/zh-tw/personal/credit-card/list |
| `dbs` | 星展銀行 | Playwright 動態 | https://www.dbs.com.tw/personal-zh/cards/dbs-credit-cards/default.page |
| `hsbc` | 滙豐銀行 | Playwright 動態 | https://www.hsbc.com.tw/credit-cards/ |
| `scb` | 渣打銀行 | Playwright 動態 | https://www.sc.com/tw/credit-cards/ |
| `ctbc` | 中國信託銀行 | 靜態清單（`ctbc_cards.csv`） | https://www.ctbcbank.com/twrbo/zh_tw/cc_index/cc_cardall.html （WAF 防護，預設改讀 CSV） |

```bash
# 爬取全部銀行
uv run python scraper_banks.py

# 只爬單一銀行
uv run python scraper_banks.py --bank esun

# 開啟瀏覽器視窗（非 headless，方便偵錯）
uv run python scraper_banks.py --show --debug

# 嘗試動態爬中信（有可能被 WAF 擋）
uv run python scraper_banks.py --ctbc-dynamic
```

輸出：`crawler_data/banks.csv`

---

### `fac_crawler.py`（金管會）

直接下載金管會公開統計 CSV（`banking66.csv`），儲存至 `crawler_data/` 並同步寫入 MySQL。

**資料來源網址**：https://www.banking.gov.tw/webdowndoc?file=/stat/opendata/banking66.csv （金管會銀行局開放資料）

```bash
uv run python fac_crawler.py
```

輸出：`crawler_data/credit_card_stats.csv`

---

### `ptt_credit_card_crawler.py`（PTT）

爬取 PTT 信用卡版 2025 年至今的文章，功能包含：

**看板網址**：https://www.ptt.cc/bbs/creditcard/index.html


- 二分搜尋估算起始頁，縮短不必要的爬取時間
- 批次寫入（每 100 筆存一次），兼顧效能與斷點保護
- 連續 2 頁皆為舊文章自動停止
- 支援斷點恢復（重跑 = 清空 MySQL 後重寫）

可修改 `ptt_credit_card_crawler.py` 頂部的 `START_YEAR` 調整起始年份。

```bash
uv run python ptt_credit_card_crawler.py
```

輸出：`crawler_data/ptt_credit_card.csv`

---

## 🐝 分散式爬蟲（Celery + RabbitMQ + Docker Swarm）

上面是「單機直接跑」的用法；正式環境改用 **Celery + RabbitMQ** 的派工/消費架構，部署於 **Docker Swarm**、由 **Portainer** 管理，可多 worker 平行加速。

### 架構

```
  producer（派工）──► RabbitMQ 佇列 ──► worker（多個，平行）──► MySQL
  ・先清空對應表一次    ptt/banks/      ・抓資料 → append 寫入   （raw tables）
  ・把工作拆成多個任務   card_stats      ・三來源各一組 worker
                          │
                          └─► Flower 監控（:5555）
```

| 角色 | 說明 |
|------|------|
| **RabbitMQ** | 訊息佇列（broker）。佇列：`ptt` / `banks` / `card_stats`。管理介面 `:15672`（worker/worker） |
| **Producer** | 派工程式（跑一次即結束）：① 先 **清空** 對應 MySQL 表 ② 把工作拆成多個任務送進佇列 |
| **Worker** | 消費程式（常駐）：從佇列取任務、執行爬蟲、**append** 進 MySQL。可多副本平行 |
| **Flower** | Celery 監控 Web UI（`:5555`），看任務數量與 worker 狀態 |

> 為避免多個平行 worker 互相清空資料：**清空只由 producer 派工前做一次，worker 全程只 append**。

| 來源 | 佇列 | 任務拆分 | worker |
|------|------|----------|--------|
| PTT | `ptt` | 每個索引頁一個任務（約 110+ 頁） | 2 副本平行 |
| 各銀行 | `banks` | 每家銀行一個任務（11 家） | 1 副本（Playwright 較吃資源） |
| 金管會 | `card_stats` | 單一下載任務 | 1 副本 |

### 啟動步驟

> 前置：Swarm 已啟用、overlay 網路 `my_swarm_network` 已建。MySQL 也以 swarm 服務部署（服務名 `mysql_mysql` / 資料庫 `mydb`），與爬蟲在同一網路。

**MySQL（與爬蟲共用同一個 DB）**：若尚未部署，用 `mysql.yml`（MySQL 8 + phpMyAdmin）：

```bash
# 1) 先建立 external volume（mysql.yml 的 volume 設為 external，不會自動建）
docker volume create mysql

# 2) 部署 MySQL + phpMyAdmin（約束為 manager 節點，不需貼 label）
docker stack deploy -c mysql.yml mysql
# 服務名 mysql_mysql；phpMyAdmin 介面 http://localhost:8080；資料持久化於 volume `mysql`
```

> 已有 `mysql_mysql` 在跑就跳過。爬蟲 / producer 的 yml 內 `DB_HOST=mysql_mysql` 即指向它（須同在 `my_swarm_network`）。

接著依序啟動其餘服務：

```bash
# ① RabbitMQ + Flower
docker stack deploy -c rabbitmq.yml rabbitmq

# ② 建置並推送爬蟲映像（改了程式才需重做）
docker build -t rfvwsx527/credit-card-crawler:1.0 .
docker push rfvwsx527/credit-card-crawler:1.0

# ③ 貼節點 label、啟動常駐 worker
docker node update --label-add card_crawler=true $(docker node ls -q)
docker node update --label-add producer=true $(docker node ls -q)
docker stack deploy -c docker-compose-card-crawler-worker.yml card_crawler

# ④ 派工開始爬（producer 跑一次：清空表 → 派工）
docker stack deploy -c docker-compose-card-crawler-producer.yml card_producer
```

重新爬一輪（之後重爬時）：

```bash
docker service update --force card_producer_card_producer_ptt
docker service update --force card_producer_card_producer_banks
docker service update --force card_producer_card_producer_stats
```

### 如何監控「爬完了沒」

**Flower（最直觀）**：開 `http://localhost:5555` → Workers 頁看 `Active` 是否全為 0、Tasks 頁看任務皆 `SUCCESS`。
（注意：Flower 的 `Succeeded` 是 worker 啟動以來的 **累計值**，重爬會持續累加，不等於資料庫筆數。）

**查佇列是否歸 0**：

```bash
docker exec $(docker ps -qf name=rabbitmq_rabbitmq) \
  rabbitmqctl list_queues name messages messages_unacknowledged | grep -E "^ptt|^banks|^card_stats"
```

三個佇列的 `messages` 與 `messages_unacknowledged` **都為 0** = 沒有任務在排隊或執行 = 爬完。

**查資料列數（最終確認）**：

```bash
docker exec $(docker ps -qf name=mysql_mysql) --default-character-set=utf8mb4 \
  mysql -uroot -p<密碼> -e \
  "SELECT 'ptt' t, COUNT(*) FROM mydb.ptt_credit_card
   UNION ALL SELECT 'banks', COUNT(*) FROM mydb.banks
   UNION ALL SELECT 'stats', COUNT(*) FROM mydb.credit_card_stats;"
```

**看即時進度 / 排錯**：

```bash
docker service logs card_crawler_card_worker_ptt --tail 30 -f   # 「PTT 第 X 頁：寫入 N 篇」
docker service logs card_producer_card_producer_ptt --tail 15   # 「已派工 N 個任務」
```

> Producer 是「跑完即退出」的服務，在 Portainer 顯示 `0/1`、部署時出現 `service update paused` 屬正常（非錯誤）。

---

## 🧹 資料清理（`clean_credit_cards.py`）

將原始爬蟲資料清理、特徵工程後寫回 MySQL：

| 原始表 | 清理後表 | 主要處理 |
|--------|----------|----------|
| `credit_card_stats` | `credit_card_stats_clean` | 民國年轉西元、數值欄轉型、計算淨增卡數、有效卡率、卡均簽帳金額 |
| `banks` | `banks_clean` | 合併回饋亮點、解析最高回饋率（%）、卡別多標籤展開、適用場景關鍵字標記 |
| `ptt_credit_card` | `ptt_credit_card_clean` | 推噓數正規化（「爆」→100、「Xn」→負數）、銀行關鍵字提及標記、年月欄位 |
| — | `dashboard_agg` | 長表彙整（metric / dim / value），供儀表板 KPI 快取使用 |

```bash
# 清理並寫入（會 TRUNCATE 清理後的表再重寫，不動原始表）
uv run python clean_credit_cards.py

# 原始表還沒進 DB 時，從 CSV 自動建立
SEED_FROM_CSV=1 CSV_DIR=./crawler_data uv run python clean_credit_cards.py
```

---

## ⏰ 排程自動化（每晚 21:00 自動爬蟲 → 清理）

把「分散式爬蟲」與「資料清理」串成一條**每晚自動執行**的流程，由 `crawler/scheduler.py`（APScheduler 常駐排程器）負責。每天 **21:00（Asia/Taipei）** 觸發一次：

```
21:00  ① 派工：沿用 producer，清空三張原始表各一次 → 任務送進 ptt / banks / card_stats 佇列
        ② 等待：輪詢「佇列深度 + worker 進行中任務」，直到全部清空（= 爬完）
        ③ 清理：執行 clean_credit_cards.py → 寫入 *_clean / dashboard_agg（原始表不動）
```

### 設計重點

- 排程器只做「派工 + 等待 + 清理」，**真正爬蟲仍由常駐 worker 執行**，因此部署排程器前 worker 必須在線，否則任務會卡在佇列無人消費。
- 與 worker / producer **共用同一個映像**（`rfvwsx527/credit-card-crawler:1.0`），只是啟動指令改成 `python -m crawler.scheduler`，**不需另建映像**。
- 清空只在派工時做一次，worker 全程 `append`，避免多個平行 worker 互相清空（沿用既有架構）。
- 「爬完」採「佇列深度 + 進行中任務」雙重判定，並要求連續多次閒置才收工，避免 worker 還沒接手就被誤判為已爬完。
- 任一階段失敗只記 log、不讓排程器整個崩潰，下一晚會再跑一輪。

### 前置

需先完成上方「分散式爬蟲」的部署：`my_swarm_network`、`mysql_mysql`、`rabbitmq`、以及**常駐 worker**（`docker-compose-card-crawler-worker.yml`）都已啟動。

> 映像需含排程器與清理程式：`Dockerfile` 已把 `crawler/scheduler.py`、`clean_credit_cards.py`、`ctbc_cards.csv` 打包，`requirements.txt` 已加入 `APScheduler`、`loguru`。改過這些檔案後就要重新 build 映像。

### 部署步驟

```bash
# ① 重新建置並推送映像（已含 scheduler.py / clean_credit_cards.py / apscheduler / loguru）
#    ★ 必須在 crawler_dist/（有 Dockerfile 與 crawler/ 的那層）執行
docker build -t rfvwsx527/credit-card-crawler:1.0 .
docker push rfvwsx527/credit-card-crawler:1.0

# ② 部署常駐排程器（每天 21:00 自動跑）
docker stack deploy -c docker-compose-card-scheduler.yml card_scheduler

# ③ 看排程器 log
docker service logs card_scheduler_card_scheduler -f
```

> ⚠️ `scheduler.py` 必須位於 `crawler/scheduler.py`（套件內），啟動方式為 `python -m crawler.scheduler`；切勿放最上層或用 `python crawler/scheduler.py`，否則 `from crawler.worker import app` 會匯入失敗。

### 立即驗證（不想等到晚上）

兩種方式擇一：

```bash
# 法 A：把 docker-compose-card-scheduler.yml 內 RUN_ON_START 改成 1 後重新部署
#       → 容器一啟動就先跑一輪
docker stack deploy -c docker-compose-card-scheduler.yml card_scheduler

# 法 B：暫時把 compose 內 CRAWL_HOUR / CRAWL_MINUTE 改成接近現在的時間後重新部署
```

### 可調參數（環境變數，寫在 `docker-compose-card-scheduler.yml`）

| 變數 | 預設 | 說明 |
|------|------|------|
| `CRAWL_HOUR` / `CRAWL_MINUTE` | `21` / `0` | 每天觸發時間 |
| `RUN_ON_START` | `0` | 設 `1` → 啟動後立即先跑一輪（測試用） |
| `WAIT_TIMEOUT_SEC` | `10800` | 等爬完的逾時上限（秒），預設 3 小時 |
| `POLL_INTERVAL_SEC` | `20` | 輪詢佇列間隔（秒） |
| `IDLE_CONFIRM` | `3` | 連續幾次判定閒置才算爬完 |

> ⚠️ `db_common` 讀 `MYSQL_ACCOUNT`、`clean_credit_cards` 讀 `MYSQL_USER`，compose 內兩者已設成相同值（`root`），請務必保持一致，否則清理與派工會連到不同帳號。

### 調整排程時間（不需重建映像）

觸發時間吃環境變數 `CRAWL_HOUR` / `CRAWL_MINUTE`（24 小時制、台北時間），改時間**不必重 build 映像**；覆寫環境變數後容器會重啟，並以新時間重新註冊排程。

```bash
# 法一：service update 即時改（例：改成每天 14:30）
docker service update \
  --env-add CRAWL_HOUR=14 \
  --env-add CRAWL_MINUTE=30 \
  --force card_scheduler_card_scheduler
```

長期設定建議改 `docker-compose-card-scheduler.yml` 內的 `CRAWL_HOUR` / `CRAWL_MINUTE` 後重新部署（臨時測試用法一即可）：

```bash
# 法二：寫進 compose 再部署
docker stack deploy -c docker-compose-card-scheduler.yml card_scheduler
```

改完看 log 確認新時間已生效：

```bash
docker service logs card_scheduler_card_scheduler --tail 5
#   已註冊每日排程：每天 14:30（Asia/Taipei） 爬蟲 → 等爬完 → 資料清理
```

> 想「幾分鐘後就觸發」測試，把時、分設成比現在晚 2~3 分鐘即可（記得 worker 要在線，否則 ② 等待會卡到逾時）。`--env-add` 對已存在的變數即為覆寫；法一改的是執行中服務狀態，之後若再用舊 compose `stack deploy` 會被蓋回，正式時間請用法二寫進 compose。

### 確認跑完

排程器 log 會依序印出 ①／②／③ 三階段，清理完成會看到：

```
③ 資料清理完成 → *_clean / dashboard_agg 已更新
```

也可用上方「如何監控爬完了沒」的查佇列指令，確認 `ptt` / `banks` / `card_stats` 三佇列都歸 0。

---

## 🗄️ 資料庫設定

連線資訊優先讀取環境變數，未設定才用預設值：

```bash
export DB_HOST=localhost
export DB_PORT=3306
export DB_NAME=mydb
export DB_USER=root
export DB_PASSWORD=<your_password>
```

> ⚠️ 請勿將密碼寫死於程式碼或提交至版控。

---

## 除錯截圖

執行 `--debug` 後會產生各銀行全頁截圖（`debug_<代碼>.png`），用於確認網頁實際呈現內容與排查爬取問題。

---

## 注意事項

- PTT 爬蟲預設 0.4 秒請求間隔，請勿縮短
- 中信（ctbc）預設使用 `ctbc_cards.csv` 靜態清單；官網改版時直接編輯 CSV 即可更新，動態爬取失敗時也會自動 fallback 至此清單
- 部分銀行官網有 WAF 防護，若動態爬取失敗會自動 fallback 至靜態清單
- 排程器與 worker / producer 共用同一個映像，改了 `crawler/`、`clean_credit_cards.py`、`requirements.txt` 或 `Dockerfile` 後需重新 build 並 push，再 `docker service update --force` 對應服務才會生效