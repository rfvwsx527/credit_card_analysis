## 💳 專案名稱：銀行信用卡分散式爬蟲和儀表板

---

### 🔍 1. 可以分析什麼

> 銀行行銷團隊每天面對 **10 多家競爭對手**，卻沒有一個統一平台能即時掌握：
> **誰在搶市場？用什麼策略？效果如何？**

| # | 分析項目 | 說明 |
|---|----------|------|
| ① | **整合金管會統計資料** | 爬取 2019～2024 年各銀行信用卡業務統計，建立市佔率消長資料庫，欄位涵蓋：發卡數、有效卡數、消費筆數、消費金額、循環信用餘額 |
| ② | **爬取競品促銷資訊** | 每週自動爬取前 10 大發卡行官網信用卡列表，記錄卡別名稱、主打回饋類別（餐飲／旅遊／網購）、回饋率上限、年費、合作通路、優惠期間 |
| ③ | **量化消費者聲音** | 爬取 PTT 信用卡版文章標題與留言數，統計各銀行被討論的頻率與情緒傾向 |
| ④ | **建立互動式競爭分析儀表板** | 整合上述資料，提供可篩選、可比較的視覺化平台，涵蓋四大分析維度：市佔率趨勢、回饋率比較、促銷熱度、PTT 社群聲量 |

---

### 📂 2. 資料來源

- 🏛️ 金管會
- 🏦 各大銀行信用卡官網（共 11 家）：玉山銀行、國泰世華銀行、台北富邦銀行、台新銀行、永豐銀行、元大銀行、凱基銀行、星展銀行、滙豐銀行、渣打銀行、中國信託銀行
- 💬 PTT 信用卡版

---

### 📁 3. 專案結構

```
.
├── crawler_dist/                       # 分散式爬蟲（Celery + RabbitMQ + Swarm）
│   ├── scraper_banks.py                # 各銀行官網爬蟲（Playwright）
│   ├── fac_crawler.py                  # 金管會統計資料爬蟲
│   ├── ptt_credit_card_crawler.py      # PTT 信用卡版爬蟲
│   ├── ctbc_cards.py / ctbc_cards.csv  # 中信卡片清單（CSV 後備 + 自動同步）
│   ├── card_common.py                  # 爬蟲共用模組
│   ├── db_common.py                    # MySQL 讀寫共用模組
│   ├── clean_credit_cards.py           # 資料清理 → 寫回 MySQL
│   ├── crawler/                        # Celery 套件
│   │   ├── worker.py                   # Celery app（佇列路由）
│   │   ├── tasks_ptt.py / tasks_banks.py / tasks_fac.py        # 任務定義
│   │   └── producer_ptt.py / producer_banks.py / producer_card_stats.py  # 派工
│   ├── Dockerfile
│   ├── mysql.yml                                   # MySQL 8 + phpMyAdmin（Swarm）
│   ├── docker-compose-card-crawler-worker.yml      # Swarm worker
│   └── docker-compose-card-crawler-producer.yml    # Swarm producer
├── rabbitmq.yml                        # RabbitMQ + Flower
├── streamlit/                          # Streamlit 互動式儀表板
│   ├── app.py                          # 儀表板主程式（讀 clean tables）
│   ├── requirements.txt
│   ├── Dockerfile
│   └── streamlit.yml                   # Swarm 部署
└── crawler_data/                       # 爬蟲輸出（CSV 備份）
```

---

### 🧰 4. 需求環境

**基礎環境**

| 項目 | 需求 |
|------|------|
| 作業系統 | macOS（Apple Silicon）或 Linux |
| 容器平台 | Docker Desktop / Docker Engine（已啟用 **Swarm 模式**） |
| 容器管理 | Portainer |
| Python | 3.12+（本機跑清理程式用） |
| 套件管理 | uv（或 pip） |
| overlay 網路 | `my_swarm_network`（需事先 `docker network create -d overlay`） |

**服務（以容器部署於 Swarm）**

| 服務 | 映像 | 用途 |
|------|------|------|
| MySQL | `mysql:8.0` | 資料庫 `mydb`（raw / clean tables） |
| RabbitMQ | `rabbitmq:3.6-management-alpine` | 任務佇列（broker），含管理介面 `:15672` |
| Flower | `mher/flower:2.0.0` | Celery 任務監控 `:5555` |
| 爬蟲映像 | 自建 `credit-card-crawler`（含 Playwright/chromium） | worker / producer |
| 儀表板 | 自建 `credit-card-dashboard`（Streamlit） | 視覺化 `:8501` |

**主要 Python 套件**

- 分散式 / 爬蟲：`celery`、`pika`、`requests`、`beautifulsoup4`、`playwright`（+ chromium）
- 資料庫 / 處理：`sqlalchemy`、`pymysql`、`cryptography`、`pandas`、`numpy`
- 儀表板：`streamlit`、`plotly`

> 各子目錄（`crawler_dist/`、`streamlit/`）的 `requirements.txt` 已列明完整套件版本；映像由各自的 `Dockerfile` 建置。

---

### ⚙️ 5. 系統架構與資料流程

採 **Celery + RabbitMQ** 的「派工 / 消費」模式，部署於 **Docker Swarm**、由 **Portainer** 管理；
爬完寫入 MySQL → 清理 → Streamlit 儀表板。

```
┌──────────────────────────────────────────────────────────────────────┐
│  資料來源：金管會統計  ／  11 家銀行官網  ／  PTT 信用卡版                  │
└──────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
   ① Producer（派工，跑一次）
      ・先把對應的 MySQL 表清空一次
      ・把工作拆成許多小任務，丟進 RabbitMQ 佇列
         - PTT  ：每個索引頁  → 一個任務（約 110+ 個）
         - 銀行 ：每家銀行    → 一個任務（11 個）
         - 金管會：單一下載    → 一個任務
                                   │
                                   ▼
   ② RabbitMQ（訊息佇列 broker）        ── Flower 監控介面（http://localhost:5555）
      佇列：ptt ／ banks ／ card_stats      看任務數量、成功 / 失敗、worker 狀態
                                   │
                                   ▼
   ③ Worker（消費者，常駐，可多副本平行）
      ・從佇列取任務 → 執行爬蟲
      ・結果「只 append」寫入 MySQL（清空只由 producer 做一次，避免互相覆蓋）
      ・三個來源各一組 worker（ptt 開 2 個平行）
                                   │
                                   ▼
   ④ MySQL（raw tables）
      credit_card_stats ／ banks ／ ptt_credit_card
                                   │
                                   ▼
   ⑤ clean_credit_cards.py（清理 + 特徵工程）
      民國轉西元、推噓數正規化、卡別 / 場景標籤、彙整 dashboard_agg…
                                   │
                                   ▼
   ⑥ MySQL（clean tables）
      *_clean 系列 + dashboard_agg
                                   │
                                   ▼
   ⑦ Streamlit 儀表板
      市佔率趨勢 ／ 回饋率比較 ／ 促銷熱度 ／ PTT 社群聲量
```

> 整個 ①～④ 部署於 **Docker Swarm**、由 **Portainer** 管理；⑤ 在本機執行，⑥⑦ 由儀表板服務讀取呈現。

| 階段 | 元件 | 說明 |
|------|------|------|
| 派工 | **Producer** | 跑一次：先清空對應 MySQL 表，再把工作拆成多個任務送進 RabbitMQ（PTT 每頁、銀行每家、金管會各一個任務） |
| 佇列 | **RabbitMQ** | 任務 broker，佇列 `ptt` / `banks` / `card_stats`；**Flower** 提供監控（:5555） |
| 消費 | **Worker** | 常駐、可多副本平行；從佇列取任務執行爬蟲，**append** 寫入 MySQL（清空只由 producer 做一次，避免互相覆蓋） |
| 儲存 | **MySQL** | raw tables（爬蟲輸出）→ `clean_credit_cards.py` 清理 → clean tables + `dashboard_agg` |
| 視覺化 | **Streamlit** | 讀 clean tables，呈現市佔率趨勢、回饋率比較、促銷熱度、PTT 社群聲量 |
| 容器管理 | **Portainer / Docker Swarm** | 部署與管理所有服務（worker / producer / RabbitMQ / 儀表板） |

詳細說明請參閱子目錄的 README：
- 爬蟲（含分散式部署與監控）：[crawler_dist/README.md](./crawler_dist/README.md)
- 儀表板：[streamlit/README.md](./streamlit/README.md)

---

### 🛠️ 6. 使用工具與開發進度

| 類別 | 工具 | 狀態 |
|------|------|------|
| 金管會爬蟲 | Python | ✅ 完成 |
| 各銀行官網爬蟲 | Python、Playwright | ✅ 完成 |
| PTT 爬蟲 | Python | ✅ 完成 |
| 分散式爬蟲架構 | Celery、Docker Swarm | ✅ 完成 |
| 訊息佇列 | RabbitMQ | ✅ 完成 |
| 任務監控 | Flower | ✅ 完成 |
| 資料清理管線 | Python、SQLAlchemy | ✅ 完成 |
| 儀表板 | Python、Streamlit | ✅ 完成 |
| 資料庫 | MySQL | ✅ 完成 |
| 容器管理 | Portainer、Docker Swarm | ✅ 完成 |
| 雲端平台 | GCP | 🚧 處理中 |
| 排程工作流 | Airflow | 🚧 處理中 |

---

### ⚠️ 7. 注意事項

- 資訊結果僅供參考，請依個人判斷做出合適決策
- 請勿將密碼寫死於程式碼或提交至版控