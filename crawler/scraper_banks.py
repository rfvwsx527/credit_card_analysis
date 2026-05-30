"""
各銀行官網爬蟲 (scraper_banks.py) — 使用 Playwright
====================================================
v9 (2026-05) 修正國泰、玉山、永豐、元大、凱基

主要修正:
1. JS 擷取器從 p/h3/span 擴大為「全頁葉子文字元素」+ img[alt] 兜底,
   解決 React SPA 卡名藏在 hashed-class <div> 內抓不到。
2. endsWith 檢查前先剝除尾端 (邀請制)/(停發)/【已停發】 等補述。
3. 元大 URL 改為 /bank/creditCard/creditCard/list.do (官網實際路徑)。
4. 凱基由 href 改 js (href 下連結文字是「了解更多」)。
5. JS_EXTRACT_HREFS 連結文字非卡名時,fallback 到 title / aria-label /
   連結內 h1-h6 / img alt / 周邊 3 層父容器 h1-h6。
"""

import argparse
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from card_common import (
    COLUMNS, NoiseFilter, make_record, save_csv, setup_logger,
)

log = setup_logger("scraper_banks", "scraper_banks.log")

# ── 中信 hardcode 清單 ──────────────────────────────────────────────────────
CTBC_CARDS = [
    ("中信LINE Pay卡",      "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/LINEPay/index.html"),
    ("中信ALL ME卡",        "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/ALLME/index.html"),
    ("中信foodpanda聯名卡", "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/foodpanda/index.html"),
    ("中信和泰聯名卡",      "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/Hotai/index.html"),
    ("中信中華航空聯名卡",  "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/CTBCCI/index.html"),
    ("中信uniopen卡",       "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/uniopen/index.html"),
    ("中信遠東SOGO聯名卡",  "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/SOGO/index.html"),
    ("中信財管鼎鑽卡",      "https://mkt.ctbcbank.com/long/creditcard/WMmember/index.html"),
    ("中信商旅鈦金卡",      "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/bussiness/index.html"),
    ("中信中油聯名卡",      "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/CPC/index.html"),
    ("中信台北101聯名卡",   "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/Taipei101/index.html"),
    ("中信秀泰聯名卡",      "https://www.ctbcbank.com/content/dam/minisite/long/creditcard/showtime/index.html"),
    ("中信Agoda聯名卡",     "https://mkt.ctbcbank.com/long/creditcard/agoda/index.html"),
]


def make_ctbc_records() -> list[dict]:
    records = []
    for card_name, url in CTBC_CARDS:
        records.append(make_record(
            bank_name="中國信託銀行", bank_code="ctbc",
            card_name=card_name, highlights=[],
            apply_url=url, source=url,
        ))
    log.info(f"  ✅ 中國信託銀行:{len(records)} 張(hardcode)")
    return records


# ── 共用 JS 函式 (raw string 讓 \s \u3000 等保持為 JS 字面值) ────────────────

JS_EXTRACT_CARD_NAMES = r"""
() => {
    // 剝除尾端括號補述,最多 3 層: ( ... ) （ ... ） 【 ... 】 [ ... ]
    const stripTail = (s) => {
        let t = (s || '').trim();
        for (let i = 0; i < 3; i++) {
            const before = t;
            t = t.replace(/[\s\u3000]*[\(（【\[][^\)）】\]]{0,30}[\)）】\]][\s\u3000]*$/, '').trim();
            if (t === before) break;
        }
        return t;
    };

    const looksLikeCard = (txt) => {
        if (!txt) return false;
        const t = txt.trim();
        if (t.length < 3 || t.length > 35) return false;
        if (/[\r\n\t]/.test(t)) return false;
        const core = stripTail(t);
        if (core.length < 3) return false;
        return core.endsWith('卡') || core.endsWith('Card') || core.endsWith('card');
    };

    const denyExact = new Set([
        '信用卡','銀行卡','聯名卡','其他卡','所有卡','卡片','一張卡','一卡',
        '熱門推薦卡','世界卡/無限卡','簽帳金融卡','頂級卡','聯名認同卡',
        '比較信用卡','所有信用卡','我的卡','熱門卡','聯名/認同卡','分類卡',
        '採購卡','行動支付卡','企業/採購卡','現金儲值卡','停發卡','整併卡',
        '比較卡','卡卡','卡','旅遊卡','回饋卡','分期卡','信用卡卡',
        '無限卡','鈦金卡','白金卡','金卡','普卡',
    ]);

    const denyInclude = [
        '掛失','補發','辦卡進度','卡片管理','繳款','帳單','信用卡服務',
        '常見問題','卡別','分類標籤','線上辦卡','請選擇您想要的服務',
        '更多介紹','立即申辦','瞭解更多','了解更多','禮遇專區',
        '卡片總覽','尋找適合','信用卡介紹',
    ];

    const inlineTags = new Set([
        'STRONG','EM','SPAN','I','B','U','BR','SMALL','SUB','SUP','MARK','FONT'
    ]);

    const matched = [];

    // 第一輪:掃所有元素,只取葉子文字 (children 全是 inline 或無 children)
    for (const el of document.querySelectorAll('*')) {
        const kids = el.children;
        if (kids.length > 0) {
            let containerLike = false;
            for (const c of kids) {
                const ct = (c.textContent || '').trim();
                if (ct.length > 0 && !inlineTags.has(c.tagName)) {
                    containerLike = true;
                    break;
                }
            }
            if (containerLike) continue;
        }

        const txt = ((el.innerText || el.textContent || '') + '').trim();
        if (!looksLikeCard(txt)) continue;
        if (denyExact.has(txt)) continue;
        if (denyInclude.some(k => txt.includes(k))) continue;
        if ((txt.match(/[、，。！？:：；]/g) || []).length >= 2) continue;

        const aEl = el.closest('a');
        matched.push({text: txt, href: aEl ? aEl.href : ''});
    }

    // 第二輪:img[alt] 兜底
    for (const img of document.querySelectorAll('img[alt]')) {
        const alt = (img.alt || '').trim();
        if (!looksLikeCard(alt)) continue;
        if (denyExact.has(alt)) continue;
        if (denyInclude.some(k => alt.includes(k))) continue;
        if ((alt.match(/[、，。！？:：；]/g) || []).length >= 2) continue;
        const aEl = img.closest('a');
        matched.push({text: alt, href: aEl ? aEl.href : ''});
    }

    const seen = new Set();
    return matched.filter(r => {
        if (seen.has(r.text)) return false;
        seen.add(r.text);
        return true;
    });
}
"""


JS_EXTRACT_HREFS = r"""
(hrefPart) => {
    const stripTail = (s) => {
        let t = (s || '').trim();
        for (let i = 0; i < 3; i++) {
            const before = t;
            t = t.replace(/[\s\u3000]*[\(（【\[][^\)）】\]]{0,30}[\)）】\]][\s\u3000]*$/, '').trim();
            if (t === before) break;
        }
        return t;
    };
    const looksLikeCard = (txt) => {
        if (!txt) return false;
        const t = txt.trim();
        if (t.length < 3 || t.length > 35) return false;
        if (/[\r\n\t]/.test(t)) return false;
        const core = stripTail(t);
        if (core.length < 3) return false;
        return core.endsWith('卡') || core.endsWith('Card') || core.endsWith('card');
    };
    const denyExact = new Set([
        '信用卡','銀行卡','聯名卡','其他卡','所有卡','卡片','一張卡','一卡',
        '熱門推薦卡','世界卡/無限卡','簽帳金融卡','頂級卡','聯名認同卡',
        '比較信用卡','所有信用卡','我的卡','熱門卡','聯名/認同卡',
        '採購卡','行動支付卡','企業/採購卡','現金儲值卡','停發卡',
        '比較卡','卡卡','卡','無限卡','鈦金卡','白金卡','金卡','普卡',
    ]);

    const results = [];
    const seen = new Set();

    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        if (!href.includes(hrefPart)) continue;

        // 卡名候選來源 (由近到遠)
        const candidates = [];
        const at = ((a.innerText || '') + '').trim();
        if (at) candidates.push(at);
        if (a.title) candidates.push(a.title.trim());
        const al = a.getAttribute('aria-label');
        if (al) candidates.push(al.trim());

        for (const h of a.querySelectorAll('h1,h2,h3,h4,h5,h6,p,span,strong')) {
            const t = ((h.innerText || '') + '').trim();
            if (t) candidates.push(t);
        }
        for (const img of a.querySelectorAll('img[alt]')) {
            const alt = (img.alt || '').trim();
            if (alt) candidates.push(alt);
        }

        let p = a.parentElement;
        for (let depth = 0; depth < 3 && p; depth++) {
            for (const h of p.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
                const t = ((h.innerText || '') + '').trim();
                if (t) candidates.push(t);
            }
            p = p.parentElement;
        }

        for (const txt of candidates) {
            if (!looksLikeCard(txt)) continue;
            if (denyExact.has(txt)) continue;
            if (seen.has(txt)) continue;
            seen.add(txt);
            results.push({text: txt, href: a.href});
            break;
        }
    }
    return results;
}
"""


# ── 各銀行設定 ──────────────────────────────────────────────────────────────
BANK_CONFIGS = {
    "esun": {
        "name": "玉山銀行",
        "url": "https://www.esunbank.com/zh-tw/personal/credit-card/intro",
        "wait_for": "body",
        "strategy": "js",
    },
    "cathaybk": {
        # React SPA, cathaybk → cathay-cube 轉址後卡名在 hashed-class div
        "name": "國泰世華銀行",
        "url": "https://www.cathaybk.com.tw/cathaybk/personal/credit-card/",
        "wait_for": "body",
        "strategy": "js",
    },
    "fubon": {
        "name": "台北富邦銀行",
        "url": "https://www.fubon.com/banking/personal/credit_card/all_card/all_card.htm",
        "wait_for": "body",
        "strategy": "js",
    },
    "taishin": {
        "name": "台新銀行",
        "url": "https://www.taishinbank.com.tw/TSB/personal/credit/intro/overview/",
        "wait_for": "body",
        "strategy": "js",
    },
    "sinopac": {
        # 原 href_part "/bankcard/" 不存在,改 js 全頁掃
        "name": "永豐銀行",
        "url": "https://bank.sinopac.com/sinopacBT/personal/credit-card/introduction/list.html",
        "wait_for": "body",
        "strategy": "js",
    },
    "yuanta": {
        # 正確路徑:雙層 creditCard (cardList.do 不存在會 500)
        # 卡片詳細頁 pattern: /bank/creditCard/creditCard/in.do?id=XXX
        "name": "元大銀行",
        "url": "https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do",
        "fallback_url": "https://www.yuantabank.com.tw/bank/creditCard/index.do",
        "wait_for": "body",
        "strategy": "href",
        "href_part": "/creditCard/in.do",
    },
    "kgi": {
        # 原 href 抓到「了解更多」連結文字 → 改 js,卡名在 h3
        "name": "凱基銀行",
        "url": "https://www.kgibank.com.tw/zh-tw/personal/credit-card/list",
        "wait_for": "body",
        "strategy": "js",
    },
    "dbs": {
        "name": "星展銀行",
        "url": "https://www.dbs.com.tw/personal-zh/cards/dbs-credit-cards/default.page",
        "fallback_url": "https://www.dbs.com.tw/personal-zh/cards/default.page",
        "wait_for": "body",
        "strategy": "js",
    },
    "hsbc": {
        "name": "滙豐銀行",
        "url": "https://www.hsbc.com.tw/credit-cards/",
        "wait_for": "body",
        "strategy": "js",
    },
    "scb": {
        "name": "渣打銀行",
        "url": "https://www.sc.com/tw/credit-cards/",
        "wait_for": "body",
        "strategy": "js",
    },
}


def scrape_bank(page, code: str, cfg: dict, debug: bool = False) -> list[dict]:
    name = cfg["name"]
    urls = [cfg["url"]]
    if "fallback_url" in cfg:
        urls.append(cfg["fallback_url"])

    soup_url = None
    for url in urls:
        log.info(f"開始爬取:{name}({url})")
        try:
            page.goto(url, timeout=60000, wait_until="networkidle")
            soup_url = url
            break
        except PWTimeout:
            log.warning(f"[{name}] networkidle 逾時,改 domcontentloaded")
            try:
                page.goto(url, timeout=40000, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(cfg["wait_for"], timeout=12000)
                except PWTimeout:
                    pass
                soup_url = url
                break
            except Exception as e:
                log.warning(f"[{name}] 載入失敗:{e}")
        except Exception as e:
            log.warning(f"[{name}] 載入失敗:{e}")

    if not soup_url:
        log.error(f"[{name}] 所有 URL 失敗")
        return []

    _scroll_to_bottom(page)
    page.wait_for_timeout(2500)

    if debug:
        page.screenshot(path=f"debug_{code}.png", full_page=True)
        log.info(f"[{name}] 截圖:debug_{code}.png")

    strategy = cfg.get("strategy", "js")
    raw = []

    if strategy == "href":
        href_part = cfg.get("href_part", "")
        try:
            raw = page.evaluate(JS_EXTRACT_HREFS, href_part)
        except Exception as e:
            log.warning(f"[{name}] JS href 抓取失敗:{e}")
        if not raw:
            log.warning(f"[{name}] href 策略未取得卡名,回退 js")
            try:
                raw = page.evaluate(JS_EXTRACT_CARD_NAMES)
            except Exception as e:
                log.warning(f"[{name}] js 抓取失敗:{e}")
    else:
        try:
            raw = page.evaluate(JS_EXTRACT_CARD_NAMES)
        except Exception as e:
            log.warning(f"[{name}] JS 抓取失敗:{e}")

    log.debug(f"[{name}] JS 回傳 {len(raw)} 筆")
    if raw and log.isEnabledFor(10):
        log.debug(f"[{name}] 前 5 筆樣本:{[r['text'] for r in raw[:5]]}")

    names = [r["text"] for r in raw]
    hrefs = {r["text"]: r.get("href", soup_url) for r in raw}
    valid = NoiseFilter.dedupe([n for n in names if NoiseFilter.is_valid(n)])

    records = [
        make_record(
            bank_name=name, bank_code=code, card_name=cn,
            highlights=[], apply_url=hrefs.get(cn, soup_url) or soup_url,
            source=soup_url,
        )
        for cn in valid
    ]
    log.info(f"  ✅ {name}:{len(records)} 張(JS回傳 {len(raw)} → 有效 {len(valid)})")
    return records


def _scroll_to_bottom(page, steps: int = 10):
    """捲到底兩輪,確保 lazy-load / carousel 都被觸發。"""
    for i in range(steps):
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/steps})")
        page.wait_for_timeout(400)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    for i in range(steps):
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/steps})")
        page.wait_for_timeout(300)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)


def run(bank_filter=None, output=None, headless=True, debug=False):
    all_codes = list(BANK_CONFIGS.keys()) + ["ctbc"]

    if bank_filter:
        if bank_filter not in all_codes:
            log.error(f"未知代碼:{bank_filter},可用:{', '.join(all_codes)}")
            return save_csv([], output, "banks")
        run_codes = [bank_filter]
    else:
        run_codes = all_codes

    all_records = []

    if "ctbc" in run_codes:
        all_records.extend(make_ctbc_records())

    browser_codes = [c for c in run_codes if c != "ctbc"]
    if browser_codes:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
                viewport={"width": 1440, "height": 900},
                locale="zh-TW",
            )
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = context.new_page()
            success = 0
            for code in browser_codes:
                cfg = BANK_CONFIGS[code]
                try:
                    records = scrape_bank(page, code, cfg, debug=debug)
                    if records:
                        success += 1
                    all_records.extend(records)
                except Exception as e:
                    log.error(f"[{cfg['name']}] 爬取錯誤:{e}")
                time.sleep(2)
            browser.close()
        log.info(f"📊 瀏覽器:{success}/{len(browser_codes)} 家成功")

    log.info(f"📊 總計 {len(all_records)} 張")

    if output is None:
        output = "banks.csv"
    df = save_csv(all_records, output, "banks")
    log.info(f"✅ 儲存:{output}({len(df)} 筆)")
    return df


if __name__ == "__main__":
    all_codes = list(BANK_CONFIGS.keys()) + ["ctbc"]
    ap = argparse.ArgumentParser(description="各銀行官網爬蟲 v9")
    ap.add_argument("--bank", help=f"銀行代碼:{', '.join(all_codes)}")
    ap.add_argument("--output", default="banks.csv", help="輸出 CSV (預設 banks.csv)")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.debug:
        log.setLevel("DEBUG")

    df = run(
        bank_filter=args.bank,
        output=args.output,
        headless=not args.show,
        debug=args.debug,
    )
    print(f"\n📊 共 {len(df)} 張卡片")
    if not df.empty:
        print(df.groupby("銀行名稱")["卡片名稱"].count().to_string())
        print("\n範例:")
        print(df.head(20)[["銀行名稱", "卡片名稱"]].to_string(index=False))