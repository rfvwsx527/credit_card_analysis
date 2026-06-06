# 🏦 台灣信用卡資料爬蟲

自動抓取台灣各大銀行信用卡資訊、金管會統計數據與 PTT 討論文章。

---

## 環境安裝

```bash
uv sync
uv run playwright install chromium
```

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

> 前置：Swarm 已啟用、overlay 網路 `my_swarm_network` 已建、MySQL（swarm 服務 `mysql_mysql` / 資料庫 `mydb`）在同一網路。

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