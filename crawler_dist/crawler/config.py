# -*- coding: utf-8 -*-
"""
crawler/config.py — 連線與資料表設定(全部走環境變數)
=====================================================================
RabbitMQ broker 預設對齊你的 rabbitmq.yml:amqp://worker:worker@rabbitmq:5672//
MySQL 預設資料庫 mydb;MYSQL_HOST 請依實際環境設定:
  - MySQL 也是 swarm 服務 → 設成該服務名(例如 mysql)
  - MySQL 在宿主機 Mac → 設成 host.docker.internal
資料表名稱預設「對齊清理程式 clean_credit_cards.py 會讀的原始表」,
讓爬蟲輸出可直接被清理程式使用。
"""
import os

# ── MySQL ──────────────────────────────────────────────────────────
MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")          # swarm 服務名,或 host.docker.internal
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_ACCOUNT = os.getenv("MYSQL_ACCOUNT", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "ppWgnb_mfGe2m_")
MYSQL_DB = os.getenv("MYSQL_DB", "mydb")

# ── RabbitMQ broker ────────────────────────────────────────────────
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = os.getenv("RABBITMQ_PORT", "5672")
RABBITMQ_ACCOUNT = os.getenv("RABBITMQ_ACCOUNT", "worker")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "worker")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

BROKER_URL = (f"amqp://{RABBITMQ_ACCOUNT}:{RABBITMQ_PASSWORD}"
              f"@{RABBITMQ_HOST}:{RABBITMQ_PORT}/{RABBITMQ_VHOST}")

# ── 資料表名稱(對齊清理程式讀的原始表)────────────────────────────
TABLE_STATS = os.getenv("TABLE_STATS", "credit_card_stats")
TABLE_BANKS = os.getenv("TABLE_BANKS", "banks")
TABLE_PTT = os.getenv("TABLE_PTT", "ptt_credit_card")
