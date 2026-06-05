# 信用卡儀表板 Streamlit 映像（以 uv 安裝相依套件）
# 建置： docker build -t credit-card-dashboard:1.0 .
FROM python:3.12-slim

# 取得 uv 執行檔（從官方映像複製，固定版本以利重現；如要自動更新可改 :latest）
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/

WORKDIR /app

# 系統字型：文字雲顯示中文需要 CJK 字型（Noto Sans CJK）
# fonts-noto-cjk 會安裝到 /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 文字雲字型路徑（app.py 會優先讀取此環境變數）
ENV WC_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

# uv 行為：安裝進系統 Python、用複製而非硬連結（跨層較穩定）
ENV UV_SYSTEM_PYTHON=1 \
    UV_LINK_MODE=copy

# 先裝相依套件（利用 layer 快取）；以 uv 取代 pip
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

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