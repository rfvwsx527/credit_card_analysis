# -*- coding: utf-8 -*-
"""
routers/crawl.py — 爬蟲控制平面(派工 + 佇列監控)
=====================================================================
把任務送進 RabbitMQ,觸發 swarm 上常駐的 Celery worker 平行爬取。
行為對齊既有 producer:派工前先「清空一次」對應表,worker 全程只 append。

注意:
- PTT 需要頁碼範圍(start_page / end_page)。原 producer 會自動估算頁數,
  但那需要把 ptt 爬蟲模組打包進 API 映像;為保持 API 映像輕量,這裡改為
  「由呼叫端指定頁碼範圍」。要全自動估算請改觸發既有的 producer 服務。
- 金管會統計任務本身會自行 truncate→write,API 端不需先清空。
"""
import logging

from fastapi import APIRouter, HTTPException

from api import config, db, tasking
from api.schemas import CrawlBanksIn, CrawlPttIn, CrawlOut

log = logging.getLogger("api.crawl")
router = APIRouter(prefix="/api/v1/crawl", tags=["crawl 派工/監控"])


@router.get("/queues", summary="查三個佇列深度(皆 0 = 爬完)")
def queues():
    return {"queues": tasking.queue_stats()}


@router.post("/banks", response_model=CrawlOut, summary="派工:各銀行(每家一個任務)")
def crawl_banks(body: CrawlBanksIn):
    codes = [c.strip() for c in (body.codes or config.BANK_CODES) if c.strip()]
    if not codes:
        raise HTTPException(400, "沒有可派工的銀行代碼")

    truncated = False
    if body.truncate:
        db.refresh_tables()
        truncated = db.truncate(config.TABLE_BANKS)

    ids = [tasking.send_task(config.TASK_BANKS, config.QUEUE_BANKS, [code])
           for code in codes]
    log.info("派工 banks:%d 家 %s (truncated=%s)", len(ids), codes, truncated)
    return CrawlOut(
        enqueued=len(ids), queue=config.QUEUE_BANKS, truncated=truncated,
        task_ids=ids, detail=f"已派工 {len(ids)} 家銀行:{', '.join(codes)}")


@router.post("/ptt", response_model=CrawlOut, summary="派工:PTT(每頁一個任務)")
def crawl_ptt(body: CrawlPttIn):
    if body.end_page < body.start_page:
        raise HTTPException(400, "end_page 必須 >= start_page")

    truncated = False
    if body.truncate:
        db.refresh_tables()
        truncated = db.truncate(config.TABLE_PTT)

    pages = list(range(body.start_page, body.end_page + 1))
    ids = [tasking.send_task(config.TASK_PTT, config.QUEUE_PTT, [p]) for p in pages]
    log.info("派工 ptt:第 %d~%d 頁 共 %d 個 (truncated=%s)",
             body.start_page, body.end_page, len(ids), truncated)
    return CrawlOut(
        enqueued=len(ids), queue=config.QUEUE_PTT, truncated=truncated,
        task_ids=ids,
        detail=f"已派工第 {body.start_page}~{body.end_page} 頁,共 {len(ids)} 個任務")


@router.post("/ptt/all", response_model=CrawlOut,
             summary="派工:PTT 全部(自動估算頁數,等同重觸發 producer)")
def crawl_ptt_all():
    """送出一個『啟動任務』給 worker:由 worker(有 PTT 模組)自動清空表、
    估算 START_YEAR 起始頁、再把每一頁派成 crawl_ptt_page 任務。
    等同 `docker service update --force card_producer_card_producer_ptt`,但走 API。
    清空與派工都在該啟動任務內完成,API 端不先清空。"""
    tid = tasking.send_task(config.TASK_PTT_ALL, config.QUEUE_PTT, [])
    return CrawlOut(
        enqueued=1, queue=config.QUEUE_PTT, truncated=False, task_ids=[tid],
        detail=("已送出『PTT 全爬』啟動任務;worker 會自動估算頁數並派工"
                "(清空 ptt 表由該任務負責)。實際每頁任務數可用 /crawl/queues 觀察。"))


@router.post("/stats", response_model=CrawlOut, summary="派工:金管會統計(單一任務)")
def crawl_stats():
    # stats 任務內部自行 truncate→write,這裡不先清空
    tid = tasking.send_task(config.TASK_STATS, config.QUEUE_STATS, [])
    return CrawlOut(
        enqueued=1, queue=config.QUEUE_STATS, truncated=False,
        task_ids=[tid], detail="已派工金管會統計任務")
