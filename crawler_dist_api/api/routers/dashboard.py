# -*- coding: utf-8 -*-
"""
routers/dashboard.py — 儀表板彙整資料
=====================================================================
資料來源:dashboard_agg(metric / dim / value 長表,由 clean_credit_cards.py 產生)。
把長表轉成前端好用的結構:{ metric: [ {dim, value}, ... ] }。
"""
from fastapi import APIRouter, Query

from api import config, db

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard 儀表板"])


@router.get("", summary="取得儀表板彙整(可依 metric 前綴過濾)")
def dashboard(
    metric: str | None = Query(
        None, description="只取此 metric 前綴,如 kpi / trend_ / rank_ / ptt_ / product_"),
):
    table = config.TABLE_AGG
    if not db.has_table(table):
        return {"table": table, "metrics": {},
                "note": "dashboard_agg 尚未建立,請先執行 clean_credit_cards.py"}

    if metric:
        rows = db.run_query(
            f"SELECT `metric`, `dim`, `value` FROM `{table}` "
            f"WHERE `metric` LIKE :m ORDER BY `metric`, `dim`",
            {"m": f"{metric}%"})
    else:
        rows = db.run_query(
            f"SELECT `metric`, `dim`, `value` FROM `{table}` "
            f"ORDER BY `metric`, `dim`")

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["metric"], []).append(
            {"dim": r["dim"], "value": r["value"]})
    return {"table": table, "metrics": grouped}


@router.get("/metrics", summary="列出所有可用 metric")
def metrics():
    table = config.TABLE_AGG
    if not db.has_table(table):
        return {"table": table, "metrics": []}
    rows = db.run_query(
        f"SELECT DISTINCT `metric` FROM `{table}` ORDER BY `metric`")
    return {"table": table, "metrics": [r["metric"] for r in rows]}
