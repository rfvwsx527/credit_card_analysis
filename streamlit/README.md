# 💳 信用卡市場分析儀表板（Streamlit）

讀取 MySQL 中清理後的信用卡資料，呈現台灣信用卡市場的發卡、競爭、產品與 PTT 社群聲量。

## 執行方式

**本機執行**

```bash
cd streamlit
pip install -r requirements.txt
export MYSQL_HOST=localhost MYSQL_PORT=3306 MYSQL_DB=mydb MYSQL_USER=root MYSQL_PASSWORD='你的密碼'
streamlit run app.py
```

**Docker Swarm 部署**

```bash
cd streamlit
docker network create -d overlay my_swarm_network 2>/dev/null || true
docker build -t credit-card-dashboard:1.0 .
docker node update --label-add streamlit=true $(docker node ls -q)   # 自動帶入目前節點 ID
docker stack deploy -c streamlit.yml streamlit
```

完成後開啟 <http://localhost:8501>。

> `streamlit.yml` 以 `node.labels.streamlit==true` 約束節點，**部署前務必先貼上 label**，否則服務會卡在 pending。

> 執行前請先用清理程式建立 `*_clean` 資料表；連線參數可用環境變數調整。

## 呈現的資訊

頂部 KPI：流通卡數、有效卡數、本月簽帳、循環餘額、機構數。四個分頁：

- **市場總覽**：簽帳金額趨勢、卡數 vs 循環餘額、簽帳／卡數 Top N
- **機構競爭**：卡均簽帳、逾期率、簽帳 vs 卡數泡泡圖
- **產品分析**：卡別分布、各行產品數、產品明細
- **社群聲量**：PTT 月貼文量、分類占比、各銀行聲量、熱門貼文 Top 10

側邊欄可選月份、調整排名顯示數量。