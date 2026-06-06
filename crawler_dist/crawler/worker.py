# -*- coding: utf-8 -*-
"""
crawler/worker.py — Celery app
=====================================================================
啟動 worker(比照你的 twse/tpex)：
  celery -A crawler.worker worker --loglevel=info --hostname=%h -Q ptt -E
  celery -A crawler.worker worker --loglevel=info --hostname=%h -Q banks -E
  celery -A crawler.worker worker --loglevel=info --hostname=%h -Q card_stats -E
"""
from celery import Celery
from crawler.config import BROKER_URL

app = Celery(
    "crawler",
    broker=BROKER_URL,
    include=[
        "crawler.tasks_ptt",
        "crawler.tasks_banks",
        "crawler.tasks_fac",
    ],
)

# 任務路由：各 task 預設進對應佇列(producer 也可用 queue= 覆寫)
app.conf.task_routes = {
    "crawler.tasks_ptt.*": {"queue": "ptt"},
    "crawler.tasks_banks.*": {"queue": "banks"},
    "crawler.tasks_fac.*": {"queue": "card_stats"},
}
app.conf.task_acks_late = True            # 任務跑完才 ack,worker 掛掉可重派
app.conf.worker_prefetch_multiplier = 1   # 一次抓一個,長任務分配較平均
app.conf.timezone = "Asia/Taipei"
