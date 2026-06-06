# -*- coding: utf-8 -*-
"""
crawler/producer_banks.py — 派工:各銀行
步驟:① 建表 + 清空 banks 表(一次)② 每家銀行送一個任務到 banks 佇列
"""
import logging
import pandas as pd

import scraper_banks
from card_common import COLUMNS
from crawler.tasks_banks import crawl_bank
from crawler.config import TABLE_BANKS
from db_common import ensure_table, truncate_table

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("producer_banks")


def main():
    # ① 建表(若無)+ 清空一次
    empty = pd.DataFrame(columns=COLUMNS)
    ensure_table(empty, TABLE_BANKS)
    truncate_table(TABLE_BANKS)
    log.info(f"已清空 `{TABLE_BANKS}`,準備派工")

    # ② 每家銀行一個任務(BANK_CONFIGS 的代碼 + ctbc)
    codes = list(scraper_banks.BANK_CONFIGS.keys()) + ["ctbc"]
    for code in codes:
        crawl_bank.apply_async(args=[code], queue="banks")
    log.info(f"已派工 {len(codes)} 家銀行任務:{', '.join(codes)}")


if __name__ == "__main__":
    main()
