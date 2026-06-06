# -*- coding: utf-8 -*-
"""
routers/ptt.py — PTT 信用卡板文章查詢
=====================================================================
資料來源:ptt_credit_card_clean(若不存在退回 ptt_credit_card)。
content 內文很長,預設不回傳;include_content=true 才帶。
"""
from fastapi import APIRouter, Query

from api import config, db
from api.schemas import Page

router = APIRouter(prefix="/api/v1/ptt", tags=["ptt 討論"])


def _table() -> str:
    return db.pick_table(config.TABLE_PTT_CLEAN, config.TABLE_PTT)


@router.get("", response_model=Page, summary="查詢 PTT 文章")
def list_ptt(
    q: str | None = Query(None, description="標題關鍵字(模糊比對)"),
    category: str | None = Query(None, description="分類(如 心得/情報/問題)"),
    year_month: str | None = Query(None, description="年月,如 2025-03"),
    include_content: bool = Query(False, description="是否回傳內文(很長)"),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    table = _table()
    cols = db.columns_of(table)
    where, params = [], {}
    if q:
        where.append("`title` LIKE :q")
        params["q"] = f"%{q}%"
    if category and "分類" in cols:
        where.append("`分類` = :cat")
        params["cat"] = category
    elif category:
        where.append("`category` = :cat")
        params["cat"] = category
    if year_month and "年月" in cols:
        where.append("`年月` = :ym")
        params["ym"] = year_month
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    # 選欄位(預設排除 content)
    select_cols = "*"
    if not include_content and cols:
        keep = [c for c in cols if c != "content"]
        select_cols = ", ".join(f"`{c}`" for c in keep)

    order = "`pub_dt`" if "pub_dt" in cols else "`pub_time`"
    total = db.scalar(f"SELECT COUNT(*) FROM `{table}`{clause}", params) or 0
    params_p = {**params, "limit": limit, "offset": offset}
    rows = db.run_query(
        f"SELECT {select_cols} FROM `{table}`{clause} "
        f"ORDER BY {order} DESC LIMIT :limit OFFSET :offset", params_p)
    return Page(table=table, total=int(total), limit=limit, offset=offset, rows=rows)


@router.get("/by-month", summary="每月貼文量")
def by_month():
    table = _table()
    if "年月" not in db.columns_of(table):
        return {"table": table, "data": [], "note": "清理表尚未建立(無『年月』欄)"}
    rows = db.run_query(
        f"SELECT `年月` AS month, COUNT(*) AS posts "
        f"FROM `{table}` GROUP BY `年月` ORDER BY `年月`")
    return {"table": table, "data": rows}
