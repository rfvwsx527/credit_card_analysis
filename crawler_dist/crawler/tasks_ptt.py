# -*- coding: utf-8 -*-
"""
crawler/tasks_ptt.py — PTT 信用卡板(每個索引頁一個任務)
worker 只負責「抓某一頁 + 該頁文章內文 → append 進 DB」,
清空動作由 producer 事前做一次,避免平行 worker 互相清空。
"""
import time
import logging
import pandas as pd

import ptt_credit_card_crawler as ptt
from crawler.worker import app
from crawler.config import TABLE_PTT
from db_common import append_df

log = logging.getLogger("tasks_ptt")


@app.task(name="crawler.tasks_ptt.crawl_ptt_page", bind=True, max_retries=2)
def crawl_ptt_page(self, page_num: int):
    """抓單一索引頁:列表 → 逐篇內文 → 過濾年份 → append 進 MySQL。"""
    try:
        articles = ptt.crawl_index_page(page_num)
    except Exception as e:
        raise self.retry(exc=e, countdown=10)

    rows = []
    for art in articles:
        content, pub_time = ptt.fetch_post_content(art["url"])
        time.sleep(ptt.REQUEST_DELAY)
        if not pub_time:
            continue
        if int(pub_time[:4]) < ptt.START_YEAR:
            continue
        rows.append({
            "title": art["title"], "category": art["category"],
            "author": art["author"], "pub_time": pub_time,
            "date_display": art["date"], "push_count": art["push_count"],
            "url": art["url"], "content": content,
        })

    if rows:
        df = pd.DataFrame(rows, columns=ptt.CSV_COLUMNS)
        append_df(df, TABLE_PTT)
    log.info(f"PTT 第 {page_num} 頁:寫入 {len(rows)} 篇 → {TABLE_PTT}")
    return {"page": page_num, "rows": len(rows)}
