"""
共用模組 (common.py)
====================
兩支爬蟲 (scraper_banks.py / scraper_roocash.py) 共用的：
- 輸出欄位定義 (COLUMNS)
- 卡名雜訊過濾 (NoiseFilter)
- 卡片類型推斷 (guess_card_type)
- CSV 輸出工具 (save_csv)

這樣兩支爬蟲輸出格式一致，後續可直接合併分析。
"""

import re
import logging
import pandas as pd
from datetime import datetime

# ── 統一輸出欄位 ──────────────────────────────────────────────────────────
COLUMNS = [
    "銀行名稱", "銀行代碼", "卡片名稱", "卡片類型",
    "回饋亮點1", "回饋亮點2", "回饋亮點3",
    "申辦連結", "資料來源", "更新時間",
]


def setup_logger(name: str, logfile: str) -> logging.Logger:
    """建立同時輸出到檔案與終端機的 logger"""
    logger = logging.getLogger(name)
    if logger.handlers:  # 避免重複加 handler
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ── 卡名雜訊過濾 ──────────────────────────────────────────────────────────
class NoiseFilter:
    """判斷一個字串是否為真實的信用卡名稱"""

    BLACKLIST_KEYWORDS = [
        "掛失", "補發", "開卡", "辦卡進度", "卡友", "卡片管理",
        "權益", "公告", "活動", "登入", "註冊", "推薦", "排行",
        "FAQ", "Q&A", "客服", "幫助", "說明", "比較", "介紹",
        "繳款", "帳單", "查詢", "下載", "上傳", "服務",
        "了解更多", "詳情", "立即申辦", "馬上申辦", "免費索取",
        "不知道", "怎麼選", "哪張",
    ]

    CARD_SUFFIXES = ("卡", "Card", "CARD", "card")
    MIN_LEN = 3
    MAX_LEN = 25

    @classmethod
    def is_valid(cls, name: str) -> bool:
        if not name or not isinstance(name, str):
            return False
        name = name.strip()
        if not (cls.MIN_LEN <= len(name) <= cls.MAX_LEN):
            return False
        if not name.endswith(cls.CARD_SUFFIXES):
            return False
        if any(kw in name for kw in cls.BLACKLIST_KEYWORDS):
            return False
        # 標點太多通常是廣告文案
        punct = sum(1 for c in name if c in "、，。！？：；()（）「」【】")
        if punct >= 2:
            return False
        return True

    @staticmethod
    def dedupe(names: list[str]) -> list[str]:
        seen, out = set(), []
        for n in names:
            n = n.strip()
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out


# ── 卡片類型推斷 ──────────────────────────────────────────────────────────
def guess_card_type(card_name: str, highlights: list[str] | None = None) -> str:
    """從卡名與回饋亮點推測卡片類型"""
    highlights = highlights or []
    text = card_name + " " + " ".join(highlights)
    types = []
    if "聯名" in card_name:
        types.append("聯名卡")
    if "現金回饋" in text or re.search(r"\d+\.?\d*\s*[%％]\s*(現金)?回饋", text):
        types.append("現金回饋")
    if "哩" in text or "里程" in text:
        types.append("哩程")
    if "紅利" in text or "點數" in text:
        types.append("紅利點數")
    if any(k in card_name for k in ("無限", "鼎極", "世界", "御璽", "尊爵")):
        types.append("高階卡")
    return "/".join(types) if types else "一般"


# ── 建立空白記錄 ──────────────────────────────────────────────────────────
def make_record(bank_name: str, bank_code: str, card_name: str,
                highlights: list[str], apply_url: str, source: str) -> dict:
    """產生一筆符合 COLUMNS 格式的記錄"""
    h = (highlights + ["", "", ""])[:3]  # 確保至少 3 個
    return {
        "銀行名稱": bank_name,
        "銀行代碼": bank_code,
        "卡片名稱": card_name,
        "卡片類型": guess_card_type(card_name, highlights),
        "回饋亮點1": h[0],
        "回饋亮點2": h[1],
        "回饋亮點3": h[2],
        "申辦連結": apply_url,
        "資料來源": source,
        "更新時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── CSV 輸出 (可同時寫入 MySQL) ────────────────────────────────────────────
def save_csv(records: list[dict], output: str | None, prefix: str,
             table: str | None = None) -> pd.DataFrame:
    """將記錄存成 CSV,回傳 DataFrame。

    若有給 table,會在寫完 CSV 後「同時」把同一份資料寫進 MySQL
    (建表若無 → 清空全部 → 寫入)。DB 失敗不影響 CSV。
    """
    df = pd.DataFrame(records, columns=COLUMNS)
    if not df.empty:
        df = df.sort_values(["銀行名稱", "卡片名稱"]).reset_index(drop=True)
    if output is None:
        output = f"{prefix}_{datetime.now().strftime('%Y%m')}.csv"
    df.to_csv(output, index=False, encoding="utf-8-sig")

    # 同步寫入 MySQL (可選)
    if table:
        try:
            from db_common import write_df_to_mysql
            write_df_to_mysql(df, table)
        except ImportError:
            logging.getLogger("card_common").warning(
                "找不到 db_common,略過 MySQL 寫入 (請確認 db_common.py 存在"
                "且已安裝 sqlalchemy / pymysql)。")
    return df