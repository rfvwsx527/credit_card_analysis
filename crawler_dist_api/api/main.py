# -*- coding: utf-8 -*-
"""
api/main.py — FastAPI 進入點(對應 swarm command: uvicorn api.main:app)
=====================================================================
信用卡分散式爬蟲 API:
  · 資料查詢:/api/v1/banks  /api/v1/ptt  /api/v1/stats  /api/v1/dashboard
  · 爬蟲控制:/api/v1/crawl/{banks,ptt,stats}  /api/v1/crawl/queues
互動式文件:/docs  (Swagger UI) 、 /redoc
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import __version__, config, db
from api.schemas import HealthOut
from api.routers import banks, ptt, stats, dashboard, crawl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class UTF8JSONResponse(JSONResponse):
    """明確在 Content-Type 帶上 charset=utf-8。
    FastAPI 預設回 `application/json`(無 charset),Safari 等瀏覽器在
    zh-TW 環境會用 Big5 去解 UTF-8 位元組 → 中文變亂碼。指定 charset 即可正常。"""
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="信用卡分散式爬蟲 API",
    version=__version__,
    description=(
        "查詢台灣各大銀行信用卡、PTT 討論、金管會發卡統計資料,"
        "並可透過 RabbitMQ 派工觸發 Celery + Docker Swarm 分散式爬蟲。"),
    default_response_class=UTF8JSONResponse,  # 全站回應都帶 charset=utf-8
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (banks.router, ptt.router, stats.router, dashboard.router, crawl.router):
    app.include_router(r)


@app.get("/", tags=["meta"], summary="服務資訊")
def root():
    return {
        "service": "credit-card-crawler-api",
        "version": __version__,
        "docs": "/docs",
        "endpoints": [
            "/api/v1/banks", "/api/v1/ptt", "/api/v1/stats",
            "/api/v1/dashboard", "/api/v1/crawl/queues",
        ],
    }


@app.get("/health", response_model=HealthOut, tags=["meta"], summary="健康檢查")
def health():
    ok = db.ping()
    return HealthOut(status="ok" if ok else "degraded", db=ok, version=__version__)


@app.on_event("startup")
def _startup():
    db.refresh_tables()
    logging.getLogger("api").info(
        "啟動完成 — MySQL=%s:%s/%s, RabbitMQ=%s:%s",
        config.DB_HOST, config.DB_PORT, config.DB_NAME,
        config.RABBITMQ_HOST, config.RABBITMQ_PORT)
