# -*- coding: utf-8 -*-
"""
台灣信用卡市場分析儀表板 (Streamlit)
======================================================================
資料來源：MySQL `mydb` 內清理後的資料表
  credit_card_stats_clean / banks_clean / ptt_credit_card_clean / dashboard_agg
連線設定全部走環境變數（見 streamlit.yml）。
"""
import os
from urllib.parse import quote_plus

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

# ----------------------------------------------------------------------
# 連線設定（環境變數優先）
# ----------------------------------------------------------------------
CFG = {
    "host": os.getenv("MYSQL_HOST", "host.docker.internal"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "db":   os.getenv("MYSQL_DB",   "mydb"),
    "user": os.getenv("MYSQL_USER", "root"),
    "pwd":  os.getenv("MYSQL_PASSWORD", "ppWgnb_mfGe2m_"),
}
# 清理後表名（可用環境變數覆寫；含舊版命名的後備候選）
TABLE_CANDIDATES = {
    "stats": [os.getenv("TBL_STATS", "credit_card_stats_clean"), "stats_clean"],
    "banks": [os.getenv("TBL_BANKS", "banks_clean")],
    "ptt":   [os.getenv("TBL_PTT", "ptt_credit_card_clean"), "ptt_clean"],
}

st.set_page_config(page_title="信用卡市場儀表板", page_icon="💳",
                   layout="wide", initial_sidebar_state="expanded")

PALETTE = ["#e8b84b", "#4fd1c5", "#7aa2f7", "#e8736b",
           "#b48ead", "#9ece6a", "#f2cd6e", "#56c8d8"]


# ----------------------------------------------------------------------
# 資料存取（快取）
# ----------------------------------------------------------------------
@st.cache_resource
def get_engine():
    url = (f"mysql+pymysql://{CFG['user']}:{quote_plus(CFG['pwd'])}"
           f"@{CFG['host']}:{CFG['port']}/{CFG['db']}?charset=utf8mb4")
    return create_engine(url, pool_pre_ping=True)


def resolve_table(eng, key):
    """從候選名稱挑出實際存在的表名。"""
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
    t = resolve_table(eng, "stats")
    return pd.read_sql(f"SELECT * FROM `{t}`", eng)


@st.cache_data(ttl=600)
def load_banks():
    eng = get_engine()
    t = resolve_table(eng, "banks")
    return pd.read_sql(f"SELECT * FROM `{t}`", eng)


@st.cache_data(ttl=600)
def load_ptt():
    eng = get_engine()
    t = resolve_table(eng, "ptt")
    # 不撈 content（很長）以加速
    cols = pd.read_sql(
        text("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
             "WHERE TABLE_SCHEMA=:d AND TABLE_NAME=:t"),
        eng, params={"d": CFG["db"], "t": t})["COLUMN_NAME"].tolist()
    use = [c for c in cols if c != "content"]
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
    return fig


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
            "請確認 MySQL 可連線、清理後的資料表已建立。")
    st.stop()

# 共用欄位
SPEND = "本月簽帳金額-新臺幣百萬元"
CARDS = "流通卡數-張"
REVOLVE = "循環信用餘額-新臺幣百萬元"
OVERDUE = "逾期帳款比率-%"
PERCARD = "卡均簽帳金額_元"

months = sorted(stats["年月"].unique())
latest = months[-1]

# ----------------------------------------------------------------------
# 側邊欄篩選
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("篩選條件")
    sel_month = st.selectbox("統計月份（KPI / 排名）", months, index=len(months) - 1)
    top_n = st.slider("排名顯示前 N 名", 5, 20, 12)
    st.caption(f"資料區間：{months[0]} ~ {months[-1]}")
    st.caption(f"連線：{CFG['host']}:{CFG['port']}/{CFG['db']}")

cur = stats[stats["年月"] == sel_month]

# ----------------------------------------------------------------------
# KPI 區
# ----------------------------------------------------------------------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("流通卡數", f"{cur[CARDS].sum()/1e4:,.0f} 萬張")
k2.metric("有效卡數", f"{cur['有效卡數-張'].sum()/1e4:,.0f} 萬張")
k3.metric("本月簽帳", f"{cur[SPEND].sum()/100:,.0f} 億元")
k4.metric("循環餘額", f"{cur[REVOLVE].sum()/100:,.0f} 億元")
k5.metric("統計機構數", f"{cur['機構名稱'].nunique()} 家")

st.caption(f"以上為 {sel_month} 全市場加總")

tab1, tab2, tab3, tab4 = st.tabs(["📈 市場總覽", "🏦 機構競爭", "💼 產品分析", "💬 社群聲量"])

# ----------------------------------------------------------------------
# Tab1 市場總覽
# ----------------------------------------------------------------------
with tab1:
    trend = (stats.groupby("年月")
             .agg(簽帳億元=(SPEND, lambda s: s.sum() / 100),
                  流通萬張=(CARDS, lambda s: s.sum() / 1e4),
                  循環億元=(REVOLVE, lambda s: s.sum() / 100))
             .reset_index())
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("全市場每月簽帳金額趨勢（億元）")
        fig = px.area(trend, x="年月", y="簽帳億元", color_discrete_sequence=["#e8b84b"])
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c2:
        st.subheader("流通卡數 vs 循環信用餘額")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend["年月"], y=trend["流通萬張"],
                                 name="流通卡數(萬張)", line=dict(color="#4fd1c5")))
        fig.add_trace(go.Scatter(x=trend["年月"], y=trend["循環億元"],
                                 name="循環餘額(億元)", yaxis="y2", line=dict(color="#e8736b")))
        fig.update_layout(yaxis2=dict(overlaying="y", side="right"))
        st.plotly_chart(fig_style(fig), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader(f"簽帳金額 Top {top_n}（億元）")
        ts = (cur.groupby("機構名稱")[SPEND].sum() / 100).sort_values(ascending=True).tail(top_n)
        fig = px.bar(x=ts.values, y=ts.index, orientation="h",
                     color_discrete_sequence=["#e8b84b"])
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c4:
        st.subheader(f"流通卡數市占 Top {top_n}（萬張）")
        tc = (cur.groupby("機構名稱")[CARDS].sum() / 1e4).sort_values(ascending=True).tail(top_n)
        fig = px.bar(x=tc.values, y=tc.index, orientation="h",
                     color_discrete_sequence=["#4fd1c5"])
        st.plotly_chart(fig_style(fig), use_container_width=True)

# ----------------------------------------------------------------------
# Tab2 機構競爭
# ----------------------------------------------------------------------
with tab2:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"卡均簽帳金額 Top {top_n}（元）")
        pc = cur.groupby("機構名稱")[PERCARD].mean().sort_values(ascending=True).tail(top_n)
        fig = px.bar(x=pc.values, y=pc.index, orientation="h",
                     color_discrete_sequence=["#7aa2f7"])
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c2:
        st.subheader(f"逾期帳款比率 Top {top_n}（%）")
        rk = cur.groupby("機構名稱")[OVERDUE].mean().sort_values(ascending=True).tail(top_n)
        fig = px.bar(x=rk.values, y=rk.index, orientation="h",
                     color_discrete_sequence=["#e8736b"])
        st.plotly_chart(fig_style(fig), use_container_width=True)

    st.subheader("簽帳金額 vs 流通卡數（泡泡＝機構）")
    sc = cur.groupby("機構名稱").agg(
        卡數萬張=(CARDS, lambda s: s.sum() / 1e4),
        簽帳億元=(SPEND, lambda s: s.sum() / 100)).reset_index()
    fig = px.scatter(sc, x="卡數萬張", y="簽帳億元", text="機構名稱",
                     size="簽帳億元", color="簽帳億元",
                     color_continuous_scale="YlOrBr")
    fig.update_traces(textposition="top center", textfont_size=9)
    st.plotly_chart(fig_style(fig, 460), use_container_width=True)

# ----------------------------------------------------------------------
# Tab3 產品分析
# ----------------------------------------------------------------------
with tab3:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("信用卡主卡別分布")
        ct = banks["主卡別"].value_counts()
        fig = px.pie(values=ct.values, names=ct.index, hole=0.5,
                     color_discrete_sequence=PALETTE)
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c2:
        st.subheader("各銀行收錄產品數")
        bp = banks["銀行名稱"].value_counts().sort_values(ascending=True)
        fig = px.bar(x=bp.values, y=bp.index, orientation="h",
                     color_discrete_sequence=["#9ece6a"])
        st.plotly_chart(fig_style(fig), use_container_width=True)

    st.subheader("產品明細")
    show_cols = [c for c in ["銀行名稱", "卡片名稱", "主卡別", "回饋亮點", "最高回饋率_pct"]
                 if c in banks.columns]
    st.dataframe(banks[show_cols], use_container_width=True, height=320)

# ----------------------------------------------------------------------
# Tab4 社群聲量
# ----------------------------------------------------------------------
with tab4:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("PTT 每月貼文量")
        pv = ptt.groupby("年月").size().reset_index(name="篇數")
        fig = px.bar(pv, x="年月", y="篇數", color_discrete_sequence=["#e8b84b"])
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c2:
        st.subheader("貼文分類占比")
        cc = ptt["分類"].value_counts()
        fig = px.pie(values=cc.values, names=cc.index, hole=0.5,
                     color_discrete_sequence=PALETTE)
        st.plotly_chart(fig_style(fig), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("各銀行社群聲量（被提及篇數）")
        mention_cols = [c for c in ptt.columns if c.startswith("提及_")]
        mention = {c.replace("提及_", ""): int(ptt[c].sum()) for c in mention_cols}
        ms = pd.Series(mention).sort_values(ascending=True)
        fig = px.bar(x=ms.values, y=ms.index, orientation="h",
                     color_discrete_sequence=["#4fd1c5"])
        st.plotly_chart(fig_style(fig), use_container_width=True)
    with c4:
        st.subheader("熱門貼文 Top 10（依推噓數）")
        hot = ptt.sort_values("推噓數", ascending=False).head(10)
        hot_cols = [c for c in ["title", "分類", "推噓數", "年月"] if c in hot.columns]
        st.dataframe(hot[hot_cols].rename(columns={"title": "標題"}),
                     use_container_width=True, height=360)

st.caption("資料來源：金管會發卡統計 · 各銀行產品目錄 · PTT 信用卡板｜清理後存於 MySQL")
