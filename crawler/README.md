# 🏦 台灣信用卡資料爬蟲

自動抓取台灣各大銀行信用卡資訊、金管會統計數據與 PTT 討論文章。

## 環境安裝

```bash
uv sync
uv run playwright install chromium
```

## 使用方式

### 銀行官網爬蟲（Playwright）

```bash
# 爬取全部銀行
uv run python scraper_banks.py

# 爬取單一銀行
uv run python scraper_banks.py --bank esun

# 產生除錯截圖
uv run python scraper_banks.py --debug
```

支援銀行：`esun` `cathaybk` `taishin` `sinopac` `yuanta` `kgi` `dbs` `hsbc` `scb` `fubon` `ctbc`

輸出：`banks.csv`

---

### 金管會統計資料

```bash
uv run python fac_crawler.py
```

輸出：`crawler_data/credit_card_stats.csv`

---

### PTT 信用卡版爬蟲

```bash
uv run python ptt_credit_card_crawler.py
```

輸出：`crawler_data/ptt_credit_card.csv`

預設爬取 2025 年至今的文章，可修改 `ptt_credit_card_crawler.py` 頂部的 `START_YEAR` 調整範圍。

---

## 除錯截圖

執行 `--debug` 後會產生各銀行全頁截圖（`debug_<代碼>.png`），用於確認網頁實際呈現內容與排查爬取問題。

## 注意事項

- PTT 爬蟲預設 0.4 秒請求間隔，請勿縮短
- 中信（ctbc）使用 hardcode 清單，官網改版時需手動更新 `CTBC_CARDS`
