# -*- coding: utf-8 -*-
"""
crawler/tasks_banks.py — 各銀行(每家銀行一個任務)
用 scraper_banks.run(bank_filter=code) 單跑一家,結果 append 進 DB。
關鍵:把 scraper_banks.DB_TABLE 設為 None,讓 run() 內部的 save_csv 不要
自己 truncate-write(否則平行 worker 會互相清空);改由本 task append。
清空由 producer 事前做一次。
"""
import logging
import scraper_banks
from crawler.worker import app
from crawler.config import TABLE_BANKS
from db_common import append_df

log = logging.getLogger("tasks_banks")

# 停用 run() 內部的 DB 寫入(只讓它回傳 DataFrame + 存 CSV)
scraper_banks.DB_TABLE = None


@app.task(name="crawler.tasks_banks.crawl_bank", bind=True, max_retries=1)
def crawl_bank(self, code: str):
    """爬單一家銀行(code 見 scraper_banks.BANK_CONFIGS,另含 'ctbc')。"""
    try:
        df = scraper_banks.run(
            bank_filter=code,
            output=f"/tmp/banks_{code}.csv",
            headless=True,
        )
    except Exception as e:
        raise self.retry(exc=e, countdown=15)

    n = append_df(df, TABLE_BANKS) if df is not None else 0
    log.info(f"銀行 {code}:寫入 {n} 張 → {TABLE_BANKS}")
    return {"bank": code, "rows": int(n)}
