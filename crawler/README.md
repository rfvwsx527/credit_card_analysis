# 台灣信用卡爬蟲（雙來源版）

兩支獨立爬蟲，各自可單獨執行，輸出格式一致方便合併分析。

## 📁 檔案結構

```
tw_card_scraper/
├── common.py            # 共用：欄位定義、雜訊過濾、CSV 輸出
├── scraper_banks.py     # 【Playwright】爬各銀行官網（突破 JS / 反爬蟲）
├── scraper_roocash.py   # 【requests】爬 roo.cash（靜態、輕量快速）
├── merge.py             # 合併兩支的輸出
└── requirements.txt
```

## ⚡ 安裝

```bash
pip install -r requirements.txt
python -m playwright install chromium    # 只有 scraper_banks.py 需要
```

## 🚀 使用

### 1. 爬各銀行官網（Playwright）

```bash
python scraper_banks.py                 # 全部銀行（背景無視窗）
python scraper_banks.py --bank esun     # 只爬玉山
python scraper_banks.py --show          # 顯示瀏覽器視窗（除錯）
python scraper_banks.py --debug         # 詳細 log + 每家存截圖 debug_xxx.png
```

支援：`esun`（玉山）、`cathaybk`（國泰世華）、`ctbc`（中信）、`fubon`（富邦）、`taishin`（台新）、`sinopac`（永豐）

### 2. 爬 roo.cash（requests）

```bash
python scraper_roocash.py               # 全部 16 家銀行
python scraper_roocash.py --bank taishin
python scraper_roocash.py --debug
```

支援：`cub`、`ctbc`、`esun`、`taishin`、`fubon`、`sinopac`、`hsbc`、`scb`、`dbs`、`ubot`、`mega`、`firstbank`、`yuanta`、`kgi`、`scsb`、`tcb`

### 3. 合併兩份結果

```bash
python merge.py banks_202605.csv roocash_202605.csv
```

官網資料優先，roo.cash 補充官網沒抓到的卡片，並標記每筆來源。

## 📊 輸出欄位

`銀行名稱 / 銀行代碼 / 卡片名稱 / 卡片類型 / 回饋亮點1~3 / 申辦連結 / 資料來源 / 更新時間`

## 🔧 兩支差異

| | scraper_banks.py | scraper_roocash.py |
|---|---|---|
| 技術 | Playwright（真實瀏覽器） | requests（純 HTTP） |
| 來源 | 各銀行官網 | roo.cash 比較平台 |
| 資料 | 最原始、最即時 | 第三方整理，可能慢一點 |
| 速度 | 慢（每頁數秒） | 快 |
| 反爬蟲 | 能突破 JS / Cloudflare | 不需要（靜態頁） |
| 維護成本 | 高（官網常改版） | 低（結構穩定） |

## ⚠️ 調整 selector

若某銀行官網改版導致抓到 0 筆，編輯 `scraper_banks.py` 裡的 `BANK_CONFIGS`，
用 `--show --debug` 開瀏覽器觀察，更新該銀行的 `card_sel`。

roo.cash 若改版，調整 `scraper_roocash.py` 的 `extract_highlights()` 或 h3 解析邏輯。

## 📅 每月自動更新（cron 範例）

```bash
0 2 1 * * cd /path && python scraper_roocash.py && python scraper_banks.py && python merge.py banks_$(date +\%Y\%m).csv roocash_$(date +\%Y\%m).csv
```
