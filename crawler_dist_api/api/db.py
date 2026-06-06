# -*- coding: utf-8 -*-
"""
api/db.py — MySQL 連線與查詢工具
=====================================================================
- 單例 engine(pool_pre_ping 自動偵測斷線)。
- 只讀查詢;回傳 list[dict],欄位保留原始(中文)名稱。
- 表名一律用白名單比對(防 SQL injection);所有過濾值用 bound parameters。
- has_table()/pick_table() 讓 API 在「清理表還沒建」時自動退回原始表。
"""
import logging
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from api.config import mysql_url

log = logging.getLogger("api.db")

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            mysql_url(), pool_pre_ping=True, pool_recycle=3600, future=True)
    return _engine


def ping() -> bool:
    """測試 DB 連線。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("MySQL 連線失敗: %s", e)
        return False


@lru_cache(maxsize=1)
def _inspector_tables() -> frozenset[str]:
    # 只在啟動後查一次;若需要即時反映新表,呼叫 refresh_tables()
    return frozenset(inspect(get_engine()).get_table_names())


def refresh_tables() -> None:
    _inspector_tables.cache_clear()


def has_table(name: str) -> bool:
    return name in _inspector_tables()


def pick_table(prefer: str, fallback: str) -> str:
    """優先用 prefer(例如清理表);不存在則退回 fallback(原始表)。"""
    if has_table(prefer):
        return prefer
    if has_table(fallback):
        return fallback
    # 都沒有 → 仍回 prefer,查詢時自然會回 0 列 / 錯誤訊息
    return prefer


def columns_of(table: str) -> list[str]:
    if not has_table(table):
        return []
    return [c["name"] for c in inspect(get_engine()).get_columns(table)]


def run_query(sql: str, params: dict[str, Any] | None = None) -> list[dict]:
    """執行只讀 SQL,回傳 list[dict]。sql 內所有變數值請用 :name bound 參數。"""
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params or {})
        cols = rows.keys()
        return [dict(zip(cols, r)) for r in rows.fetchall()]


def scalar(sql: str, params: dict[str, Any] | None = None):
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def truncate(table: str) -> bool:
    """清空整張表(僅限白名單呼叫端使用)。表不存在則略過回 False。"""
    if not has_table(table):
        return False
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE `{table}`"))
    return True
