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

| 代碼 | 銀行名稱 | 爬取方式 |
|------|---------|---------|
| `esun` | 玉山銀行 | Playwright 動態 |
| `cathaybk` | 國泰世華銀行 | Playwright 動態 |
| `fubon` | 台北富邦銀行 | Playwright 動態 |
| `taishin` | 台新銀行 | Playwright 動態 |
| `sinopac` | 永豐銀行 | Playwright 動態 |
| `yuanta` | 元大銀行 | Playwright 動態（含分頁） |
| `kgi` | 凱基銀行 | Playwright 動態 |
| `dbs` | 星展銀行 | Playwright 動態 |
| `hsbc` | 滙豐銀行 | Playwright 動態 |
| `scb` | 渣打銀行 | Playwright 動態 |
| `ctbc` | 中國信託銀行 | 靜態清單（`ctbc_cards.csv`） |

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

```bash
uv run python fac_crawler.py
```

輸出：`crawler_data/credit_card_stats.csv`

---

### `ptt_credit_card_crawler.py`（PTT）

爬取 PTT 信用卡版 2025 年至今的文章，功能包含：

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