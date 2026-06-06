# -*- coding: utf-8 -*-
"""
crawler/producer_ptt.py — 派工:PTT 信用卡板
步驟:① 建表 + 清空 ptt 表(一次)② 估算要爬的頁數 ③ 每頁送一個任務到 ptt 佇列
"""
import logging
import pandas as pd

import ptt_credit_card_crawler as ptt
from crawler.tasks_ptt import crawl_ptt_page
from crawler.config import TABLE_PTT
from db_common import ensure_table, truncate_table

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("producer_ptt")


def main():
    # ① 建表(若無)+ 清空一次(之後 worker 只 append)
    empty = pd.DataFrame(columns=ptt.CSV_COLUMNS)
    ensure_table(empty, TABLE_PTT)
    truncate_table(TABLE_PTT)
    log.info(f"已清空 `{TABLE_PTT}`,準備派工")

    # ② 估算頁數範圍(沿用爬蟲的偵測邏輯)
    latest = ptt.get_latest_index()
    _, start = ptt.estimate_total_posts(latest)
    log.info(f"派工頁數:第 {start} ~ {latest} 頁(共 {latest - start + 1} 頁)")

    # ③ 每頁一個任務
    for page in range(start, latest + 1):
        crawl_ptt_page.apply_async(args=[page], queue="ptt")
    log.info(f"已派工 {latest - start + 1} 個 PTT 頁任務")


if __name__ == "__main__":
    main()
