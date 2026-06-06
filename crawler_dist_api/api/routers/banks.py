# -*- coding: utf-8 -*-
"""
routers/banks.py — 各銀行信用卡資料查詢
=====================================================================
資料來源:banks_clean(清理表,若不存在自動退回 banks 原始表)。
欄位保留原始中文名稱。
"""
from fastapi import APIRouter, Query

from api import config, db
from api.schemas import Page

router = APIRouter(prefix="/api/v1/banks", tags=["banks 信用卡"])


def _table() -> str:
    return db.pick_table(config.TABLE_BANKS_CLEAN, config.TABLE_BANKS)


@router.get("", response_model=Page, summary="查詢信用卡列表")
def list_banks(
    bank: str | None = Query(None, description="銀行名稱關鍵字(模糊比對)"),
    card_type: str | None = Query(None, description="卡片類型關鍵字(模糊比對)"),
    q: str | None = Query(None, description="卡片名稱關鍵字(模糊比對)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    table = _table()
    where, params = [], {}
    if bank:
        where.append("`銀行名稱` LIKE :bank")
        params["bank"] = f"%{bank}%"
    if card_type:
        where.append("`卡片類型` LIKE :ct")
        params["ct"] = f"%{card_type}%"
    if q:
        where.append("`卡片名稱` LIKE :q")
        params["q"] = f"%{q}%"
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    total = db.scalar(f"SELECT COUNT(*) FROM `{table}`{clause}", params) or 0
    params_p = {**params, "limit": limit, "offset": offset}
    rows = db.run_query(
        f"SELECT * FROM `{table}`{clause} "
        f"ORDER BY `銀行名稱`, `卡片名稱` LIMIT :limit OFFSET :offset", params_p)
    return Page(table=table, total=int(total), limit=limit, offset=offset, rows=rows)


@router.get("/by-bank", summary="各銀行卡片張數統計")
def count_by_bank():
    table = _table()
    rows = db.run_query(
        f"SELECT `銀行名稱` AS bank, COUNT(*) AS cards "
        f"FROM `{table}` GROUP BY `銀行名稱` ORDER BY cards DESC")
    return {"table": table, "data": rows}
