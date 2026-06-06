# -*- coding: utf-8 -*-
"""
信用卡資料清理 → 寫回 MySQL（建表一次、每次清空重寫）
======================================================================
寫入策略（依需求）：
  1. 資料表不存在 → 以 CREATE TABLE IF NOT EXISTS 建立（含索引）；已存在則不重建。
  2. 每次執行 → 先 TRUNCATE 清空全部資料，再 INSERT 寫入。
     （保留表結構與索引，只刷新資料）

原始表（預設名稱，可用環境變數覆寫）：
  credit_card_stats / banks / ptt_credit_card
輸出表：
  stats_clean / banks_clean / ptt_clean / dashboard_agg

連線設定：環境變數優先，未設定才用程式內預設值。
建議用環境變數帶密碼，不要把密碼留在程式碼或版控裡：
  export MYSQL_HOST=localhost MYSQL_PORT=3306 MYSQL_DB=mydb
  export MYSQL_USER=root MYSQL_PASSWORD='ppWgnb_mfGe2m_'
  python clean_credit_card_to_mysql.py

選用：原始表還沒進 DB 時可先灌入
  SEED_FROM_CSV=1 CSV_DIR=/path/to/csv python clean_credit_card_to_mysql.py

相依套件： pip install pandas numpy sqlalchemy pymysql cryptography
"""
import os
import re
import numpy as np
import pandas as pd
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

# ----------------------------------------------------------------------
# 連線設定
# ----------------------------------------------------------------------
CFG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "db":   os.getenv("MYSQL_DB",   "mydb"),
    "user": os.getenv("MYSQL_USER", "root"),
    "pwd":  os.getenv("MYSQL_PASSWORD", "ppWgnb_mfGe2m_"),
}
RAW = {
    "stats": os.getenv("RAW_STATS", "credit_card_stats"),
    "banks": os.getenv("RAW_BANKS", "banks"),
    "ptt":   os.getenv("RAW_PTT",   "ptt_credit_card"),
}
# 清理後輸出表名稱：必須與原始表「不同名」，避免覆蓋原始資料。
# 可用環境變數覆寫；或用 CLEAN_SUFFIX 統一加後綴（預設 _clean）。
SUF = os.getenv("CLEAN_SUFFIX", "_clean")
DST = {
    "stats": os.getenv("DST_STATS", f"credit_card_stats{SUF}"),
    "banks": os.getenv("DST_BANKS", f"banks{SUF}"),
    "ptt":   os.getenv("DST_PTT",   f"ptt_credit_card{SUF}"),
    "agg":   os.getenv("DST_AGG",   "dashboard_agg"),
}

# 索引設定：{表名: [(索引名, 欄位), ...]}
INDEXES = {
    DST["stats"]: [("idx_stats_ym", "`年月`"), ("idx_stats_org", "`機構名稱`")],
    DST["ptt"]:   [("idx_ptt_ym", "`年月`"), ("idx_ptt_cat", "`分類`")],
    DST["agg"]:   [("idx_agg_metric", "`metric`")],
}

# 指定欄位的 MySQL 型別（其餘依 dtype 自動推斷）
VARCHAR_COLS = {
    "年月": "VARCHAR(7)", "機構名稱": "VARCHAR(100)", "機構類型名稱": "VARCHAR(20)",
    "銀行名稱": "VARCHAR(50)", "銀行代碼": "VARCHAR(20)", "卡片名稱": "VARCHAR(120)",
    "主卡別": "VARCHAR(30)", "卡片類型": "VARCHAR(60)", "分類": "VARCHAR(20)",
    "category": "VARCHAR(20)", "author": "VARCHAR(60)", "date_display": "VARCHAR(20)",
    "pub_time": "VARCHAR(30)", "pub_dt": "VARCHAR(20)", "title": "VARCHAR(500)",
    "url": "VARCHAR(255)", "metric": "VARCHAR(40)", "dim": "VARCHAR(120)",
    "更新時間": "VARCHAR(20)", "場景標籤": "VARCHAR(80)",
}
LONGTEXT_COLS = {"content"}  # 內文可能很長

# ── 卡片分類設定（與 app.py 一致）─────────────────────────────────────────
# 卡別多標籤：原始「卡片類型」以「/」拆解後可能含這些標籤
CARD_TYPE_TAGS = ["現金回饋", "紅利點數", "哩程", "聯名卡", "高階卡", "一般"]
# 適用場景：依「卡名＋回饋亮點」文字關鍵字比對（可自行增修）
SCENE_KW = {
    "海外消費": ["海外", "國外", "國際", "跨境", "外幣"],
    "旅遊住宿": ["旅遊", "旅行", "訂房", "飯店", "機票", "航空", "agoda", "booking", "trip"],
    "行動支付": ["行動支付", "apple pay", "google pay", "samsung pay", "街口", "line pay", "悠遊付", "綁定"],
    "加油交通": ["加油", "中油", "台塑", "停車", "高鐵", "捷運", "交通"],
    "餐飲外送": ["餐廳", "美食", "餐飲", "用餐", "foodpanda", "ubereats", "uber eats", "外送", "咖啡"],
    "超商量販": ["超商", "7-eleven", "全家", "全聯", "量販", "賣場", "好市多", "costco", "家樂福"],
    "網購電商": ["網購", "電商", "momo", "蝦皮", "pchome", "amazon", "網路購物", "線上購物"],
    "影音訂閱": ["串流", "訂閱", "netflix", "spotify", "youtube", "disney"],
}


def get_engine():
    url = (f"mysql+pymysql://{CFG['user']}:{quote_plus(CFG['pwd'])}"
           f"@{CFG['host']}:{CFG['port']}/{CFG['db']}?charset=utf8mb4")
    return create_engine(url, pool_pre_ping=True)


def normalize_cols(df):
    df.columns = [c.replace("\ufeff", "").strip() for c in df.columns]
    return df


def roc_to_ad(y):
    return int(y) + 1911


# ----------------------------------------------------------------------
# 由 DataFrame 推斷欄位型別並產生 CREATE TABLE
# ----------------------------------------------------------------------
def col_type(col, dtype):
    if col in LONGTEXT_COLS:
        return "LONGTEXT"
    if col in VARCHAR_COLS:
        return VARCHAR_COLS[col]
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


def ensure_table(eng, table, df):
    """建表(若無)；若表已存在但缺少新欄位，自動 ALTER TABLE 補上（含索引）。"""
    cols_sql = ",\n  ".join(f"`{c}` {col_type(c, df[c].dtype)}" for c in df.columns)
    ddl = (f"CREATE TABLE IF NOT EXISTS `{table}` (\n  {cols_sql}\n) "
           f"ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci")
    with eng.begin() as c:
        c.execute(text(ddl))
        # 自動補欄位：表已存在但缺少 df 的新欄位 → ADD COLUMN（不動既有資料）
        existing = {r[0] for r in c.execute(text(f"SHOW COLUMNS FROM `{table}`"))}
        added = []
        for col in df.columns:
            if col not in existing:
                c.execute(text(
                    f"ALTER TABLE `{table}` ADD COLUMN `{col}` {col_type(col, df[col].dtype)}"))
                added.append(col)
        if added:
            print(f"  [schema] `{table}` 新增欄位：{added}")
        for idx_name, idx_col in INDEXES.get(table, []):
            try:
                c.execute(text(f"CREATE INDEX `{idx_name}` ON `{table}` ({idx_col})"))
            except Exception:
                pass  # 索引已存在則略過（舊版 MySQL 不支援 IF NOT EXISTS）


def refresh_table(eng, table, df):
    """每次執行：建表(若無) → TRUNCATE 清空 → INSERT 寫入。"""
    ensure_table(eng, table, df)
    with eng.begin() as c:
        c.execute(text(f"TRUNCATE TABLE `{table}`"))
    df.to_sql(table, eng, if_exists="append", index=False, chunksize=1000)
    print(f"  -> {table}: 清空後寫入 {len(df)} 列")


# ----------------------------------------------------------------------
# 原始表前置檢查（preflight）
#   依序嘗試：① 預設表名存在 → 用之
#             ② 關鍵字自動比對現有表名 → 唯一命中就用
#             ③ 同目錄有對應 CSV → 自動灌入後使用
#             ④ 都沒有 → 給清楚的指示後中止
# ----------------------------------------------------------------------
CSV_FILE = {"stats": "credit_card_stats.csv",
            "banks": "banks.csv", "ptt": "ptt_credit_card.csv"}
KEYWORDS = {"stats": ["stats", "發卡", "金管", "stat"],
            "banks": ["bank", "card", "卡", "產品"],
            "ptt":   ["ptt", "批踢踢", "forum", "post"]}


def list_tables(eng):
    with eng.connect() as c:
        return [r[0] for r in c.execute(text("SHOW TABLES"))]


def seed_csv(eng, table, key, csv_dir, existing):
    """原始表『不存在時』才從 CSV 建立；絕不覆蓋既有原始資料。"""
    if table in existing:
        return False  # 已存在 → 不動它（保護原始資料）
    path = os.path.join(csv_dir, CSV_FILE[key])
    if not os.path.exists(path):
        return False
    df = normalize_cols(pd.read_csv(path))
    df.to_sql(table, eng, if_exists="fail", index=False, chunksize=1000)
    print(f"[seed] 原始表 `{table}` 不存在 → 由 {CSV_FILE[key]} 建立（{len(df)} 列）")
    return True


def preflight(eng):
    """
    確認三張原始表都可用（全程不覆蓋既有原始資料）。
    依序：① 表名存在就用 ② 關鍵字自動比對 ③ 缺表才從 CSV 建立 ④ 都沒有→友善報錯。
    """
    csv_dir = os.getenv("CSV_DIR", os.path.dirname(os.path.abspath(__file__)))
    existing = list_tables(eng)
    out_tables = set(DST.values())
    print(f"資料庫現有資料表：{existing}")

    for key, default in list(RAW.items()):
        if default in existing:
            continue  # ① 原始表已在 → 直接讀（唯讀，不更動）

        # ② 關鍵字自動比對（排除輸出表與已解析的原始表）
        used = set(RAW.values())
        cands = [t for t in existing
                 if t not in out_tables and t not in used
                 and any(k.lower() in t.lower() for k in KEYWORDS[key])]
        if len(cands) == 1:
            print(f"[auto] 找不到 `{default}`，自動改讀相符的 `{cands[0]}`")
            RAW[key] = cands[0]
            continue

        # ③ 原始表確實不存在 → 才從 CSV 建立（不會覆蓋任何既有表）
        if seed_csv(eng, default, key, csv_dir, existing):
            continue

        # ④ 都失敗 → 友善錯誤
        raise SystemExit(
            f"\n[錯誤] 找不到原始表 `{default}`。\n"
            f"  目前資料庫內的表：{existing}\n"
            f"  解法擇一：\n"
            f"    1) 若原始表名不同，設定環境變數指定，例如：\n"
            f"       export RAW_{key.upper()}=你的實際表名\n"
            f"    2) 若資料還沒進 DB，把 {CSV_FILE[key]} 放到本程式同目錄"
            f"（或設定 CSV_DIR），程式會自動建立該原始表。\n")


def assert_no_overwrite():
    """防呆：清理後表名不得與任何原始表同名，避免覆蓋原始資料。"""
    raw = set(RAW.values())
    clash = [(k, t) for k, t in DST.items() if t in raw]
    if clash:
        lines = "；".join(f"{k}->`{t}`" for k, t in clash)
        raise SystemExit(
            f"\n[錯誤] 清理後表名與原始表撞名（{lines}），會覆蓋原始資料，已中止。\n"
            f"  請用環境變數改清理後表名，例如 DST_{clash[0][0].upper()}=新表名，"
            f"或設定 CLEAN_SUFFIX 改後綴。\n")


# ----------------------------------------------------------------------
# 1. 統計表清理
# ----------------------------------------------------------------------
def clean_stats(eng):
    df = normalize_cols(pd.read_sql(f"SELECT * FROM `{RAW['stats']}`", eng))
    df["機構名稱"] = df["機構名稱"].astype(str).str.replace("#", "", regex=False).str.strip()
    df["年_西元"] = df["年"].apply(roc_to_ad)
    df["月"] = df["月-期底"].astype(int)
    df["年月"] = df["年_西元"].astype(str) + "-" + df["月"].astype(str).str.zfill(2)
    df["日期"] = pd.to_datetime(df["年月"] + "-01", errors="coerce")

    num_cols = [c for c in df.columns if any(k in c for k in
               ["卡數", "金額", "餘額", "比率", "率", "收入", "手續費", "家數"])]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["淨增卡數"] = df["本月發卡數-張"] - df["本月停卡數-張"]
    df["有效卡率"] = (df["有效卡數-張"] / df["流通卡數-張"]).round(4)
    df["卡均簽帳金額_元"] = np.where(
        df["有效卡數-張"] > 0,
        (df["本月簽帳金額-新臺幣百萬元"] * 1_000_000 / df["有效卡數-張"]).round(0),
        np.nan)

    df = df.drop_duplicates()
    refresh_table(eng, DST["stats"], df)
    print(f"[stats] {len(df)} 列 / {df['機構名稱'].nunique()} 機構 "
          f"({df['年月'].min()}~{df['年月'].max()})")
    return df


# ----------------------------------------------------------------------
# 2. 產品表清理
# ----------------------------------------------------------------------
def clean_banks(eng):
    df = normalize_cols(pd.read_sql(f"SELECT * FROM `{RAW['banks']}`", eng))
    df = df.drop_duplicates(subset=["銀行名稱", "卡片名稱"])

    def merge_points(r):
        pts = [str(r[c]).strip() for c in ["回饋亮點1", "回饋亮點2", "回饋亮點3"]
               if pd.notna(r[c]) and str(r[c]).strip() not in ("", "nan")]
        return " ｜ ".join(pts)
    df["回饋亮點"] = df.apply(merge_points, axis=1)
    df["亮點數量"] = df[["回饋亮點1", "回饋亮點2", "回饋亮點3"]].notna().sum(axis=1)
    df["主卡別"] = df["卡片類型"].astype(str).str.split("/").str[0]

    def max_pct(t):
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*%", str(t))
        return max(map(float, nums)) if nums else np.nan
    df["最高回饋率_pct"] = df["回饋亮點"].apply(max_pct)

    # ── 卡別多標籤：聯名卡/現金回饋 → 各自一個布林欄（TINYINT(1)）──────────
    tag_lists = df["卡片類型"].astype(str).apply(
        lambda t: [x.strip() for x in t.split("/") if x.strip()])
    df["卡別數"] = tag_lists.apply(len)
    for tag in CARD_TYPE_TAGS:
        df[f"類_{tag}"] = tag_lists.apply(lambda lst: tag in lst)

    # ── 適用場景：依卡名＋回饋亮點文字比對；一張卡可屬多場景 ───────────────
    blob = (df["卡片名稱"].astype(str) + " " + df["回饋亮點"].astype(str)).str.lower()
    scene_lists = blob.apply(
        lambda txt: [s for s, kws in SCENE_KW.items()
                     if any(k.lower() in txt for k in kws)])
    for s in SCENE_KW:
        df[f"場景_{s}"] = scene_lists.apply(lambda lst: s in lst)
    df["場景數"] = scene_lists.apply(len)
    df["場景標籤"] = scene_lists.apply(
        lambda lst: "、".join(lst) if lst else "綜合/未標示")

    refresh_table(eng, DST["banks"], df)
    print(f"[banks] {len(df)} 張卡 / {df['銀行名稱'].nunique()} 家")
    return df


# ----------------------------------------------------------------------
# 3. PTT 貼文清理
# ----------------------------------------------------------------------
BANK_KW = {
    "玉山": ["玉山", "Pi錢包", "Ucard", "Unicard"],
    "中信": ["中信", "中國信託", "ALL ME", "LINE Pay卡"],
    "國泰世華": ["國泰", "CUBE"],
    "台新": ["台新", "@GoGo", "FlyGo", "Richart"],
    "富邦": ["富邦", "J卡", "momo卡"],
    "永豐": ["永豐", "DAWHO", "幣倍"],
    "星展": ["星展", "DBS", "eco"],
    "凱基": ["凱基", "魔BUY"],
    "聯邦": ["聯邦", "賴點"],
    "新光": ["新光", "OU"],
    "滙豐": ["滙豐", "匯豐", "HSBC"],
    "花旗": ["花旗", "Citi"],
    "渣打": ["渣打"],
    "元大": ["元大", "鑽金卡"],
    "兆豐": ["兆豐"],
    "第一銀行": ["第一銀行", "iLEO"],
    "華南": ["華南"],
}


def push_to_int(v):
    s = str(v).strip()
    if s == "爆":
        return 100
    if re.fullmatch(r"X\d+", s):
        return -int(s[1:])
    try:
        return int(s)
    except ValueError:
        return 0


def clean_ptt(eng):
    df = normalize_cols(pd.read_sql(f"SELECT * FROM `{RAW['ptt']}`", eng))
    df = df.drop_duplicates(subset=["url"])

    df["推噓數"] = df["push_count"].apply(push_to_int)
    pub = pd.to_datetime(df["pub_time"], errors="coerce")
    df = df.assign(_pub=pub).dropna(subset=["_pub"])
    df["年月"] = df["_pub"].dt.to_period("M").astype(str)
    df["pub_dt"] = df["_pub"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df = df.drop(columns=["_pub"])

    main_cat = {"情報", "問題", "心得", "閒聊", "討論", "新聞", "海外", "公告"}
    df["分類"] = df["category"].where(df["category"].isin(main_cat), "其他")
    df["內文長度"] = df["content"].astype(str).str.len()
    df["含優惠連結"] = df["content"].astype(str).str.contains("http", na=False)

    text_all = df["title"].astype(str) + " " + df["content"].astype(str)
    for bank, kws in BANK_KW.items():
        pat = "|".join(map(re.escape, kws))
        df[f"提及_{bank}"] = text_all.str.contains(pat, case=False, na=False)

    refresh_table(eng, DST["ptt"], df)
    print(f"[ptt] {len(df)} 篇 ({df['年月'].min()}~{df['年月'].max()})")
    return df


# ----------------------------------------------------------------------
# 4. 彙整表（長表：metric / dim / value，方便 BI 工具直接接）
# ----------------------------------------------------------------------
def build_agg(eng, stats, banks, ptt):
    rows = []

    def add(metric, dim, value):
        rows.append({"metric": metric, "dim": str(dim),
                     "value": None if pd.isna(value) else float(value)})

    latest = stats["日期"].max()
    cur = stats[stats["日期"] == latest]
    lm = cur["年月"].iloc[0]

    add("kpi", "流通卡數_萬張", cur["流通卡數-張"].sum() / 1e4)
    add("kpi", "有效卡數_萬張", cur["有效卡數-張"].sum() / 1e4)
    add("kpi", "本月簽帳_億元", cur["本月簽帳金額-新臺幣百萬元"].sum() / 100)
    add("kpi", "循環餘額_億元", cur["循環信用餘額-新臺幣百萬元"].sum() / 100)
    add("kpi", "機構數", cur["機構名稱"].nunique())
    add("meta", "最新月", int(latest.year * 100 + latest.month))

    for ym, g in stats.groupby("年月"):
        add("trend_簽帳億元", ym, g["本月簽帳金額-新臺幣百萬元"].sum() / 100)
        add("trend_流通萬張", ym, g["流通卡數-張"].sum() / 1e4)
        add("trend_循環億元", ym, g["循環信用餘額-新臺幣百萬元"].sum() / 100)

    for n, v in (cur.groupby("機構名稱")["本月簽帳金額-新臺幣百萬元"].sum()/100).items():
        add("rank_簽帳億元", n, v)
    for n, v in (cur.groupby("機構名稱")["流通卡數-張"].sum()/1e4).items():
        add("rank_流通萬張", n, v)
    for n, v in cur.groupby("機構名稱")["逾期帳款比率-%"].mean().items():
        add("rank_逾期率", n, v)
    for n, v in cur.groupby("機構名稱")["卡均簽帳金額_元"].mean().items():
        add("rank_卡均簽帳元", n, v)

    for n, v in banks["主卡別"].value_counts().items():
        add("product_卡別", n, v)
    for n, v in banks["銀行名稱"].value_counts().items():
        add("product_各行張數", n, v)
    # 多標籤卡別張數（一張卡可計入多類）
    for tag in CARD_TYPE_TAGS:
        col = f"類_{tag}"
        if col in banks.columns:
            add("product_類型", tag, int(banks[col].sum()))
    # 適用場景張數
    for s in SCENE_KW:
        col = f"場景_{s}"
        if col in banks.columns:
            add("product_場景", s, int(banks[col].sum()))
    # 各銀行平均最高回饋率（僅計有數字者）
    rb = banks.dropna(subset=["最高回饋率_pct"]).groupby("銀行名稱")["最高回饋率_pct"].mean()
    for n, v in rb.items():
        add("product_平均回饋率", n, round(float(v), 2))

    for ym, g in ptt.groupby("年月"):
        add("ptt_月貼文", ym, len(g))
    for n, v in ptt["分類"].value_counts().items():
        add("ptt_分類", n, v)
    for b in BANK_KW:
        add("ptt_聲量", b, int(ptt[f"提及_{b}"].sum()))

    agg = pd.DataFrame(rows)
    refresh_table(eng, DST["agg"], agg)
    print(f"[agg] {len(agg)} 列 (最新月={lm})")
    return agg


def main():
    eng = get_engine()
    with eng.connect() as c:
        ver = c.execute(text("SELECT VERSION()")).scalar()
    print(f"=== 已連線 {CFG['host']}:{CFG['port']}/{CFG['db']} (MySQL {ver}) ===")

    preflight(eng)            # 解析三張原始表（唯讀；缺表才從 CSV 建立）
    assert_no_overwrite()     # 防呆：清理後表名不得覆蓋原始表
    print(f"原始表(讀取)：{RAW}")
    print(f"清理後表(寫入)：{DST}")
    stats = clean_stats(eng)
    banks = clean_banks(eng)
    ptt = clean_ptt(eng)
    build_agg(eng, stats, banks, ptt)
    print(f"=== 完成。原始表未更動；清理後寫入："
          f"{DST['stats']} / {DST['banks']} / {DST['ptt']} / {DST['agg']} ===")


if __name__ == "__main__":
    main()