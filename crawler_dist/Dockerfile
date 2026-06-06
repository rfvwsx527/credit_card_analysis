# 信用卡分散式爬蟲映像（Celery worker / producer 共用）
# 建置： docker build -t credit-card-crawler:1.0 .
#
# 注意：banks 爬蟲用 Playwright，需要瀏覽器，映像較大。
# 若只跑 ptt / card_stats，可自行精簡掉 playwright 安裝。
FROM python:3.12-slim

WORKDIR /app

# Playwright 執行 chromium 需要的系統函式庫
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation libnss3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 安裝 chromium（banks 爬蟲用）
RUN python -m playwright install chromium

# 複製程式：頂層爬蟲模組 + crawler 套件
COPY card_common.py ctbc_cards.py db_common.py fac_crawler.py \
     ptt_credit_card_crawler.py scraper_banks.py ./
COPY crawler/ ./crawler/

ENV PYTHONUNBUFFERED=1 TZ=Asia/Taipei PYTHONPATH=/app

# 預設啟動 ptt worker；實際命令由 compose 的 command 覆寫
CMD ["celery", "-A", "crawler.worker", "worker", "--loglevel=info", "-Q", "ptt", "-E"]
