## 💳 專案名稱：銀行信用卡分散式爬蟲和儀表板

---

### 🔍 1. 可以分析什麼

> 銀行行銷團隊每天面對 **10多家競爭對手**，卻沒有一個統一平台能即時掌握：
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
- 🏦 各大銀行信用卡官網（國泰世華、玉山、富邦、台新、中信等 10+ 家）
- 💬 PTT 信用卡版

---

### 🛠️ 3. 使用工具

| 類別 | 工具 |
|------|------|
| 語言／框架 | Python 3.12 |
| 雲端平台 | GCP |
| 容器管理 | Portainer |
| 資料庫 | MySQL |
| 排程工作流 | Airflow（規劃中） |
| 訊息佇列 | RabbitMQ（規劃中） |

---

### 📁 4. 專案結構

```
.
├── scraper_banks.py          # 各銀行官網爬蟲（Playwright 動態渲染）
├── fac_crawler.py            # 金管會統計資料爬蟲
├── ptt_credit_card_crawler.py# PTT 信用卡版爬蟲
├── ctbc_cards.py             # 中信卡片清單管理（CSV 後備 + 自動同步）
├── ctbc_cards.csv            # 中信手動維護清單（可直接用 Excel 編輯）
├── card_common.py            # 爬蟲共用模組（欄位定義、雜訊過濾、輸出工具）
├── clean_credit_cards.py     # 資料清理 → 寫回 MySQL
├── app.py                    # Streamlit 互動式儀表板
├── db_common.py              # MySQL 讀寫共用模組
└── crawler_data/             # 爬蟲輸出（CSV）
    ├── banks.csv
    ├── credit_card_stats.csv
    └── ptt_credit_card.csv
```

---

### ⚙️ 5. 資料流程

```
金管會 ──────────────────────────────────────────────┐
                                                      │
各銀行官網 ──[scraper_banks.py / Playwright]──────────┤
                                                      ▼
PTT 信用卡版 ──[ptt_credit_card_crawler.py]──── MySQL (raw tables)
                                                      │
                                              clean_credit_cards.py
                                                      │
                                              MySQL (clean tables)
                                                      │
                                                  app.py
                                                      │
                                             Streamlit 儀表板
```

---

### 🕷️ 6. 爬蟲說明

#### `scraper_banks.py`（各銀行官網）

使用 Playwright 動態渲染，支援 10+ 家銀行，具備：

- **雙策略擷取**：JS 注入（卡名葉子節點偵測）+ href 連結比對，兩種方式互補
- **反偵測強化**：抹除 `webdriver` 指紋、偽裝 UA / sec-ch-ua / WebGL，優先使用系統真實 Chrome
- **導覽區排除**：自動跳過 nav / header / footer / sidebar，避免選單文字混入卡名
- **卡名雜訊過濾**：黑名單關鍵字、長度限制、標點密度過濾、結尾必須為「卡/Card」
- **中信特殊處理**：中信官網有 WAF（APP-1053）防護，預設改讀 `ctbc_cards.csv` 靜態清單；加 `--ctbc-dynamic` 參數可嘗試動態爬取，抓到新卡自動寫回 CSV

```bash
# 爬取全部銀行
python scraper_banks.py

# 只爬單一銀行
python scraper_banks.py --bank esun

# 開啟瀏覽器視窗（非 headless，方便偵錯）
python scraper_banks.py --show --debug

# 嘗試動態爬中信（有可能被 WAF 擋）
python scraper_banks.py --ctbc-dynamic
```

#### `fac_crawler.py`（金管會）

直接下載金管會公開統計 CSV（`banking66.csv`），儲存至 `crawler_data/` 並同步寫入 MySQL。

```bash
python fac_crawler.py
```

#### `ptt_credit_card_crawler.py`（PTT）

爬取 PTT 信用卡版 2025 年至今的文章，功能包含：

- 二分搜尋估算起始頁，縮短不必要的爬取時間
- 批次寫入（每 100 筆存一次），兼顧效能與斷點保護
- 連續 2 頁皆為舊文章自動停止
- 支援斷點恢復（重跑 = 清空 MySQL 後重寫）

```bash
python ptt_credit_card_crawler.py
```

---

### 🧹 7. 資料清理

`clean_credit_cards.py` 負責將原始爬蟲資料清理、特徵工程後寫回 MySQL：

| 原始表 | 清理後表 | 主要處理 |
|--------|----------|----------|
| `credit_card_stats` | `credit_card_stats_clean` | 民國年轉西元、數值欄轉型、計算淨增卡數、有效卡率、卡均簽帳金額 |
| `banks` | `banks_clean` | 合併回饋亮點、解析最高回饋率（%）、卡別多標籤展開、適用場景關鍵字標記 |
| `ptt_credit_card` | `ptt_credit_card_clean` | 推噓數正規化（「爆」→100、「Xn」→負數）、銀行關鍵字提及標記、年月欄位 |
| — | `dashboard_agg` | 長表彙整（metric / dim / value），供儀表板 KPI 快取使用 |

```bash
# 清理並寫入（會 TRUNCATE 清理後的表再重寫，不動原始表）
python clean_credit_cards.py

# 原始表還沒進 DB 時，從 CSV 自動建立
SEED_FROM_CSV=1 CSV_DIR=./crawler_data python clean_credit_cards.py
```

---

### 📊 8. Streamlit 儀表板（`app.py`）

執行方式：

```bash
# 本機啟動
streamlit run app.py

# Docker 環境：密碼由環境變數帶入，勿寫死於程式碼
MYSQL_PASSWORD=<your_password> streamlit run app.py
```

儀表板共 5 個分頁：

| 分頁 | 內容 |
|------|------|
| 📈 市場概覽 | KPI 卡（流通卡數、有效卡數、簽帳金額、循環餘額）、簽帳趨勢、市佔排名 |
| 🏦 機構分析 | 市占演變、HHI 市場集中度、逾期率趨勢、YoY 年增率 |
| 💬 社群聲量 | PTT 月貼文量、各銀行被提及次數、熱門貼文 Top 10、文字雲 |
| 🃏 產品比較 | 卡片回饋率分布、各銀行平均回饋率、卡別 × 場景熱力圖、並排比較（最多 4 張） |
| 🔍 優惠篩選 | 依銀行、卡別、適用場景、最低回饋率篩選，一鍵前往申辦頁面 |

---

### 🗄️ 9. 資料庫設定

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

### 📅 10. 開發進度

| 項目 | 狀態 |
|------|------|
| 金管會爬蟲 | ✅ 完成 |
| 各銀行官網爬蟲 | ✅ 完成 |
| PTT 爬蟲 | ✅ 完成 |
| 資料清理管線 | ✅ 完成 |
| Streamlit 儀表板 | ✅ 完成 |
| Airflow 排程工作流 | 🚧 處理中 |
| RabbitMQ 訊息佇列 | 🚧 處理中 |
| 分散式爬蟲架構 | 🚧 處理中 |

---

### ⚠️ 11. 注意事項

- 資訊結果僅供參考，請依個人判斷做出合適決策
- 爬蟲請勿過度頻繁請求，PTT 預設間隔 0.4 秒，請勿任意調低
- 部分銀行官網有 WAF 防護（如中信），若動態爬取失敗會自動 fallback 至靜態清單