# 信用卡分散式爬蟲 API（FastAPI + Docker Swarm）

在原本的「Celery + RabbitMQ + Docker Swarm」信用卡爬蟲之上，加一層 **FastAPI 服務**：

- **資料查詢**：對外提供爬好的銀行信用卡 / PTT 討論 / 金管會統計 / 儀表板資料（JSON）。
- **爬蟲控制平面**：透過 RabbitMQ 派工觸發分散式爬蟲、查佇列深度，不必登進機器下 `docker` 指令。

API 映像很輕量（**不含** Playwright / 爬蟲程式）——它只查 MySQL、送 Celery 任務。

---

## 架構位置

```
                         ┌─────────────┐
   瀏覽器 / 前端儀表板 ──►│  FastAPI    │── 查詢 ──► MySQL（mydb，與爬蟲共用）
                         │ (this repo) │── 派工 ──► RabbitMQ ──► Celery worker（多副本）──► MySQL
                         └─────────────┘── 監控 ──► RabbitMQ 管理 API（佇列深度）
```

部署方式、環境變數命名都對齊既有的 worker / producer yml，可直接共用同一張 overlay 網路 `my_swarm_network`。

---

## 目錄結構

```
api/                              # build context（對應容器內 /api）
├── api/                          # Python 套件（模組路徑 api.main:app）
│   ├── main.py                   # FastAPI 進入點：掛載各 router、/health、/docs
│   ├── config.py                 # 連線設定（全部走環境變數，命名對齊爬蟲端）
│   ├── db.py                     # MySQL engine + 只讀查詢（表名白名單、bound 參數）
│   ├── tasking.py                # Celery send_task 派工 + RabbitMQ 佇列監控
│   ├── schemas.py                # Pydantic 請求/回應模型
│   └── routers/
│       ├── banks.py              # /api/v1/banks
│       ├── ptt.py                # /api/v1/ptt
│       ├── stats.py              # /api/v1/stats
│       ├── dashboard.py          # /api/v1/dashboard
│       └── crawl.py              # /api/v1/crawl/*（派工 + 佇列）
├── pyproject.toml                # uv 專案（fastapi / uvicorn / sqlalchemy / celery …）
├── uv.lock                       # 鎖定版本（可重現 build）
├── .env.example                  # 環境變數範例（複製成 .env）
├── Dockerfile                    # uv + uvicorn 映像
└── docker-compose-api-swarm.yml  # Swarm 部署（對齊你提供的範例 yml）
```

---

## API 端點

互動式文件：`http://<host>:8887/docs`（Swagger）、`/redoc`

### 資料查詢（GET）

| 端點 | 說明 | 主要參數 |
|------|------|----------|
| `/api/v1/banks` | 信用卡列表 | `bank` `card_type` `q` `limit` `offset` |
| `/api/v1/banks/by-bank` | 各銀行卡片張數 | — |
| `/api/v1/ptt` | PTT 文章（預設不含內文） | `q` `category` `year_month` `include_content` `limit` `offset` |
| `/api/v1/ptt/by-month` | 每月貼文量 | — |
| `/api/v1/stats` | 金管會發卡統計 | `org` `year_month` `limit` `offset` |
| `/api/v1/dashboard` | 儀表板彙整（依 metric 分組） | `metric`（前綴，如 `kpi` `trend_` `rank_`） |
| `/api/v1/dashboard/metrics` | 列出所有 metric | — |
| `/health` | 健康檢查（含 DB 連線） | — |

> 查詢優先讀清理表（`*_clean` / `dashboard_agg`）；清理表還沒建時自動退回原始表。
> 欄位保留原始中文名稱（與 DB 一致）。
> `/api/v1/ptt` 回傳 `title`（**貼文標題**，一律回傳）、`author`、`pub_dt`、`分類`、`push_count`、`url`；`content`（**貼文內容**全文）較長，預設不帶，需加 `?include_content=true` 才回傳。例：`/api/v1/ptt?include_content=true&limit=10`。

### 爬蟲控制（POST / GET）

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/v1/crawl/queues` | GET | 查 `ptt`/`banks`/`card_stats` 三佇列深度（皆 0 = 爬完） |
| `/api/v1/crawl/banks` | POST | 清空 `banks` → 每家銀行派一個任務（body 可指定 `codes`） |
| `/api/v1/crawl/ptt` | POST | 清空 `ptt` → 指定頁碼範圍派工（body `start_page`/`end_page`） |
| `/api/v1/crawl/ptt/all` | POST | 清空 `ptt` → 自動估算頁數全爬（等同重觸發 producer，無需 body） |
| `/api/v1/crawl/stats` | POST | 派一個金管會統計任務 |

> 行為對齊既有 producer：**派工前清空一次，worker 全程只 append**。
> `/crawl/ptt` 需指定頁碼範圍（適合補爬某段）；要**全爬**用 `/crawl/ptt/all`，由 worker 自動估算頁數（worker 映像需含 `crawler.tasks_ptt.crawl_ptt_all` 任務）。

**範例**

```bash
# 派工全部 11 家銀行
curl -X POST http://localhost:8887/api/v1/crawl/banks \
  -H 'Content-Type: application/json' -d '{}'

# 只爬玉山、國泰
curl -X POST http://localhost:8887/api/v1/crawl/banks \
  -H 'Content-Type: application/json' -d '{"codes":["esun","cathaybk"]}'

# 派工 PTT 第 1~20 頁
curl -X POST http://localhost:8887/api/v1/crawl/ptt \
  -H 'Content-Type: application/json' -d '{"start_page":1,"end_page":20}'

# 全爬 PTT（自動估算頁數，最省事）
curl -X POST http://localhost:8887/api/v1/crawl/ptt/all \
  -H 'Content-Type: application/json'

# 查 PTT 文章（含標題與內容）
curl "http://localhost:8887/api/v1/ptt?include_content=true&limit=10"

# 看佇列是否歸 0
curl http://localhost:8887/api/v1/crawl/queues
```

---

## 本機開發

```bash
cd api
cp .env.example .env          # 視情況改 MYSQL_HOST / RABBITMQ_HOST（本機常用 127.0.0.1）
uv sync
uv run --env-file=.env uvicorn api.main:app --reload --port 8887
# 開 http://localhost:8887/docs
```

---

## 部署到 Docker Swarm

> 前置：Swarm 已啟用、overlay 網路 `my_swarm_network` 已建、MySQL（`mysql_mysql`）與 RabbitMQ（`rabbitmq`）已在同一網路上跑（沿用爬蟲專案的部署）。

```bash
# ① 建置並推送 API 映像
cd api
docker build -t rfvwsx527/credit-card-api:1.0 .
docker push rfvwsx527/credit-card-api:1.0

# ② 貼 node label（API 要落在哪台）
docker node update --label-add api=true $(docker node ls -q)

# ③ 部署（image tag 由 DOCKER_IMAGE_VERSION 控制，預設 1.0）
DOCKER_IMAGE_VERSION=1.0 docker stack deploy -c docker-compose-api-swarm.yml api

# ④ 驗證
curl http://localhost:8887/health
#  → 開 http://localhost:8887/docs
```

部署 yml 的 `command` 與你提供的範例一致：

```
bash -c "cd /api && uv run --env-file=.env uvicorn api.main:app --host 0.0.0.0 --port 8887"
```

程式實際位於 `/api/api/main.py`，故模組路徑為 `api.main:app`。

> `/api/v1/crawl/ptt/all` 的估算邏輯在 worker 端執行，需 worker 映像含 `crawler.tasks_ptt.crawl_ptt_all` 任務（見爬蟲專案 tasks_ptt.py）；只重 build 本 API 不會讓該端點生效。

---

## 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `MYSQL_HOST` | `mysql_mysql` | MySQL swarm 服務名（本機開發用 `127.0.0.1`） |
| `MYSQL_PORT` / `MYSQL_DB` | `3306` / `mydb` | |
| `MYSQL_ACCOUNT` / `MYSQL_PASSWORD` | `root` / … | |
| `RABBITMQ_HOST` | `rabbitmq` | broker 主機 |
| `RABBITMQ_PORT` | `5672` | AMQP 埠 |
| `RABBITMQ_MGMT_PORT` | `15672` | 管理 API 埠（查佇列深度用） |
| `RABBITMQ_ACCOUNT` / `RABBITMQ_PASSWORD` | `worker` / `worker` | |
| `BANK_CODES` | 11 家代碼 | 派工 banks 的預設清單 |
| `CORS_ORIGINS` | `*` | 前端來源（正式環境建議收斂） |

> 命名與 `crawler/config.py`、`db_common.py` 相容，同一份 environment 可共用。
> ⚠️ 正式環境請改用 Docker secrets / 環境變數注入密碼，不要寫死在 yml。
