# 信用卡分散式爬蟲映像（Celery worker / producer / scheduler 共用）
# 建置： docker build -t credit-card-crawler:1.0 .
#
# 套件安裝改用 uv（Astral 的高速套件管理器，pip 的替代品）。
# 以 requirements.txt 為套件來源（內含 celery / pika / apscheduler / loguru，
# 是比 pyproject.toml 更完整的清單）；uv pip install --system 直接裝進系統環境，
# 因此容器內仍可用 `python -m crawler.xxx` / `celery ...` 直接啟動（不需 uv run）。
#
# 注意：banks 爬蟲用 Playwright，需要瀏覽器，映像較大。
# 若只跑 ptt / card_stats，可自行精簡掉 playwright 安裝。
FROM python:3.12-slim

WORKDIR /app

# 取得 uv 官方二進位（多階段 COPY，不經 pip）
# 需要釘版本時把 latest 換成例如 0.5.11
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Playwright 執行 chromium 需要的系統函式庫
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation libnss3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# 用 uv 安裝 Python 套件（--system：裝進系統環境；--no-cache：不留快取縮小映像）
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt
# 安裝 chromium（banks 爬蟲用）
RUN python -m playwright install chromium

# 複製程式：頂層爬蟲模組 + 清理程式 + crawler 套件
# clean_credit_cards.py：排程器爬完後呼叫的資料清理程式
# ctbc_cards.csv：banks 爬蟲(ctbc)執行時需要的對照檔
COPY card_common.py ctbc_cards.py ctbc_cards.csv db_common.py fac_crawler.py \
     ptt_credit_card_crawler.py scraper_banks.py clean_credit_cards.py ./
COPY crawler/ ./crawler/

ENV PYTHONUNBUFFERED=1 TZ=Asia/Taipei PYTHONPATH=/app

# 預設啟動 ptt worker；實際命令由 compose 的 command 覆寫
# （worker：celery ...；producer：python -m crawler.producer_xxx；scheduler：python -m crawler.scheduler）
CMD ["celery", "-A", "crawler.worker", "worker", "--loglevel=info", "-Q", "ptt", "-E"]