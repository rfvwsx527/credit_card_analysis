# -*- coding: utf-8 -*-
"""
routers/stats.py — 金管會發卡統計查詢
=====================================================================
資料來源:credit_card_stats_clean(若不存在退回 credit_card_stats)。
"""
from fastapi import APIRouter, Query

from api import config, db
from api.schemas import Page

router = APIRouter(prefix="/api/v1/stats", tags=["stats 金管會統計"])


def _table() -> str:
    return db.pick_table(config.TABLE_STATS_CLEAN, config.TABLE_STATS)


@router.get("", response_model=Page, summary="查詢發卡統計")
def list_stats(
    org: str | None = Query(None, description="機構名稱關鍵字(模糊比對)"),
    year_month: str | None = Query(None, description="年月,如 2025-03"),
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    table = _table()
    cols = db.columns_of(table)
    where, params = [], {}
    if org:
        where.append("`機構名稱` LIKE :org")
        params["org"] = f"%{org}%"
    if year_month and "年月" in cols:
        where.append("`年月` = :ym")
        params["ym"] = year_month
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    order = "`日期`" if "日期" in cols else "`機構名稱`"
    total = db.scalar(f"SELECT COUNT(*) FROM `{table}`{clause}", params) or 0
    params_p = {**params, "limit": limit, "offset": offset}
    rows = db.run_query(
        f"SELECT * FROM `{table}`{clause} "
        f"ORDER BY {order} DESC LIMIT :limit OFFSET :offset", params_p)
    return Page(table=table, total=int(total), limit=limit, offset=offset, rows=rows)
