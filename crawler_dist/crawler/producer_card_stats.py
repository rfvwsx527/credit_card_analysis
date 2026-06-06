# -*- coding: utf-8 -*-
"""
crawler/producer_card_stats.py — 派工:金管會發卡統計
單一任務,直接送進 card_stats 佇列。
"""
import logging
from crawler.tasks_fac import crawl_card_stats

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("producer_card_stats")


def main():
    r = crawl_card_stats.apply_async(queue="card_stats")
    log.info(f"已派工金管會統計任務:task_id={r.id}")


if __name__ == "__main__":
    main()
