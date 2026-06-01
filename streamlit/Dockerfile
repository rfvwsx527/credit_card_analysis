# 信用卡儀表板 Streamlit 映像
# 建置： docker build -t credit-card-dashboard:1.0 .
FROM python:3.12-slim

WORKDIR /app

# 先裝相依套件（利用 layer 快取）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式
COPY app.py .

EXPOSE 8501

# 健康檢查：用 Python 打 Streamlit 內建健康端點（slim 映像無 curl/wget）
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; \
  sys.exit(0) if urllib.request.urlopen('http://localhost:8501/_stcore/health').status==200 else sys.exit(1)"

# 啟動 Streamlit（headless、對外綁 0.0.0.0；關掉 CORS/XSRF 以利 Swarm ingress 轉發）
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.headless=true", "--browser.gatherUsageStats=false", \
     "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
