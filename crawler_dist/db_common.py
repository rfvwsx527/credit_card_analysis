"""
MySQL 寫入共用模組 (db_common.py)
==================================
所有爬蟲共用的「寫入 MySQL」工具。設計原則:
1. 資料表不存在 → 自動依 DataFrame 欄位建立;已存在 → 不動結構。
2. write_df_to_mysql:寫入前先 TRUNCATE (清空全部舊資料) 再 append,
   符合「每次爬蟲都刪除全部資料再寫入」的需求 (單機 / 單一任務用)。
3. append_df:只 append,不清空 (分散式多 worker 平行寫入用)。
4. 連線失敗不會讓爬蟲掛掉 —— 只記 warning,CSV 仍正常保留。

連線資訊優先讀環境變數 (相容兩種命名):
    MYSQL_HOST / DB_HOST          預設 mysql
    MYSQL_PORT / DB_PORT          預設 3306
    MYSQL_DB / DB_NAME            預設 mydb
    MYSQL_ACCOUNT / DB_USER       預設 root
    MYSQL_PASSWORD / DB_PASSWORD  預設 (專案提供值)

需要套件:
    uv add sqlalchemy pymysql cryptography
    (cryptography 供 MySQL 8 的 caching_sha2_password 驗證用)
"""
import os
import logging
import urllib.parse
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, inspect, text

# 自動補的「更新時間」欄位名稱(寫入 DB 時若資料沒有此欄,會自動加上)
UPDATE_COL = "更新時間"

log = logging.getLogger("db_common")

# ── 連線設定 (優先吃 MYSQL_*,沒有才吃 DB_*,都沒有才用預設) ──────────────────
DB_HOST = os.getenv("MYSQL_HOST", os.getenv("DB_HOST", "mysql"))
DB_PORT = os.getenv("MYSQL_PORT", os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("MYSQL_DB", os.getenv("DB_NAME", "mydb"))
DB_USER = os.getenv("MYSQL_ACCOUNT", os.getenv("DB_USER", "root"))
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", os.getenv("DB_PASSWORD", "ppWgnb_mfGe2m_"))


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
        _engine = create_engine(
            _make_url(), pool_pre_ping=True, pool_recycle=3600, future=True)
    return _engine


# ── 由 DataFrame 欄位型別推斷 MySQL 欄位型別 ─────────────────────────────────
def _col_type(dtype) -> str:
    k = dtype.kind  # b=bool, i=int, f=float, M=datetime, O=object
    if k == "b":
        return "TINYINT(1)"
    if k == "i":
        return "BIGINT"
    if k == "f":
        return "DOUBLE"
    if k == "M":
        return "DATETIME"
    return "TEXT"


def _with_update_time(df: pd.DataFrame) -> pd.DataFrame:
    """確保 DataFrame 有「更新時間」欄位:沒有就補上寫入當下的時間。
    已有此欄(例如 banks 的 make_record 已帶日期)則不覆蓋。"""
    if df is None or df.empty:
        return df
    if UPDATE_COL not in df.columns:
        df = df.copy()
        df[UPDATE_COL] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def ensure_table(df: pd.DataFrame, table: str, engine=None) -> None:
    """資料表不存在才建立 (欄位型別依 df 推斷);已存在則不動結構。
    一律確保含「更新時間」欄位 (即使 df 沒有,也加進 schema)。"""
    engine = engine or get_engine()
    if df is None or len(df.columns) == 0:
        return
    col_defs = [f"`{c}` {_col_type(df[c].dtype)}" for c in df.columns]
    if UPDATE_COL not in df.columns:        # df 沒帶就補進 DDL(建表時就有此欄)
        col_defs.append(f"`{UPDATE_COL}` VARCHAR(20)")
    cols = ",\n  ".join(col_defs)
    ddl = (f"CREATE TABLE IF NOT EXISTS `{table}` (\n  {cols}\n) "
           f"ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci")
    with engine.begin() as conn:
        conn.execute(text(ddl))


def truncate_table(table: str, engine=None) -> None:
    """清空整張表 (保留結構與索引)。表不存在則略過。"""
    engine = engine or get_engine()
    insp = inspect(engine)
    if not insp.has_table(table):
        return
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE `{table}`"))


def append_df(df: pd.DataFrame, table: str, engine=None,
              chunksize: int = 1000) -> int:
    """只 append 寫入 (不清空)。分散式多 worker 安全。回傳寫入列數。"""
    if df is None or df.empty:
        return 0
    df = _with_update_time(df)        # 自動補「更新時間」欄位
    engine = engine or get_engine()
    df.to_sql(table, engine, if_exists="append", index=False, chunksize=chunksize)
    return len(df)


def write_df_to_mysql(df: pd.DataFrame, table: str, *,
                      engine=None, chunksize: int = 1000) -> int:
    """建表 (若無) → 清空全部 → 寫入。單機 / 單一任務用。
    DB 失敗不讓爬蟲中斷,只記 warning (CSV 仍保留)。回傳寫入列數。"""
    if df is None:
        return 0
    df = _with_update_time(df)        # 自動補「更新時間」欄位(建表前先加,DDL 才含此欄)
    engine = engine or get_engine()
    try:
        ensure_table(df, table, engine=engine)
        truncate_table(table, engine=engine)
        return append_df(df, table, engine=engine, chunksize=chunksize)
    except Exception as e:
        log.warning(f"⚠️ 寫入 MySQL `{table}` 失敗 (已保留 CSV):{e}")
        return 0


def test_connection() -> bool:
    """測試資料庫連線,成功回傳 True。"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info(f"✅ MySQL 連線成功:{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
        return True
    except Exception as e:
        log.warning(f"⚠️ MySQL 連線失敗:{e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    print(f"連線目標:{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    test_connection()