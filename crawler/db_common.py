"""
MySQL 寫入共用模組 (db_common.py)
==================================
所有爬蟲共用的「寫入 MySQL」工具。設計原則:

1. 資料表不存在 → 自動依 DataFrame 欄位建立;已存在 → 不動結構。
2. 每次寫入前先 TRUNCATE (清空全部舊資料) 再 append,符合
   「每次爬蟲都刪除全部資料再寫入」的需求。
3. 連線失敗不會讓爬蟲掛掉 —— 只記 warning,CSV 仍正常保留。

連線資訊優先讀環境變數,沒設才用預設值 (方便日後改用 .env / 不寫死)。
    DB_HOST     預設 localhost
    DB_PORT     預設 3306
    DB_NAME     預設 mydb
    DB_USER     預設 root
    DB_PASSWORD 預設 (專案提供值)

需要套件:
    uv add sqlalchemy pymysql cryptography
    (cryptography 供 MySQL 8 的 caching_sha2_password 驗證用)
"""

import os
import logging
import urllib.parse

import pandas as pd
from sqlalchemy import create_engine, inspect, text

log = logging.getLogger("db_common")

# ── 連線設定 (環境變數優先,否則用預設) ───────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "mydb")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ppWgnb_mfGe2m_")


def _make_url() -> str:
    # 密碼可能含特殊字元 → URL encode
    pw = urllib.parse.quote_plus(DB_PASSWORD)
    return (f"mysql+pymysql://{DB_USER}:{pw}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            f"?charset=utf8mb4")


_engine = None  # 單例,避免重複建立連線池


def get_engine():
    """取得 (並快取) SQLAlchemy engine。"""
    global _engine
    if _engine is None:
        _engine = create_engine(_make_url(), pool_pre_ping=True, future=True)
    return _engine


# ── 低階工具 (供批次寫入的爬蟲使用,例如 PTT) ─────────────────────────────────
def ensure_table(df: pd.DataFrame, table: str, engine=None) -> None:
    """資料表不存在 → 依 df 欄位建立空表 (已存在則不動)。"""
    engine = engine or get_engine()
    insp = inspect(engine)
    if not insp.has_table(table):
        # head(0):只建結構不寫資料
        df.head(0).to_sql(table, engine, index=False, if_exists="fail")
        log.info(f"建立資料表 `{table}` (欄位:{list(df.columns)})")


def truncate_table(table: str, engine=None) -> None:
    """清空資料表全部資料 (MySQL 用 TRUNCATE,其他 dialect 用 DELETE)。"""
    engine = engine or get_engine()
    with engine.begin() as conn:
        if engine.dialect.name == "mysql":
            conn.execute(text(f"TRUNCATE TABLE `{table}`"))
        else:
            conn.execute(text(f'DELETE FROM "{table}"'))
    log.info(f"已清空資料表 `{table}`")


def append_df(df: pd.DataFrame, table: str, engine=None,
              chunksize: int = 1000) -> None:
    """把 df append 進資料表 (不清空、不建表)。"""
    engine = engine or get_engine()
    df.to_sql(table, engine, index=False, if_exists="append",
              chunksize=chunksize)


# ── 高階工具:一次性「清空 + 寫入」(供 banks / fac 等一次寫完的爬蟲) ──────────
def write_df_to_mysql(df: pd.DataFrame, table: str, *,
                      truncate: bool = True, engine=None) -> bool:
    """建表(若無) → 清空全部(若 truncate) → append。

    回傳 True 表示成功;連線/寫入失敗只記 warning 並回 False,
    不拋例外 (確保 CSV 流程不受影響)。
    """
    if df is None or df.empty:
        log.warning(f"`{table}`:DataFrame 為空,略過 MySQL 寫入。")
        return False
    try:
        eng = engine or get_engine()
        ensure_table(df, table, eng)
        if truncate:
            truncate_table(table, eng)
        append_df(df, table, eng)
        log.info(f"✅ 已寫入 MySQL `{table}`:{len(df)} 筆")
        return True
    except Exception as e:
        log.warning(f"⚠️ 寫入 MySQL `{table}` 失敗 (已保留 CSV):{e}")
        return False


def test_connection() -> bool:
    """測試能否連到 DB,回傳 True/False。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        log.warning(f"無法連線 MySQL:{e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    print(f"連線字串 (密碼已隱藏):"
          f"mysql+pymysql://{DB_USER}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("連線測試:", "✅ 成功" if test_connection() else "❌ 失敗")