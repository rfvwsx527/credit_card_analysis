# -*- coding: utf-8 -*-
"""
台灣信用卡市場分析儀表板 (Streamlit) — 升級版
======================================================================
資料來源：MySQL `mydb` 內清理後的資料表
  credit_card_stats_clean / banks_clean / ptt_credit_card_clean

相較於原版，主要強化：
  1. 縱向分析：市占演變、逾期率趨勢、市場集中度(HHI)、YoY
  2. 機構類型(本國銀行 / 信用卡公司)對比與篩選
  3. KPI 加上環比(MoM) delta
  4. 產品回饋率分布、社群聲量隨時間變化、聲量 vs 簽帳對照
  5. 區間篩選與排版細修

安全性：密碼由 streamlit.yml 的 environment（MYSQL_PASSWORD）注入，
  程式不寫死密碼。正式環境建議改用 docker secret，並更換已外洩的密碼。
"""
import os
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

# set_page_config 必須是「第一個」Streamlit 指令，務必放在最前面
st.set_page_config(page_title="信用卡市場儀表板", page_icon="💳",
                   layout="wide", initial_sidebar_state="expanded")


# ----------------------------------------------------------------------
# 設定讀取：環境變數優先 → 預設值（密碼由 streamlit.yml 的 environment 注入）
# ⚠️ 不要把真實密碼寫死在程式碼；正式環境建議改用 docker secret，並更換已外洩的密碼
# ----------------------------------------------------------------------
def _cfg(key, default):
    return os.getenv(key, default)


CFG = {
    "host": _cfg("MYSQL_HOST", "host.docker.internal"),
    "port": int(_cfg("MYSQL_PORT", "3306")),
    "db":   _cfg("MYSQL_DB",   "mydb"),
    "user": _cfg("MYSQL_USER", "root"),
    "pwd":  _cfg("MYSQL_PASSWORD", ""),
}
TABLE_CANDIDATES = {
    "stats": [_cfg("TBL_STATS", "credit_card_stats_clean"), "stats_clean"],
    "banks": [_cfg("TBL_BANKS", "banks_clean")],
    "ptt":   [_cfg("TBL_PTT", "ptt_credit_card_clean"), "ptt_clean"],
}

PALETTE = ["#e8b84b", "#4fd1c5", "#7aa2f7", "#e8736b",
           "#b48ead", "#9ece6a", "#f2cd6e", "#56c8d8"]

# 一點輕量 CSS：縮頂部空白、放大分頁列、讓 KPI 卡與區塊更整齊
st.markdown("""
<style>
/* 1) 縮掉主畫面與側邊欄頂部的大片空白 */
[data-testid="stMainBlockContainer"], .main .block-container {
    padding-top: 1.6rem !important;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { right: 0.5rem; }
/* 側邊欄頂部：壓掉收合鈕區塊的高度，並讓內容與右側標題同高 */
[data-testid="stSidebarHeader"] { height: 0 !important; min-height: 0 !important; padding: 0 !important; }
[data-testid="stSidebarUserContent"],
section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
section[data-testid="stSidebar"] .block-container {
    padding-top: 1.4rem !important;
}

/* 2) 分頁切換列：放大字體、加大間距、選中更顯眼 */
div[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 10px; border-bottom: 2px solid rgba(128,128,128,.2);
}
div[data-testid="stTabs"] button[data-baseweb="tab"] {
    padding: 12px 20px;
}
div[data-testid="stTabs"] button[data-baseweb="tab"] p {
    font-size: 1.25rem !important; font-weight: 600;
}
div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] {
    background: rgba(232,184,75,.14);
    border-radius: 10px 10px 0 0;
}
div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] p {
    color: #d99a18 !important;
}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    height: 4px; background-color: #e8b84b;
}

/* 3) KPI 卡：大小一致、數字完整不截斷 */
[data-testid="stMetric"] {
    background: rgba(128,128,128,.06);
    border: 1px solid rgba(128,128,128,.15);
    border-radius: 12px; padding: 14px 16px;
    min-height: 116px;                 /* 五張卡同高（含無 delta 的那張）*/
    display: flex; flex-direction: column; justify-content: center;
}
[data-testid="stMetricValue"] {
    font-size: 1.9rem;                 /* 縮一點以完整顯示 */
    white-space: nowrap; overflow: visible; text-overflow: clip;
}
[data-testid="stMetricLabel"] { opacity: .75; }
div[data-testid="stHorizontalBlock"] { gap: .6rem; }
h3 { margin-top: .2rem; }

/* 4) 標題字級各縮小一號 */
h1 { font-size: 2.1rem !important; }                                  /* 主標題 */
[data-testid="stMainBlockContainer"] h3, .main h3 { font-size: 1.3rem !important; }  /* 圖表標題 */
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------
# 資料存取（快取）
# ----------------------------------------------------------------------
@st.cache_resource
def get_engine():
    url = (f"mysql+pymysql://{CFG['user']}:{quote_plus(str(CFG['pwd']))}"
           f"@{CFG['host']}:{CFG['port']}/{CFG['db']}?charset=utf8mb4")
    return create_engine(url, pool_pre_ping=True)


def resolve_table(eng, key):
    with eng.connect() as c:
        existing = {r[0] for r in c.execute(text("SHOW TABLES"))}
    for name in TABLE_CANDIDATES[key]:
        if name in existing:
            return name
    raise RuntimeError(f"找不到 {key} 對應的資料表，候選：{TABLE_CANDIDATES[key]}；"
                       f"DB 內有：{sorted(existing)}")


@st.cache_data(ttl=600)
def load_stats():
    eng = get_engine()
    return pd.read_sql(f"SELECT * FROM `{resolve_table(eng, 'stats')}`", eng)


@st.cache_data(ttl=600)
def load_banks():
    eng = get_engine()
    return pd.read_sql(f"SELECT * FROM `{resolve_table(eng, 'banks')}`", eng)


@st.cache_data(ttl=600)
def load_ptt():
    eng = get_engine()
    t = resolve_table(eng, "ptt")
    cols = pd.read_sql(
        text("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
             "WHERE TABLE_SCHEMA=:d AND TABLE_NAME=:t"),
        eng, params={"d": CFG["db"], "t": t})["COLUMN_NAME"].tolist()
    use = [c for c in cols if c != "content"]      # 不撈長內文以加速
    sel = ", ".join(f"`{c}`" for c in use)
    return pd.read_sql(f"SELECT {sel} FROM `{t}`", eng)


def fig_style(fig, h=360):
    fig.update_layout(
        height=h, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Noto Sans TC, sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,.2)")
    # 移除 plotly express 用陣列繪圖時自動產生的預設 "x"/"y" 軸標題；保留有意義者
    for ax in list(fig.select_xaxes()) + list(fig.select_yaxes()):
        if ax.title.text in (None, "", "x", "y"):
            ax.title.text = ""
    return fig


def show_selectable(fig, key, h=360):
    """可點擊聚焦的圖表：clickmode=event+select 讓『單擊』就會選取，
    selection_mode 限定 points（單擊取點），並把選取狀態存進 session_state[key]。"""
    fig = fig_style(fig, h)
    fig.update_layout(clickmode="event+select", dragmode=False)
    return st.plotly_chart(fig, use_container_width=True, key=key,
                           on_select="rerun", selection_mode="points")


# ----------------------------------------------------------------------
# 交叉篩選共用工具
#   下拉選單（selectbox）為「主要且可靠」的聚焦控制；圖表點擊為加分功能，
#   若 plotly on_select 在當前環境有作動，會把點到的項目同步寫回下拉。
#   get_pick：從帶 key 的圖表選取狀態取出被點到的類別
# ----------------------------------------------------------------------
def get_pick(state_key, order):
    s = st.session_state.get(state_key)
    if not s:
        return None
    sel = s.get("selection") if isinstance(s, dict) else getattr(s, "selection", None)
    pts = (sel or {}).get("points") or []
    if not pts:
        return None
    p = pts[0]
    i = p.get("point_index", p.get("point_number", -1))
    if isinstance(i, int) and 0 <= i < len(order):
        return order[i]
    return p.get("label") or p.get("y") or p.get("x")


def focus_nonce(tab_id):
    return st.session_state.setdefault(f"{tab_id}_nonce", 0)


ALL = "（全部）"
FOCUS_TABS = ["t1", "t2", "t3", "t4", "t5"]


def focus_control(tab_id, label, options, specs):
    """於『側邊欄』渲染聚焦下拉，回傳目前聚焦類別（None 表示全部）。
    - label：側邊欄下拉的標題（含分頁名）。
    - options：可聚焦的所有類別。
    - specs：[(圖表 state_key, 該圖類別順序 order), ...]，用來偵測圖表點擊並同步寫回下拉。
    """
    options = list(dict.fromkeys(options))          # 去重保序
    sel_key = f"{tab_id}_focus_sel"

    # 圖表點擊 → 偵測「本次新點擊」→ 寫回下拉（須在 selectbox 建立前設定）
    for key, order in specs:
        cur = get_pick(key, order)
        seen = f"_seen_{key}"
        if cur != st.session_state.get(seen):
            st.session_state[seen] = cur
            if cur in options:
                st.session_state[sel_key] = cur

    opts = [ALL] + options
    if st.session_state.get(sel_key) not in opts:
        st.session_state[sel_key] = ALL

    choice = st.sidebar.selectbox(label, opts, key=sel_key)   # 渲染到左側側邊欄
    return None if choice == ALL else choice


def clear_all_focus():
    """側邊欄「清除所有聚焦」按鈕的 callback：重置所有分頁的聚焦與圖表選取。"""
    for t in FOCUS_TABS:
        st.session_state[f"{t}_focus_sel"] = ALL
        st.session_state[f"{t}_nonce"] = st.session_state.get(f"{t}_nonce", 0) + 1


# ----------------------------------------------------------------------
# 卡片分類：多標籤卡別 + 適用場景（由卡片類型與回饋亮點衍生）
# ----------------------------------------------------------------------
CARD_TYPE_TAGS = ["現金回饋", "紅利點數", "哩程", "聯名卡", "高階卡", "一般"]

# 適用場景關鍵字（依回饋亮點文字比對；可自行增修）
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


@st.cache_data(ttl=600)
def enrich_banks(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # 多標籤卡別：把「聯名卡/現金回饋」拆成 list
    raw = df["卡片類型"].astype(str) if "卡片類型" in df.columns else df.get("主卡別", "")
    df["卡別標籤"] = raw.apply(
        lambda t: [x.strip() for x in str(t).split("/") if x.strip()])
    df["卡別數"] = df["卡別標籤"].apply(len)
    # 每個卡別給一個布林欄，方便篩選與統計
    for tag in CARD_TYPE_TAGS:
        df[f"類_{tag}"] = df["卡別標籤"].apply(lambda lst: tag in lst)

    # 適用場景：比對回饋亮點（含卡名）文字
    blob = (df.get("卡片名稱", "").astype(str) + " " +
            df.get("回饋亮點", "").astype(str)).str.lower()
    scene_lists = []
    for txt in blob:
        hits = [s for s, kws in SCENE_KW.items()
                if any(k.lower() in txt for k in kws)]
        scene_lists.append(hits)
    df["適用場景"] = scene_lists
    for s in SCENE_KW:
        df[f"場景_{s}"] = df["適用場景"].apply(lambda lst: s in lst)
    df["場景標籤"] = df["適用場景"].apply(
        lambda lst: "、".join(lst) if lst else "綜合/未標示")
    return df


# ----------------------------------------------------------------------
# 載入資料 + 錯誤處理
# ----------------------------------------------------------------------
st.title("💳 台灣信用卡市場分析儀表板")

try:
    stats = load_stats()
    banks = load_banks()
    ptt = load_ptt()
except Exception as e:
    st.error(f"無法連線或讀取資料庫：{e}")
    st.info(f"目前連線設定：{CFG['user']}@{CFG['host']}:{CFG['port']}/{CFG['db']}。"
            "請確認 MySQL 可連線、清理後的資料表已建立，且已設定 MYSQL_PASSWORD。")
    st.stop()

banks = enrich_banks(banks)   # 衍生：多標籤卡別 + 適用場景

# 共用欄位
SPEND = "本月簽帳金額-新臺幣百萬元"
CARDS = "流通卡數-張"
ACTIVE = "有效卡數-張"
REVOLVE = "循環信用餘額-新臺幣百萬元"
OVERDUE = "逾期帳款比率-%"
PERCARD = "卡均簽帳金額_元"
ORGTYPE = "機構類型名稱"

months = sorted(stats["年月"].unique())
latest_data_month = months[-1]                              # 各資料中最晚有資料的月份
last_month = months[-2] if len(months) >= 2 else months[-1]  # 「上個月」(倒數第二)


# ----------------------------------------------------------------------
# 側邊欄篩選
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("篩選條件")

    org_types = ["全部"] + sorted(stats[ORGTYPE].dropna().unique().tolist()) \
        if ORGTYPE in stats.columns else ["全部"]
    sel_type = st.selectbox("機構類型", org_types, index=0)

    sel_month = st.selectbox("統計月份（KPI / 排名）", months,
                             index=months.index(last_month))

    # 趨勢圖觀察區間：結束預設為最晚有資料的月份（起始預設往前約 3 年）
    default_start = months[max(0, len(months) - 37)]
    rng = st.select_slider("趨勢觀察區間", options=months,
                           value=(default_start, latest_data_month))
    top_n = st.slider("排名顯示前 N 名", 5, 25, 10)
    st.caption(f"資料區間：{months[0]} ~ {months[-1]}（共 {len(months)} 個月）")
    st.caption(f"連線：{CFG['host']}:{CFG['port']}/{CFG['db']}")

# 套用機構類型篩選
S = stats if sel_type == "全部" or ORGTYPE not in stats.columns \
    else stats[stats[ORGTYPE] == sel_type]
cur = S[S["年月"] == sel_month]
in_range = [m for m in months if rng[0] <= m <= rng[1]]
S_rng = S[S["年月"].isin(in_range)]

# 上月（供 KPI 環比）
prev_month = months[months.index(sel_month) - 1] if months.index(sel_month) > 0 else None
prev = S[S["年月"] == prev_month] if prev_month else None


# ----------------------------------------------------------------------
# KPI 區（含環比 delta）
# ----------------------------------------------------------------------
k1, k2, k3, k4, k5 = st.columns(5)
for col, (title, snow, sprev, scale, unit) in zip(
        [k1, k2, k3, k4, k5],
        [("流通卡數", cur[CARDS], prev[CARDS] if prev is not None else None, 1e4, "萬張"),
         ("有效卡數", cur[ACTIVE], prev[ACTIVE] if prev is not None else None, 1e4, "萬張"),
         ("本月簽帳", cur[SPEND], prev[SPEND] if prev is not None else None, 100, "億元"),
         ("循環餘額", cur[REVOLVE], prev[REVOLVE] if prev is not None else None, 100, "億元")]):
    now = snow.sum() / scale
    delta = None
    if sprev is not None and len(sprev) and sprev.sum():
        p = sprev.sum() / scale
        delta = f"{(now - p) / p * 100:+.1f}%"
    col.metric(f"{title}（{unit}）", f"{now:,.0f}", delta)
k5.metric("統計機構數（家）", f"{cur['機構名稱'].nunique():,}")

st.caption(f"以上為 {sel_month}・{sel_type} 的加總；delta 為較上月（{prev_month or '—'}）變化")

# 側邊欄「聚焦」區標題（各分頁的聚焦下拉會接在這之後，由各分頁的 focus_control 加入）
with st.sidebar:
    st.divider()
    st.subheader("🔎 聚焦（依分頁）")
    st.caption("選擇後，對應分頁的圖表會只顯示該項目；也可直接點分頁中的長條／圓餅／泡泡圖聚焦。")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📈 市場總覽", "🏦 機構競爭", "💼 產品分析", "💬 社群聲量", "💳 優惠比較"])

# ----------------------------------------------------------------------
# Tab1 市場總覽
# ----------------------------------------------------------------------
with tab1:
    nonce = focus_nonce("t1")
    ts_all = (cur.groupby("機構名稱")[SPEND].sum() / 100).sort_values().tail(top_n)
    tc_all = (cur.groupby("機構名稱")[CARDS].sum() / 1e4).sort_values().tail(top_n)
    k_spend, k_cards = f"t1_spend_{nonce}", f"t1_cards_{nonce}"
    focus = focus_control("t1", "市場總覽 · 聚焦機構", sorted(cur["機構名稱"].unique()),
                          [(k_spend, list(ts_all.index)),
                           (k_cards, list(tc_all.index))])

    # 趨勢資料：聚焦時改用該機構，否則為（已套機構類型篩選的）全市場
    src = S_rng[S_rng["機構名稱"] == focus] if focus else S_rng
    trend = (src.groupby("年月")
             .agg(簽帳億元=(SPEND, lambda s: s.sum() / 100),
                  流通萬張=(CARDS, lambda s: s.sum() / 1e4),
                  循環億元=(REVOLVE, lambda s: s.sum() / 100))
             .reset_index())
    tag = f"{focus}：" if focus else ""

    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"{tag}每月簽帳金額趨勢（億元）")
        fig = px.area(trend, x="年月", y="簽帳億元",
                      color_discrete_sequence=["#e8b84b"])
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c2:
        st.subheader(f"{tag}流通卡數 vs 循環信用餘額")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend["年月"], y=trend["流通萬張"],
                                 name="流通卡數(萬張)", line=dict(color="#4fd1c5")))
        fig.add_trace(go.Scatter(x=trend["年月"], y=trend["循環億元"],
                                 name="循環餘額(億元)", yaxis="y2",
                                 line=dict(color="#e8736b")))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right"))
        st.plotly_chart(fig_style(fig), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("本國銀行 vs 信用卡公司：簽帳金額（億元）")
        if ORGTYPE in stats.columns:
            base = stats[stats["年月"].isin(in_range)]
            bytype = (base.groupby(["年月", ORGTYPE])[SPEND].sum() / 100).reset_index()
            fig = px.area(bytype, x="年月", y=SPEND, color=ORGTYPE,
                          color_discrete_sequence=PALETTE)
            fig.update_yaxes(title="簽帳億元")
            st.plotly_chart(fig_style(fig), use_container_width=True)
        else:
            st.info("資料無機構類型欄位")
    with c4:
        st.subheader("市場集中度 HHI（簽帳市占）")
        # HHI = Σ(各機構市占%)^2，越高越集中（>2500 視為高度集中）；恆為全市場
        hhi = []
        for ym, g in S_rng.groupby("年月"):
            share = g.groupby("機構名稱")[SPEND].sum()
            tot = share.sum()
            if tot > 0:
                hhi.append({"年月": ym, "HHI": float(((share / tot * 100) ** 2).sum())})
        hdf = pd.DataFrame(hhi)
        fig = px.line(hdf, x="年月", y="HHI", markers=True,
                      color_discrete_sequence=["#b48ead"])
        fig.add_hline(y=2500, line_dash="dash", line_color="#e8736b",
                      annotation_text="高度集中(2500)")
        st.plotly_chart(fig_style(fig), use_container_width=True)

    c5, c6 = st.columns(2)
    with c5:
        st.subheader(f"簽帳金額 Top {top_n}（{sel_month}・億元）")
        order_s = list(ts_all.index)
        cols_s = ["#e8736b" if b == focus else "#e8b84b" for b in order_s]
        fig = px.bar(x=ts_all.values, y=order_s, orientation="h",
                     text=[f"{v:,.0f}" for v in ts_all.values])
        fig.update_traces(marker_color=cols_s)
        show_selectable(fig, k_spend)
    with c6:
        st.subheader(f"流通卡數 Top {top_n}（{sel_month}・萬張）")
        order_c = list(tc_all.index)
        cols_c = ["#e8736b" if b == focus else "#4fd1c5" for b in order_c]
        fig = px.bar(x=tc_all.values, y=order_c, orientation="h",
                     text=[f"{v:,.0f}" for v in tc_all.values])
        fig.update_traces(marker_color=cols_c)
        show_selectable(fig, k_cards)

# ----------------------------------------------------------------------
# Tab2 機構競爭（重點：市占演變 + 風險趨勢）
# ----------------------------------------------------------------------
with tab2:
    nonce = focus_nonce("t2")
    pc_all = cur.groupby("機構名稱")[PERCARD].mean().sort_values().tail(top_n)
    rk_all = cur.groupby("機構名稱")[OVERDUE].mean().sort_values().tail(top_n)
    sc = cur.groupby("機構名稱").agg(
        卡數萬張=(CARDS, lambda s: s.sum() / 1e4),
        簽帳億元=(SPEND, lambda s: s.sum() / 100)).reset_index()
    k_perc, k_over, k_sc = f"t2_perc_{nonce}", f"t2_over_{nonce}", f"t2_sc_{nonce}"
    focus = focus_control("t2", "機構競爭 · 聚焦機構", sorted(S["機構名稱"].unique()),
                          [(k_perc, list(pc_all.index)),
                           (k_over, list(rk_all.index)),
                           (k_sc, list(sc["機構名稱"]))])

    leaders = (cur.groupby("機構名稱")[SPEND].sum()
               .sort_values(ascending=False).head(top_n).index.tolist())
    picks = st.multiselect("選擇要比較的機構", sorted(S["機構名稱"].unique()),
                           default=leaders[:6], disabled=bool(focus))
    active = [focus] if focus else picks   # 聚焦時兩條趨勢線只看該機構

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("簽帳市占率演變（%）")
        share_rows = []
        for ym, g in S_rng.groupby("年月"):
            tot = g[SPEND].sum()
            if tot <= 0:
                continue
            sub = g.groupby("機構名稱")[SPEND].sum()
            for name in active:
                share_rows.append({"年月": ym, "機構名稱": name,
                                   "市占%": float(sub.get(name, 0) / tot * 100)})
        sh = pd.DataFrame(share_rows)
        if not sh.empty:
            fig = px.line(sh, x="年月", y="市占%", color="機構名稱",
                          color_discrete_sequence=PALETTE)
            st.plotly_chart(fig_style(fig, 400), use_container_width=True)
        else:
            st.info("請於上方選擇至少一家機構，或點下方排名圖聚焦")
    with c2:
        st.subheader("逾期帳款比率趨勢（%）")
        if OVERDUE in S.columns and active:
            ov = (S_rng[S_rng["機構名稱"].isin(active)]
                  .groupby(["年月", "機構名稱"])[OVERDUE].mean().reset_index())
            fig = px.line(ov, x="年月", y=OVERDUE, color="機構名稱",
                          color_discrete_sequence=PALETTE)
            st.plotly_chart(fig_style(fig, 400), use_container_width=True)
        else:
            st.info("資料無逾期帳款比率欄位")

    c3, c4 = st.columns(2)
    with c3:
        st.subheader(f"卡均簽帳金額 Top {top_n}（{sel_month}・元）")
        order_p = list(pc_all.index)
        cols_p = ["#e8736b" if b == focus else "#7aa2f7" for b in order_p]
        fig = px.bar(x=pc_all.values, y=order_p, orientation="h",
                     text=[f"{v:,.0f}" for v in pc_all.values])
        fig.update_traces(marker_color=cols_p)
        show_selectable(fig, k_perc)
    with c4:
        st.subheader(f"逾期帳款比率 Top {top_n}（{sel_month}・%）")
        order_r = list(rk_all.index)
        cols_r = ["#b48ead" if b == focus else "#e8736b" for b in order_r]
        fig = px.bar(x=rk_all.values, y=order_r, orientation="h",
                     text=[f"{v:.2f}" for v in rk_all.values])
        fig.update_traces(marker_color=cols_r)
        show_selectable(fig, k_over)

    st.subheader(f"簽帳金額 vs 流通卡數（泡泡＝機構，{sel_month}）")
    sc["聚焦"] = np.where(sc["機構名稱"] == focus, "聚焦", "其他") if focus else "全部"
    fig = px.scatter(sc, x="卡數萬張", y="簽帳億元", text="機構名稱",
                     size="簽帳億元", color="簽帳億元",
                     color_continuous_scale="YlOrBr")
    fig.update_traces(textposition="top center", textfont_size=9)
    show_selectable(fig, k_sc, 460)

# ----------------------------------------------------------------------
# Tab3 產品分析
# ----------------------------------------------------------------------
with tab3:
    nonce = focus_nonce("t3")
    ct = banks["主卡別"].value_counts()
    k_pie = f"t3_pie_{nonce}"
    focus_cat = focus_control("t3", "產品分析 · 聚焦卡別", list(ct.index),
                              [(k_pie, list(ct.index))])

    bset = banks[banks["主卡別"] == focus_cat] if focus_cat else banks

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("信用卡主卡別分布")
        pull = [0.08 if n == focus_cat else 0 for n in ct.index]
        fig = px.pie(values=ct.values, names=ct.index, hole=0.5,
                     color_discrete_sequence=PALETTE)
        fig.update_traces(pull=pull)
        show_selectable(fig, k_pie)
    with c2:
        st.subheader(f"各銀行收錄產品數{'（'+focus_cat+'）' if focus_cat else ''}")
        bp = bset["銀行名稱"].value_counts().sort_values()
        fig = px.bar(x=bp.values, y=bp.index, orientation="h",
                     text=bp.values, color_discrete_sequence=["#9ece6a"])
        st.plotly_chart(fig_style(fig), use_container_width=True)

    if "最高回饋率_pct" in banks.columns:
        c3, c4 = st.columns(2)
        with c3:
            st.subheader("各卡別最高回饋率分布（%）")
            bb = banks.dropna(subset=["最高回饋率_pct"])
            fig = px.box(bb, x="主卡別", y="最高回饋率_pct", points="all",
                         color="主卡別", color_discrete_sequence=PALETTE)
            if focus_cat:                      # 聚焦時淡化其他卡別
                fig.update_traces(opacity=0.25)
                fig.for_each_trace(
                    lambda tr: tr.update(opacity=1.0) if tr.name == focus_cat else None)
            st.plotly_chart(fig_style(fig), use_container_width=True)
        with c4:
            st.subheader(f"最高回饋率 Top 15{'（'+focus_cat+'）' if focus_cat else ''}")
            top_rw = (bset.dropna(subset=["最高回饋率_pct"])
                      .nlargest(15, "最高回饋率_pct"))
            cols = [c for c in ["銀行名稱", "卡片名稱", "主卡別", "最高回饋率_pct"]
                    if c in top_rw.columns]
            st.dataframe(top_rw[cols], use_container_width=True, height=360,
                         hide_index=True)

    st.subheader(f"產品明細{'（'+focus_cat+'）' if focus_cat else ''}")
    show_cols = [c for c in ["銀行名稱", "卡片名稱", "主卡別", "回饋亮點", "最高回饋率_pct"]
                 if c in bset.columns]
    st.dataframe(bset[show_cols], use_container_width=True, height=320,
                 hide_index=True)

# ----------------------------------------------------------------------
# Tab4 社群聲量
# ----------------------------------------------------------------------
with tab4:
    nonce = focus_nonce("t4")
    mention_cols = [c for c in ptt.columns if c.startswith("提及_")]
    mention = {c.replace("提及_", ""): int(ptt[c].sum()) for c in mention_cols}
    ms = pd.Series(mention).sort_values()
    k_voice = f"t4_voice_{nonce}"
    focus_bk = focus_control("t4", "社群聲量 · 聚焦銀行",
                             list(ms.sort_values(ascending=False).index),
                             [(k_voice, list(ms.index))])

    # 聚焦時：貼文子集為「提及該銀行」的文章
    psub = ptt[ptt[f"提及_{focus_bk}"]] if focus_bk else ptt
    tg = f"{focus_bk}：" if focus_bk else ""

    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"{tg}PTT 每月貼文量")
        pv = psub.groupby("年月").size().reset_index(name="篇數")
        fig = px.bar(pv, x="年月", y="篇數", color_discrete_sequence=["#e8b84b"])
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c2:
        st.subheader(f"{tg}貼文分類占比")
        cc = psub["分類"].value_counts()
        fig = px.pie(values=cc.values, names=cc.index, hole=0.5,
                     color_discrete_sequence=PALETTE)
        st.plotly_chart(fig_style(fig), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("各銀行社群聲量（被提及篇數）")
        order_v = list(ms.index)
        cols_v = ["#e8736b" if b == focus_bk else "#4fd1c5" for b in order_v]
        fig = px.bar(x=ms.values, y=order_v, orientation="h", text=ms.values)
        fig.update_traces(marker_color=cols_v)
        show_selectable(fig, k_voice)
    with c4:
        if focus_bk:
            st.subheader(f"{focus_bk}：每月被提及篇數")
            mv = (ptt.groupby("年月")[f"提及_{focus_bk}"].sum()
                  .reset_index(name="篇數"))
            fig = px.line(mv, x="年月", y="篇數", markers=True,
                          color_discrete_sequence=["#e8736b"])
        else:
            st.subheader("聲量隨時間變化（Top 5 被提及銀行）")
            top_banks = sorted(mention, key=mention.get, reverse=True)[:5]
            rows = []
            for ym, g in ptt.groupby("年月"):
                for b in top_banks:
                    rows.append({"年月": ym, "銀行": b,
                                 "篇數": int(g[f"提及_{b}"].sum())})
            sv = pd.DataFrame(rows)
            fig = px.line(sv, x="年月", y="篇數", color="銀行",
                          color_discrete_sequence=PALETTE)
        st.plotly_chart(fig_style(fig), use_container_width=True)

    st.subheader(f"{tg}熱門貼文 Top 10（依推噓數）")
    hot = psub.sort_values("推噓數", ascending=False).head(10)
    hot_cols = [c for c in ["title", "分類", "推噓數", "年月"] if c in hot.columns]
    st.dataframe(hot[hot_cols].rename(columns={"title": "標題"}),
                 use_container_width=True, height=360, hide_index=True)

# ----------------------------------------------------------------------
# Tab5 優惠比較
# ----------------------------------------------------------------------
with tab5:
    st.subheader("各銀行信用卡優惠比較")

    nonce = focus_nonce("t5")
    rate_chart_key = f"t5_rate_{nonce}"
    rate_series = (banks.dropna(subset=["最高回饋率_pct"])
                   .groupby("銀行名稱")["最高回饋率_pct"].mean().sort_values())
    rate_order = list(rate_series.index)          # 與長條 y 軸順序一致（升冪）

    focus_bank = focus_control("t5", "優惠比較 · 聚焦銀行", sorted(banks["銀行名稱"].unique()),
                               [(rate_chart_key, rate_order)])

    f1, f2, f3, f4 = st.columns([1.4, 1.4, 1.4, 1])
    with f1:
        sel_banks = st.multiselect("銀行", sorted(banks["銀行名稱"].unique()),
                                   default=[], key="cmp_bank",
                                   disabled=bool(focus_bank))
    with f2:
        sel_types = st.multiselect("卡片類型（可複選）", CARD_TYPE_TAGS,
                                   default=[], key="cmp_type")
    with f3:
        sel_scenes = st.multiselect("適用場景（可複選）", list(SCENE_KW.keys()),
                                    default=[], key="cmp_scene")
    with f4:
        max_rate = float(np.nanmax(banks["最高回饋率_pct"])) \
            if banks["最高回饋率_pct"].notna().any() else 50.0
        min_rate = st.slider("最低回饋率 %", 0.0, float(round(max_rate)), 0.0, 0.5,
                             key="cmp_rate")

    # 套用篩選（聚焦銀行優先；其次才看多選銀行）
    f = banks.copy()
    if focus_bank:
        f = f[f["銀行名稱"] == focus_bank]
    elif sel_banks:
        f = f[f["銀行名稱"].isin(sel_banks)]
    if sel_types:                      # 命中任一所選卡別即保留
        mask = np.zeros(len(f), dtype=bool)
        for t in sel_types:
            mask |= f[f"類_{t}"].to_numpy()
        f = f[mask]
    if sel_scenes:
        mask = np.zeros(len(f), dtype=bool)
        for s in sel_scenes:
            mask |= f[f"場景_{s}"].to_numpy()
        f = f[mask]
    if min_rate > 0:
        f = f[f["最高回饋率_pct"].fillna(-1) >= min_rate]

    extra = f"｜已聚焦 {focus_bank}" if focus_bank else ""
    st.caption(f"符合條件：{len(f)} 張卡（共 {len(banks)} 張）{extra}")

    show_cols = [c for c in ["銀行名稱", "卡片名稱", "場景標籤", "最高回饋率_pct",
                             "回饋亮點", "申辦連結"] if c in f.columns]
    tbl = f.sort_values("最高回饋率_pct", ascending=False, na_position="last")[show_cols]
    st.dataframe(
        tbl, use_container_width=True, height=360, hide_index=True,
        column_config={
            "最高回饋率_pct": st.column_config.NumberColumn("最高回饋率%", format="%.2f"),
            "申辦連結": st.column_config.LinkColumn("申辦", display_text="前往"),
            "回饋亮點": st.column_config.TextColumn("回饋亮點", width="large"),
        })

    st.divider()
    st.markdown("#### 🔬 並排比較（最多選 4 張）")
    # 聚焦時，候選清單預設只列該銀行的卡，方便直接挑來比
    pool = banks[banks["銀行名稱"] == focus_bank] if focus_bank else banks
    name_map = {f"{r['銀行名稱']}｜{r['卡片名稱']}": i for i, r in pool.iterrows()}
    picks = st.multiselect("挑選卡片", list(name_map.keys()), max_selections=4)
    if picks:
        rows = []
        for label in picks:
            r = banks.loc[name_map[label]]
            rate = r["最高回饋率_pct"]
            rows.append({
                "卡片": label,
                "卡片類型": "、".join(r["卡別標籤"]) or "—",
                "最高回饋率": f"{rate:.2f}%" if pd.notna(rate) else "—",
                "適用場景": r["場景標籤"],
                "回饋亮點": r.get("回饋亮點", ""),
            })
        comp = pd.DataFrame(rows).set_index("卡片").T
        st.dataframe(comp, use_container_width=True)
    else:
        st.info("從上方挑選 2~4 張卡片即可並排比較。")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("各銀行平均最高回饋率（%）")
        colors = ["#e8736b" if b == focus_bank else "#e8b84b" for b in rate_order]
        figr = px.bar(x=rate_series.values, y=rate_order, orientation="h",
                      text=[f"{v:.1f}" for v in rate_series.values])
        figr.update_traces(marker_color=colors)
        show_selectable(figr, rate_chart_key)
    with c2:
        if focus_bank:
            st.subheader(f"{focus_bank}：各場景卡片數")
            sub = banks[banks["銀行名稱"] == focus_bank]
        else:
            st.subheader("各適用場景的卡片數")
            sub = banks
        scene_cnt = pd.Series(
            {s: int(sub[f"場景_{s}"].sum()) for s in SCENE_KW}
        ).sort_values()
        fig = px.bar(x=scene_cnt.values, y=scene_cnt.index, orientation="h",
                     text=scene_cnt.values, color_discrete_sequence=["#4fd1c5"])
        st.plotly_chart(fig_style(fig), use_container_width=True)

    if focus_bank:
        st.subheader(f"{focus_bank} × 卡片類型 分布（張數）")
        heat_src = banks[banks["銀行名稱"] == focus_bank]
    else:
        st.subheader("銀行 × 卡片類型 分布（張數）")
        heat_src = banks
    heat = pd.DataFrame(
        {t: heat_src.groupby("銀行名稱")[f"類_{t}"].sum() for t in CARD_TYPE_TAGS})
    heat = heat.loc[heat.sum(axis=1).sort_values(ascending=False).index]
    fig = px.imshow(heat, text_auto=True, aspect="auto",
                    color_continuous_scale="YlGnBu",
                    labels=dict(x="卡片類型", y="銀行", color="張數"))
    st.plotly_chart(fig_style(fig, 420), use_container_width=True)

with st.expander("📋 資料說明 / 口徑"):
    st.markdown(
        "- **金額單位**：原始為「新臺幣百萬元」，圖表多換算為「億元」(÷100)；卡數換算「萬張」(÷1e4)。\n"
        "- **卡均簽帳金額**：本月簽帳金額 ÷ 有效卡數。\n"
        "- **HHI**：各機構簽帳市占百分比的平方和，>2500 一般視為高度集中。\n"
        "- **社群聲量**：以關鍵字比對 PTT 標題＋內文是否「提及」該銀行，非情緒分析。\n"
        "- **卡片類型**：原始「卡片類型」為複合標籤，以「/」拆成多標籤（現金回饋/紅利點數/哩程/聯名卡/高階卡/一般）。\n"
        "- **適用場景**：依回饋亮點文字關鍵字比對（海外、旅遊、行動支付、加油、餐飲、超商、網購、影音等），一張卡可屬多場景；無命中標為「綜合/未標示」。\n"
        "- **最高回饋率**：從回饋亮點文字解析出的最大百分比；部分卡無明確數字故顯示「—」。\n"
        "- 資料來源：金管會發卡統計 · 各銀行產品目錄 · PTT 信用卡板｜清理後存於 MySQL。")

st.caption("資料來源：金管會發卡統計 · 各銀行產品目錄 · PTT 信用卡板｜清理後存於 MySQL")

# 側邊欄底部：一鍵清除所有分頁的聚焦（callback 於 widget 建立前執行，合法）
with st.sidebar:
    st.button("顯示全部（清除所有聚焦）", on_click=clear_all_focus,
              use_container_width=True)