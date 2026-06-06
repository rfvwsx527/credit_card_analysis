# 💳 信用卡市場分析儀表板（Streamlit）

讀取 MySQL 中清理後的信用卡資料，呈現台灣信用卡市場的發卡、競爭、產品、優惠與 PTT 社群聲量；社群聲量分頁並提供貼文內容**中文文字雲**與可篩選的熱門貼文清單。

---

## 資料來源

MySQL `mydb` 內清理後的三張資料表（名稱可用環境變數覆寫）：

| 用途 | 預設資料表 | 覆寫環境變數 | 內容 |
|------|-----------|-------------|------|
| 發卡統計 | `credit_card_stats_clean` | `TBL_STATS` | 金管會逐月發卡統計（流通卡數、簽帳金額、循環餘額、逾期率…） |
| 銀行產品 | `banks_clean` | `TBL_BANKS` | 各銀行信用卡產品、卡片類型、回饋亮點、申辦連結 |
| 社群聲量 | `ptt_credit_card_clean` | `TBL_PTT` | PTT 信用卡版貼文（標題、內文、分類、推噓數、年月、網址…） |

> 執行前請先用清理程式建立上述 `*_clean` 資料表。

---

## 🧰 需求環境

**本機執行**

| 項目 | 需求 |
|------|------|
| 作業系統 | macOS（Apple Silicon）或 Linux |
| Python | 3.12+ |
| 資料庫 | MySQL 8（資料庫 `mydb`，且已建立 `*_clean` 清理後資料表） |
| 中文字型 | 文字雲需 CJK 字型；本機若無，用 `WC_FONT_PATH` 指向字型檔（如 Noto Sans CJK） |

**Docker 部署額外需求**

| 項目 | 需求 |
|------|------|
| 容器平台 | Docker Desktop / Docker Engine（已啟用 **Swarm 模式**） |
| 容器管理 | Portainer（可選，用於介面管理） |
| overlay 網路 | `my_swarm_network`（需事先 `docker network create -d overlay`） |
| 節點 label | `streamlit=true`（儀表板）、`mysql=true`（MySQL 服務） |
| 字型 | 映像已內建 `fonts-noto-cjk`，文字雲可直接顯示中文 |

**主要 Python 套件**

- 介面 / 圖表：`streamlit`、`plotly`、`pandas`
- 資料庫：`sqlalchemy`、`pymysql`、`cryptography`
- 中文文字雲：`wordcloud`、`jieba`

> 完整套件版本見 `requirements.txt`；映像由 `Dockerfile` 建置（Python 3.12-slim + uv，內建 Noto Sans CJK 字型）。

---

## 📊 儀表板分頁

**頂部 KPI**：流通卡數、有效卡數、本月簽帳、循環餘額、統計機構數五張卡，前四張附**環比（MoM）變化**。

| 分頁 | 主要內容 |
|------|----------|
| 📈 市場總覽 | 每月簽帳趨勢、流通卡數 vs 循環餘額、HHI 市場集中度、簽帳與流通卡數 Top N |
| 🏦 機構競爭 | 簽帳市占率演變、逾期率趨勢、卡均簽帳金額排名、泡泡圖（簽帳 vs 流通卡數） |
| 💬 社群聲量 | PTT 月貼文量、各銀行被提及次數、聲量隨時間變化、中文文字雲、熱門貼文 Top 10 |
| 🃏 產品比較 | 卡別分布、各銀行平均回饋率、卡別 × 場景熱力圖、並排比較（最多 4 張） |
| 🔍 優惠篩選 | 依銀行、卡別、適用場景、最低回饋率篩選，一鍵前往申辦頁面 |

---

## ▶️ 執行方式

### 本機執行

```bash
cd streamlit
pip install -r requirements.txt
export MYSQL_HOST=localhost MYSQL_PORT=3306 MYSQL_DB=mydb \
       MYSQL_USER=root MYSQL_PASSWORD='你的密碼'
streamlit run app.py
```

開啟 <http://localhost:8501>。

> 文字雲需要 `wordcloud`、`jieba` 及一套**中文字型**。本機若沒有 CJK 字型，可用環境變數 `WC_FONT_PATH` 指向字型檔（例如 Noto Sans CJK）。缺字型或套件時，文字雲會自動退回「高頻詞長條圖」，不會中斷。

### 先部署 MySQL（Docker Swarm）

儀表板與爬蟲共用同一個 swarm 內的 MySQL（服務名 `mysql_mysql`）。若尚未部署，用 `mysql.yml`：

```bash
# 1) overlay 網路（沒有才建）
docker network create -d overlay my_swarm_network 2>/dev/null || true

# 2) 幫要跑 DB 的節點貼 label
docker node update --label-add mysql=true $(docker node ls -q)

# 3) 部署 MySQL + phpMyAdmin
docker stack deploy -c mysql.yml mysql
```

部署後：

- 服務名 **`mysql_mysql`**（stack `mysql` + service `mysql`）；同一 overlay 網路內其他服務（爬蟲 worker、儀表板）即可用此主機名連線
- phpMyAdmin 網頁介面：<http://localhost:8080>
- 資料以具名 volume `mysql_data` 持久化，重新部署不會遺失
- `mysql.yml` 預設 `MYSQL_ROOT_PASSWORD` 為教學用明碼、資料庫 `mydb` 自動建立；正式環境請改用 **docker secret**

> 已經有 `mysql_mysql` 在跑（例如跟爬蟲一起部署過）就跳過這步，儀表板會直接連到它。

---

### Docker Swarm 部署（儀表板）

```bash
cd streamlit

# 1) 建立 overlay 網路
docker network create -d overlay my_swarm_network 2>/dev/null || true

# 2) 建置映像並推送到 Docker Hub
docker build -t rfvwsx527/credit-card-dashboard:1.0 .
docker push rfvwsx527/credit-card-dashboard:1.0

# 3) 幫節點加上 label
docker node update --label-add streamlit=true $(docker node ls -q)

# 4) 部署
docker stack deploy -c streamlit.yml streamlit
```

完成後開啟 <http://localhost:8501>。

`streamlit.yml` 預設設定：

- 連線 swarm 內的 MySQL：`MYSQL_HOST=mysql_mysql`（與爬蟲共用同一個 DB，須在同一 overlay 網路）
- `deploy`：`replicas: 1`、約束 `node.labels.streamlit==true`、失敗自動重啟
- 對外埠 `8501:8501`
- 映像內建 `fonts-noto-cjk`，文字雲可直接顯示中文

> ⚠️ `streamlit.yml` 內的 `MYSQL_PASSWORD` 為教學用明碼；正式環境請改用 **docker secret**，並更換已外洩的密碼。

### 查看狀態 / 疑難排解

```bash
docker service ls
docker service ps streamlit_streamlit_dashboard --no-trunc
docker service logs -f streamlit_streamlit_dashboard
```

| 問題 | 原因與解法 |
|------|-----------|
| 服務一直 pending | 節點未加 `streamlit=true` label，或 overlay 網路未建立 |
| 起來很慢 | 正常收斂過程，健康檢查 `start-period=20s`，約需 20～50 秒 |
| 畫面顯示 DB 連不上 | 確認 `mysql_mysql` 服務在線、且與儀表板在同一 `my_swarm_network` 網路 |

---

## 互動與篩選

- **聚焦**：點選任一橫條／圓餅／泡泡圖，或使用側邊欄下拉，可將圖表鎖定到單一機構／銀行；側邊欄底部「顯示全部（清除所有聚焦）」一鍵還原
- **側邊欄篩選**：機構類型、統計月份、趨勢觀察區間、排名顯示前 N 名

---

## 名詞與計算說明

- **金額單位**：原始為「新臺幣百萬元」，圖表換算為「億元」（÷100）；卡數換算「萬張」（÷1e4）
- **卡均簽帳金額**：本月簽帳金額 ÷ 有效卡數
- **HHI**：各機構簽帳市占百分比的平方和，> 2500 一般視為高度集中
- **社群聲量**：以關鍵字比對 PTT 標題＋內文是否「提及」該銀行（非情緒分析）
- **卡片類型**：原始複合標籤以「/」拆成多標籤（現金回饋／紅利點數／哩程／聯名卡／高階卡／一般）
- **適用場景**：依回饋亮點關鍵字比對（海外、旅遊、行動支付、加油、餐飲、超商、網購、影音等），一張卡可屬多場景
- **最高回饋率**：從回饋亮點文字解析出的最大百分比；部分卡無明確數字故顯示「—」

---

## 技術棧

Streamlit · Plotly · pandas · SQLAlchemy + PyMySQL · wordcloud + jieba（中文文字雲）。容器以 Python 3.12-slim 為基底、`uv` 安裝套件、內建 Noto Sans CJK 字型。

---

資料來源：金管會發卡統計 · 各銀行信用卡 · PTT 信用卡版