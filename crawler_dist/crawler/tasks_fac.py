# -*- coding: utf-8 -*-
"""
crawler/tasks_fac.py — 金管會發卡統計(單一下載任務)
單一 task,沿用 fac_crawler 的下載邏輯;因無平行,直接建表→清空→寫入。
"""
import logging
import fac_crawler
from crawler.worker import app
from crawler.config import TABLE_STATS
from db_common import write_df_to_mysql

log = logging.getLogger("tasks_fac")


@app.task(name="crawler.tasks_fac.crawl_card_stats")
def crawl_card_stats():
    df = fac_crawler.download_credit_card_stats()  # 下載 + 存 CSV(內含一次 DB 寫入)
    # 對齊資料表名稱:寫入 config 指定的 TABLE_STATS(預設 credit_card_stats)
    rows = write_df_to_mysql(df, TABLE_STATS)
    log.info(f"金管會統計:寫入 {rows} 列 → {TABLE_STATS}")
    return {"table": TABLE_STATS, "rows": int(rows)}
