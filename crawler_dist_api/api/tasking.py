# -*- coding: utf-8 -*-
"""
api/tasking.py — 派工 / 佇列監控
=====================================================================
API 作為「控制平面」:把 Celery 任務送進 RabbitMQ(send_task,不需 import
worker 端程式碼),並透過 RabbitMQ 管理 HTTP API 查詢佇列深度。

任務名稱與佇列必須與 crawler/worker.py 完全一致(見 api/config.py)。
"""
import logging

import requests
from celery import Celery

from api import config

log = logging.getLogger("api.tasking")

# 只當「producer/client」用,給 broker 即可(不需要 result backend)
celery_app = Celery("api_client", broker=config.broker_url())
celery_app.conf.task_default_delivery_mode = 2  # persistent


def send_task(name: str, queue: str, args: list | None = None) -> str:
    """送一個任務進指定佇列,回傳 task id。"""
    res = celery_app.send_task(name, args=args or [], queue=queue)
    return res.id


def queue_stats() -> list[dict]:
    """
    透過 RabbitMQ 管理 HTTP API 查三個佇列的深度。
    回傳 [{queue, messages, ready, unacked}] —— 三個皆 0 代表爬完。
    管理介面查不到時回傳錯誤說明(不丟例外,讓 /health 類查詢仍可用)。
    """
    base = (f"http://{config.RABBITMQ_HOST}:{config.RABBITMQ_MGMT_PORT}"
            f"/api/queues")
    auth = (config.RABBITMQ_ACCOUNT, config.RABBITMQ_PASSWORD)
    wanted = {config.QUEUE_PTT, config.QUEUE_BANKS, config.QUEUE_STATS}
    out: list[dict] = []
    try:
        resp = requests.get(base, auth=auth, timeout=5)
        resp.raise_for_status()
        by_name = {q.get("name"): q for q in resp.json()}
        for q in sorted(wanted):
            info = by_name.get(q, {})
            out.append({
                "queue": q,
                "messages": info.get("messages", 0),
                "ready": info.get("messages_ready", 0),
                "unacked": info.get("messages_unacknowledged", 0),
                "exists": q in by_name,
            })
    except Exception as e:  # noqa: BLE001
        log.warning("查詢 RabbitMQ 佇列失敗: %s", e)
        for q in sorted(wanted):
            out.append({"queue": q, "error": str(e)})
    return out
