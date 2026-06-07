# 信用卡分散式爬蟲 API 映像(uv + uvicorn)
# 建置: docker build -t rfvwsx527/credit-card-api:1.0 .
# 推送: docker push rfvwsx527/credit-card-api:1.0
#
# 此映像「不含」playwright / 爬蟲程式 —— API 只負責查 DB 與派工,故很輕量。
FROM python:3.12-slim

# 安裝 uv(對齊部署 command 使用 `uv run`)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# 應用程式根目錄 = /api;對應 swarm command 的 `cd /api`
WORKDIR /api

# 先裝相依(利用 layer cache);有 uv.lock 就用 --frozen
COPY pyproject.toml ./
COPY uv.loc[k] ./
RUN uv sync --no-dev || uv sync

# 複製套件原始碼:程式在 /api/api/*,模組路徑 api.main:app
COPY api/ ./api/

# 在映像內建一份空的 .env,讓 `uv run --env-file=.env` 不會因檔案缺失而失敗。
# 實際連線值由 swarm compose 的 environment:(或 docker run -e)注入;
# 都沒給時,api/config.py 內的預設值會生效。
RUN touch .env

ENV PYTHONUNBUFFERED=1 TZ=Asia/Taipei PYTHONPATH=/api

EXPOSE 8887

# 預設啟動命令(swarm compose 的 command 會覆寫,但本機 docker run 也能直接用)
CMD ["bash", "-c", "uv run --env-file=.env uvicorn api.main:app --host 0.0.0.0 --port 8887"]
