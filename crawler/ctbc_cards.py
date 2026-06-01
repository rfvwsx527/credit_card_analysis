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

【偵測 + 自動寫回新卡】(v2 新增)
scraper 動態若哪天成功抓到中信卡名,會呼叫 sync_from_found(),
自動把「官網有、但 CSV 沒有」的新卡寫回 ctbc_cards.csv,
下次執行就會用到最新清單。

安全保護:
- 動態抓取結果過少 (< MIN_FOUND) 視為被 WAF 擋,直接跳過,不寫入。
  避免「抓到空值 → 誤判整份清單全下架」。
- 只「新增」不「自動刪除」。官網查無的卡僅在 log 提示 (gone),
  是否移除交由人工判斷,以免誤刪停發但仍想保留的卡。

【主要對外介面】
- CTBC_CARDS            : list[(卡名, 網址, [亮點...])]  (與舊版相容)
- load_cards()          : 讀 CSV
- reload()              : 重新讀 CSV 並更新 CTBC_CARDS (寫入後呼叫)
- add_cards(rows)       : 把新卡 append 進 CSV (去重),回傳實際新增的卡名
- sync_from_found(found): 接收動態抓到的卡 → 比對 → 寫回新卡 → 回報差異
- get_card_names()      : 目前所有卡名 set
- diff_against(found)   : 只比對不寫入 (舊版相容)

【最後更新】2026-05 (v2:支援自動寫回)
"""

import csv
import os

# CSV 路徑:與本檔同資料夾
_HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(_HERE, "ctbc_cards.csv")

HL_SEP = "｜"  # 亮點分隔符 (全形)

# 動態抓取結果少於這個數量,視為被 WAF 擋/抓取異常,sync 時直接跳過不寫入。
# 中信實際發行卡數約十餘張,設 3 是保守下限,可自行調整。
MIN_FOUND = 3

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


def _append_rows(path, rows):
    """把新列 append 到既有 CSV 末尾 (不覆蓋)。rows: list of (name, url, [hl])。
    CSV 不存在時先建表頭。"""
    need_header = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if need_header:
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


def reload():
    """重新讀取 CSV,更新模組層級的 CTBC_CARDS。
    寫入新卡後呼叫,讓 import 此模組的程式拿到最新清單。回傳新的 CTBC_CARDS。"""
    global CTBC_CARDS
    CTBC_CARDS = load_cards()
    return CTBC_CARDS


def get_card_names() -> set:
    """回傳目前清單所有卡名 (供比對偵測新卡用)"""
    return {c[0] for c in CTBC_CARDS}


def _normalize_found(found):
    """把外部傳進來的卡片資料統一成 [(name, url, [hl]), ...]。
    支援三種格式:
      - tuple/list: (name, url, [hl]) 或 (name, url)
      - dict: {'卡片名稱'/'name', '申辦連結'/'網址'/'url', '亮點'/'highlights'/'回饋亮點1..3'}
      - 純字串: 只有卡名 (url/亮點留空)
    """
    out = []
    for item in found or []:
        if isinstance(item, str):
            name, url, hl = item.strip(), "", []
        elif isinstance(item, dict):
            name = (item.get("卡片名稱") or item.get("name") or "").strip()
            url = (item.get("申辦連結") or item.get("網址")
                   or item.get("url") or "").strip()
            hl = item.get("亮點") or item.get("highlights")
            if hl is None:
                # 退而求其次:湊 回饋亮點1/2/3
                hl = [item.get(f"回饋亮點{i}", "") for i in (1, 2, 3)]
            hl = [h.strip() for h in (hl or []) if isinstance(h, str) and h.strip()]
        else:  # tuple / list
            name = (item[0] if len(item) > 0 else "").strip()
            url = (item[1] if len(item) > 1 else "").strip()
            hl = list(item[2]) if len(item) > 2 and item[2] else []
            hl = [str(h).strip() for h in hl if str(h).strip()]
        if name:
            out.append((name, url, hl))
    return out


def add_cards(rows) -> list:
    """把新卡 append 進 CSV,自動以卡名去重 (已存在的略過)。
    rows: 可為 (name,url,[hl]) tuple、dict 或字串,見 _normalize_found。
    回傳實際新增的卡名 list;寫入後會自動 reload()。"""
    norm = _normalize_found(rows)
    have = get_card_names()
    to_add, seen = [], set()
    for name, url, hl in norm:
        if name in have or name in seen:
            continue
        seen.add(name)
        to_add.append((name, url, hl))
    if not to_add:
        return []
    _ensure_csv()
    try:
        _append_rows(CSV_PATH, to_add)
    except Exception:
        # 唯讀環境等情況:寫入失敗就只更新記憶體 (不持久化)
        global CTBC_CARDS
        CTBC_CARDS = CTBC_CARDS + to_add
        return [n for n, _, _ in to_add]
    reload()
    return [n for n, _, _ in to_add]


def diff_against(found_names) -> dict:
    """比對外部抓到的卡名 vs 此清單,回報差異 (只比對,不寫入)。
    回傳 {'new': [官網有清單沒], 'gone': [清單有官網沒]}"""
    found = {n.strip() for n in found_names if n and n.strip()}
    have = get_card_names()
    return {
        "new": sorted(found - have),
        "gone": sorted(have - found),
    }


def sync_from_found(found, write=True, logger=None) -> dict:
    """接收 scraper 動態抓到的中信卡片,比對清單並把新卡寫回 CSV。

    found: 動態抓到的卡片,格式見 _normalize_found
           (常見:scraper 傳進 (卡名, 連結, [亮點]) 或 record dict)
    write: True 才實際寫入 CSV;False 只比對 (dry-run)
    logger: 可選,傳入後用它輸出訊息 (否則 print)

    安全保護:
      - 有效卡數 < MIN_FOUND → 視為被 WAF 擋,直接跳過 (不寫入、不報 gone)
      - 只新增,不自動刪除;官網查無的卡僅放進 'gone' 供人工判斷

    回傳 dict:
      {
        'skipped': bool,       # 是否因結果過少而跳過
        'added':  [新增寫回的卡名],
        'new':    [偵測到的新卡名 (write=False 時也有值)],
        'gone':   [清單有、這次沒抓到的卡名 (僅提示)],
        'count':  本次有效抓到的卡數,
      }
    """
    def _say(msg):
        if logger:
            logger.info(msg)
        else:
            print(msg)

    norm = _normalize_found(found)
    # 卡名去重
    uniq, seen = [], set()
    for name, url, hl in norm:
        if name not in seen:
            seen.add(name)
            uniq.append((name, url, hl))

    if len(uniq) < MIN_FOUND:
        _say(f"⚠️ 中信動態抓取只取得 {len(uniq)} 張 (< {MIN_FOUND}),"
             f"視為被擋,跳過同步,沿用現有 CSV。")
        return {"skipped": True, "added": [], "new": [],
                "gone": [], "count": len(uniq)}

    have = get_card_names()
    found_names = {n for n, _, _ in uniq}
    new = sorted(found_names - have)
    gone = sorted(have - found_names)

    added = []
    if write and new:
        new_rows = [(n, u, h) for n, u, h in uniq if n in set(new)]
        added = add_cards(new_rows)  # 內含去重 + reload
        _say(f"✅ 中信偵測到 {len(added)} 張新卡,已寫回 CSV:{', '.join(added)}")
    elif new:
        _say(f"🔍 中信偵測到 {len(new)} 張新卡 (dry-run 未寫入):{', '.join(new)}")
    else:
        _say("中信:無新卡。")

    if gone:
        _say(f"ℹ️ 下列卡在清單中、本次官網未抓到 (僅提示,不自動刪除):"
             f"{', '.join(gone)}")

    return {"skipped": False, "added": added, "new": new,
            "gone": gone, "count": len(uniq)}


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
        print("新卡會由 scraper_banks.py --ctbc-dynamic 動態抓到後自動寫回此 CSV。")