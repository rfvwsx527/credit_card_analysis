# -*- coding: utf-8 -*-
"""
api/config.py — 連線設定(全部走環境變數)
=====================================================================
與爬蟲端 (crawler/config.py、db_common.py) 使用「相同的環境變數命名」,
所以同一份 swarm environment 設定可直接共用:

    MySQL    : MYSQL_HOST / MYSQL_PORT / MYSQL_ACCOUNT / MYSQL_PASSWORD / MYSQL_DB
    RabbitMQ : RABBITMQ_HOST / RABBITMQ_PORT / RABBITMQ_ACCOUNT / RABBITMQ_PASSWORD / RABBITMQ_VHOST
    管理介面 : RABBITMQ_MGMT_PORT (預設 15672,用來查佇列深度)

預設值對齊專案既有設定(swarm 服務名 mysql_mysql / rabbitmq)。
"""
import os
import urllib.parse


# ── MySQL(相容 MYSQL_* 與 DB_* 兩種命名)──────────────────────────────
DB_HOST = os.getenv("MYSQL_HOST", os.getenv("DB_HOST", "mysql_mysql"))
DB_PORT = os.getenv("MYSQL_PORT", os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("MYSQL_DB", os.getenv("DB_NAME", "mydb"))
DB_USER = os.getenv("MYSQL_ACCOUNT", os.getenv("DB_USER", "root"))
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", os.getenv("DB_PASSWORD", "ppWgnb_mfGe2m_"))


def mysql_url() -> str:
    """組出 SQLAlchemy 連線字串(密碼做 URL encode)。"""
    pw = urllib.parse.quote_plus(DB_PASSWORD)
    return (f"mysql+pymysql://{DB_USER}:{pw}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            f"?charset=utf8mb4")


# ── RabbitMQ broker(派工用,與 crawler/config.py 對齊)─────────────────
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")
RABBITMQ_ACCOUNT = os.getenv("RABBITMQ_ACCOUNT", "worker")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "worker")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")
RABBITMQ_MGMT_PORT = os.getenv("RABBITMQ_MGMT_PORT", "15672")  # 管理 HTTP API


def broker_url() -> str:
    """Celery broker URL(amqp)。"""
    return (f"amqp://{RABBITMQ_ACCOUNT}:{RABBITMQ_PASSWORD}"
            f"@{RABBITMQ_HOST}:{RABBITMQ_PORT}/{RABBITMQ_VHOST}")


# ── 資料表名稱(與 crawler/config.py、clean_credit_cards.py 對齊)────────
TABLE_BANKS = os.getenv("TABLE_BANKS", "banks")
TABLE_PTT = os.getenv("TABLE_PTT", "ptt_credit_card")
TABLE_STATS = os.getenv("TABLE_STATS", "credit_card_stats")
CLEAN_SUFFIX = os.getenv("CLEAN_SUFFIX", "_clean")
TABLE_BANKS_CLEAN = TABLE_BANKS + CLEAN_SUFFIX
TABLE_PTT_CLEAN = TABLE_PTT + CLEAN_SUFFIX
TABLE_STATS_CLEAN = TABLE_STATS + CLEAN_SUFFIX
TABLE_AGG = os.getenv("DST_AGG", "dashboard_agg")

# ── Celery 任務名稱 / 佇列(必須與 crawler/worker.py 完全一致)──────────
TASK_PTT = "crawler.tasks_ptt.crawl_ptt_page"
TASK_BANKS = "crawler.tasks_banks.crawl_bank"
TASK_STATS = "crawler.tasks_fac.crawl_card_stats"
QUEUE_PTT = "ptt"
QUEUE_BANKS = "banks"
QUEUE_STATS = "card_stats"

# 各銀行代碼(對齊 README;派工 banks 時的預設清單)
BANK_CODES = os.getenv(
    "BANK_CODES",
    "esun,cathaybk,fubon,taishin,sinopac,yuanta,kgi,dbs,hsbc,scb,ctbc",
).split(",")

# CORS(給前端儀表板用;預設全開,正式環境可收斂)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
