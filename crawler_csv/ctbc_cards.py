"""
中國信託信用卡清單載入器
================================
中信官網有 WAF (APP-1053) 防護,Playwright 動態爬取常被擋,
故維護一份手動清單作為後備。

【真實來源 = ctbc_cards.csv】(與本檔同資料夾)
本檔只負責「讀」CSV,你直接編輯 CSV 即可,不用改 Python。
scraper_banks.py 會在中信動態抓取失敗時,自動讀這份清單當後備。

【CSV 格式】三欄,UTF-8-SIG 編碼 (Excel 可直接開):
    卡片名稱, 網址, 亮點
    - 亮點: 多條用全形分隔線「｜」隔開 (例: 3%回饋｜首刷禮｜年費減免)
    - 卡名請以「卡」結尾;停發卡可在卡名後加「(停發)」,scraper 會自動標記

【維護方式】
1. 直接用 Excel / 文字編輯器開 ctbc_cards.csv 增刪改
2. 新增一張卡 = 加一列
3. 若 CSV 不存在,首次 import 會自動用內建種子清單產生一份,
   之後就以該 CSV 為準

【偵測新卡】
scraper 動態若哪天成功抓到中信卡名,會自動比對此清單,
log 提示官網有、但 CSV 沒有的卡 (建議補進 CSV)。

【最後更新】2026-05
"""

import csv
import os

# CSV 路徑:與本檔同資料夾
_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "ctbc_cards.csv")

HL_SEP = "｜"  # 亮點分隔符 (全形)

# 內建種子清單:僅在 CSV 不存在時用來產生初始 CSV
_SEED = [
    ("中信LINE Pay卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/LINEPay/index.html",
     ["LINE POINTS 最高 16% 回饋", "國內外一般消費 1% 回饋", "國外實體商店消費 2.8% 回饋"]),
    ("中信ALL ME卡", "https://mkt.ctbcbank.com/long/creditcard/ALLME_CHT/index.html",
     ["天天享 3% 回饋", "月月賺 $300", "國外消費 2.2% 無上限"]),
    ("中信foodpanda聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/foodpanda/index.html",
     ["foodpanda 點餐享胖達幣回饋", "全站消費最高 10% 胖達幣回饋"]),
    ("中信和泰聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/Hotai/index.html",
     ["iRent / yoxi 享最高 10% 回饋", "和泰集團通路享和泰 Points"]),
    ("中信中華航空聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/CTBCCI/index.html",
     ["國外消費最高 2 元 = 1 哩程", "華航官網購票享優惠"]),
    ("中信uniopen聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/uniopen/index.html",
     ["7-ELEVEN / 統一集團通路最高 8% OPENPOINT", "新戶首刷禮"]),
    ("中信遠東SOGO聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/SOGO/index.html",
     ["SOGO 百貨單筆消費最高 6% 回饋", "週年慶滿額禮"]),
    ("中信財管鼎鑽卡", "https://mkt.ctbcbank.com/long/creditcard/WMmember/index.html",
     ["財富管理會員專屬權益", "機場接送、貴賓室、高爾夫禮遇"]),
    ("中信商旅鈦金卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/bussiness/index.html",
     ["指定通路最高回饋", "新戶首刷享刷卡金"]),
    ("中信中油聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/CPC/index.html",
     ["中油直營站綁定中油 Pay 最高 6.8% 回饋", "新戶最高贈 $300 加油金"]),
    ("中信Taipei 101聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/Taipei101/index.html",
     ["Taipei 101 樓層消費享回饋", "卡友訂位特權"]),
    ("中信秀泰聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/showtime/index.html",
     ["秀泰影城享電影票優惠", "影城內消費回饋"]),
    ("中信Agoda聯名卡", "https://mkt.ctbcbank.com/long/creditcard/agoda/index.html",
     ["Agoda 訂房享 A 金回饋", "海外消費最高回饋"]),
]


def _write_csv(path, rows):
    """rows: list of (name, url, [highlights])"""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["卡片名稱", "網址", "亮點"])
        for name, url, hl in rows:
            w.writerow([name, url, HL_SEP.join(hl)])


def _ensure_csv():
    """CSV 不存在時,用種子清單產生一份"""
    if not os.path.exists(CSV_PATH):
        try:
            _write_csv(CSV_PATH, _SEED)
        except Exception:
            pass  # 唯讀環境等情況:靜默,load 會 fallback 回種子


def load_cards():
    """讀 ctbc_cards.csv,回傳 [(卡名, 網址, [亮點...]), ...]。
    CSV 不存在 → 先產生再讀;讀失敗 → 回種子清單。"""
    _ensure_csv()
    try:
        out = []
        with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("卡片名稱") or "").strip()
                url = (row.get("網址") or "").strip()
                hl_raw = (row.get("亮點") or "").strip()
                if not name:
                    continue
                # 亮點支援全形｜或半形 | 或頓號、分隔
                hl = []
                if hl_raw:
                    parts = hl_raw.replace("|", HL_SEP).split(HL_SEP)
                    hl = [p.strip() for p in parts if p.strip()]
                out.append((name, url, hl))
        if out:
            return out
    except Exception:
        pass
    # 任何問題都回種子,確保 scraper 至少有後備
    return list(_SEED)


# scraper_banks.py 直接 import 這個變數 (介面與舊版相容)
CTBC_CARDS = load_cards()


def get_card_names() -> set:
    """回傳目前清單所有卡名 (供比對偵測新卡用)"""
    return {c[0] for c in CTBC_CARDS}


def diff_against(found_names) -> dict:
    """比對外部抓到的卡名 vs 此清單,回報差異。
    回傳 {'new': [官網有清單沒], 'gone': [清單有官網沒]}"""
    found = set(found_names)
    have = get_card_names()
    return {
        "new": sorted(found - have),
        "gone": sorted(have - found),
    }


if __name__ == "__main__":
    # 直接執行:重新從種子產生 CSV (覆蓋),方便重置
    import sys
    if "--reset" in sys.argv:
        _write_csv(CSV_PATH, _SEED)
        print(f"已用種子清單重置 {CSV_PATH} ({len(_SEED)} 張)")
    else:
        cards = load_cards()
        print(f"目前 ctbc_cards.csv 共 {len(cards)} 張:")
        for name, url, hl in cards:
            print(f"  {name:<22} | 亮點 {len(hl)} 條")
        print(f"\nCSV 路徑:{CSV_PATH}")
        print("如要重置成內建種子清單,執行:python ctbc_cards.py --reset")
