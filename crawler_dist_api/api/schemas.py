# -*- coding: utf-8 -*-
"""api/schemas.py — 請求/回應模型。"""
from typing import Any
from pydantic import BaseModel, Field


class Page(BaseModel):
    """分頁查詢的共用回應外殼。"""
    table: str = Field(..., description="實際查詢的資料表")
    total: int = Field(..., description="符合條件的總列數")
    limit: int
    offset: int
    rows: list[dict[str, Any]]


class HealthOut(BaseModel):
    status: str
    db: bool
    version: str


# ── 派工請求 ────────────────────────────────────────────────────────
class CrawlBanksIn(BaseModel):
    codes: list[str] | None = Field(
        None, description="要爬的銀行代碼;不給則用預設 11 家")
    truncate: bool = Field(
        True, description="派工前是否先清空 banks 表(對齊 producer 行為)")


class CrawlPttIn(BaseModel):
    start_page: int = Field(..., ge=1, description="起始索引頁")
    end_page: int = Field(..., ge=1, description="結束索引頁(含)")
    truncate: bool = Field(
        True, description="派工前是否先清空 ptt 表")


class CrawlOut(BaseModel):
    enqueued: int = Field(..., description="送出的任務數")
    queue: str
    truncated: bool
    task_ids: list[str]
    detail: str
