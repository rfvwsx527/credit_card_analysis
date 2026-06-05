# 💳 信用卡市場分析儀表板（Streamlit）

讀取 MySQL 中清理後的信用卡資料，呈現台灣信用卡市場的發卡、競爭、產品、優惠與 PTT 社群聲量；社群聲量分頁並提供貼文內容**中文文字雲**與可篩選的熱門貼文清單。

## 資料來源

MySQL `mydb` 內清理後的三張資料表（名稱可用環境變數覆寫）：

| 用途 | 預設資料表 | 覆寫環境變數 | 內容 |
| --- | --- | --- | --- |
| 發卡統計 | `credit_card_stats_clean` | `TBL_STATS` | 金管會逐月發卡統計（流通卡數、簽帳金額、循環餘額、逾期率…） |
| 銀行產品 | `banks_clean` | `TBL_BANKS` | 各銀行信用卡產品、卡片類型、回饋亮點、申辦連結 |
| 社群聲量 | `ptt_credit_card_clean` | `TBL_PTT` | PTT 信用卡版貼文（標題、內文、分類、推噓數、年月、網址…） |

> 執行前請先用清理程式建立上述 `*_clean` 資料表。

連線參數環境變數：`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DB`、`MYSQL_USER`、`MYSQL_PASSWORD`（皆有預設值，密碼預設為空）。

## 執行方式

### 本機執行

```bash
cd streamlit
pip install -r requirements.txt
export MYSQL_HOST=localhost MYSQL_PORT=3306 MYSQL_DB=mydb MYSQL_USER=root MYSQL_PASSWORD='你的密碼'
streamlit run app.py
```

開啟 <http://localhost:8501>。

> 文字雲需要 `wordcloud`、`jieba`（已列於 `requirements.txt`）以及一套**中文字型**。本機若沒有 CJK 字型，可用環境變數 `WC_FONT_PATH` 指向字型檔（例如 Noto Sans CJK）。缺字型或套件時，文字雲會自動退回「高頻詞長條圖」，不會中斷。

### Docker Swarm 部署

`streamlit.yml` 使用外部 overlay 網路、並以節點 label 約束服務落點，所以部署前要先建網路、建映像、貼 label：

```bash
cd streamlit

# 1) 建立 overlay 網路（streamlit.yml 以 external: true 引用，必須先存在）
docker network create -d overlay my_swarm_network 2>/dev/null || true

# 2) 建置本機映像（單節點 Swarm 可直接用本機映像；多節點需推送 registry）
docker build -t credit-card-dashboard:1.0 .

# 3) 幫節點加上 streamlit=true 的 label（約束才有節點可落，否則服務卡 pending）
docker node update --label-add streamlit=true $(docker node ls -q)   # 或將 $(...) 換成 self 只標目前節點

# 4) 部署
docker stack deploy -c streamlit.yml streamlit
```

完成後開啟 <http://localhost:8501>。

`streamlit.yml` 已內建設定：

- 連線宿主機 MySQL：`MYSQL_HOST=host.docker.internal`，並用 `extra_hosts: host-gateway` 讓容器連得到宿主機（DB 若也在 swarm 內，請改成該服務名）。
- 資料表名稱（`TBL_STATS`/`TBL_BANKS`/`TBL_PTT`）、時區 `TZ=Asia/Taipei`。
- `deploy`：`replicas: 1`、約束 `node.labels.streamlit==true`、失敗自動重啟。
- 對外埠 `8501:8501`。

> 映像以 `uv` 安裝相依套件，並內建 `fonts-noto-cjk` 中文字型（已預設 `WC_FONT_PATH`），文字雲可直接顯示中文。

> ⚠️ `streamlit.yml` 內的 `MYSQL_PASSWORD` 為教學用明碼；正式環境請改用 **docker secret**，並更換已外洩的密碼。

### 查看狀態 / 疑難排解

```bash
docker service ls
docker service ps streamlit_streamlit_dashboard --no-trunc   # 看任務狀態與錯誤
docker service logs -f streamlit_streamlit_dashboard          # 看 App 日誌
```

- 服務一直 **pending**：通常是沒有節點帶 `streamlit=true` label（見上方步驟 3），或 overlay 網路尚未建立。
- 部署後「等很久才起來」：屬正常收斂過程——健康檢查 `start-period=20s`、之後每 30 秒一次，約需 20～50 秒才會顯示 healthy；本機映像在 Swarm 解析 digest 也會花一點時間（可加 `--resolve-image never` 略過）。
- 畫面顯示連不到資料庫：檢查 `MYSQL_HOST` 與宿主機 MySQL 是否可連（Streamlit 健康端點只看伺服器是否啟動，DB 連不上時服務仍為 healthy 但畫面為錯誤頁）。

## 呈現的資訊

**頂部 KPI**：流通卡數、有效卡數、本月簽帳、循環餘額、統計機構數五張卡，前四張附**環比（MoM）變化**，並標註所選月份相對上個月的增減。

**五個分頁：**

### 📈 市場總覽
- 每月簽帳金額趨勢（億元，面積圖）
- 流通卡數 vs 循環信用餘額（雙 Y 軸）
- 本國銀行 vs 信用卡公司簽帳金額（依機構類型堆疊）
- 市場集中度 HHI 趨勢（含 2500 高度集中參考線）
- 簽帳金額 Top N、流通卡數 Top N（橫條，可點擊聚焦該機構）

### 🏦 機構競爭
- 簽帳市占率演變（可多選機構互相比較）
- 逾期帳款比率趨勢
- 卡均簽帳金額 Top N、逾期帳款比率 Top N
- 簽帳金額 vs 流通卡數泡泡圖（泡泡＝機構）

### 💼 產品分析
- 信用卡主卡別分布（甜甜圈圖）
- 各銀行收錄產品數
- 各卡別最高回饋率分布（箱型圖）
- 最高回饋率 Top 15
- 產品明細表（含回饋亮點）

### 💳 優惠比較
- 篩選：銀行、卡片類型（多選）、適用場景（多選）、最低回饋率
- 優惠比較表：場景標籤、最高回饋率、回饋亮點與**申辦連結**
- 並排比較：自選 2～4 張卡逐項對照
- 各銀行平均最高回饋率、各適用場景的卡片數
- 銀行 × 卡片類型分布熱力圖

### 💬 社群聲量
- PTT 每月貼文量（每根長條標示 `2025/1` 樣式月份）
- 貼文分類占比（甜甜圈圖）
- 各銀行社群聲量＝被提及篇數（橫條，可點擊聚焦該銀行）
- 聲量隨時間變化（Top 5 被提及銀行）
- **貼文內容文字雲**（圓形，jieba 中文斷詞並過濾停用詞與網址雜訊）
- **熱門貼文 Top 10**：排名、標題、分類、推噓數（長條呈現）、年月、提及內容與**貼文網址**連結；標題右側可用**推噓數範圍**即時篩選，下方顯示符合條件篇數

## 互動與篩選

- **聚焦**：點選任一橫條／圓餅／泡泡圖，或使用側邊欄各分頁的「聚焦」下拉，可將該分頁圖表鎖定到單一機構／銀行／卡別；側邊欄底部的「顯示全部（清除所有聚焦）」一鍵還原。
- **側邊欄篩選**：機構（銀行／信用卡公司）、統計月份（KPI／排名）、趨勢觀察區間、排名顯示前 N 名。

## 名詞與計算說明

- **金額單位**：原始為「新臺幣百萬元」，圖表多換算為「億元」（÷100）；卡數換算「萬張」（÷1e4）。
- **卡均簽帳金額**：本月簽帳金額 ÷ 有效卡數。
- **HHI**：各機構簽帳市占百分比的平方和，> 2500 一般視為高度集中。
- **社群聲量**：以關鍵字比對 PTT 標題＋內文是否「提及」該銀行（非情緒分析）。
- **卡片類型**：原始複合標籤以「/」拆成多標籤（現金回饋／紅利點數／哩程／聯名卡／高階卡／一般）。
- **適用場景**：依回饋亮點關鍵字比對（海外、旅遊、行動支付、加油、餐飲、超商、網購、影音等），一張卡可屬多場景；無命中標為「綜合／未標示」。
- **最高回饋率**：從回饋亮點文字解析出的最大百分比；部分卡無明確數字故顯示「—」。

## 技術棧

Streamlit · Plotly · pandas · SQLAlchemy + PyMySQL · wordcloud + jieba（中文文字雲）。容器以 Python 3.12-slim 為基底、`uv` 安裝套件、內建 Noto Sans CJK 字型。

---

資料來源：金管會發卡統計 · 各銀行信用卡 · PTT 信用卡版