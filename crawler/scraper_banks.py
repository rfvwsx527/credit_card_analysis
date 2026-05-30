"""
各銀行官網爬蟲 (scraper_banks.py) — Playwright
====================================================
v10 (2026-05)

相對 v9 變更:
1. 中信由 hardcode 改為動態爬取
   URL: /content/twrbo/zh_tw/cc_index/cc_product/cc_introduction_index.html
2. JS 擷取器同時取每張卡的「亮點」(bullets / 含特徵詞短句)
3. Python 用 keyword 對卡名 + 亮點分類成「類別」
   分類: 現金回饋 / 哩程 / LINE Pay/Points / 紅利點數 / 聯名卡 /
        電商/購物聯名卡 / 旅遊卡 / 頂級卡 / 簽帳金融卡 / 一般卡

如果輸出 CSV 沒看到「類別」欄,代表 card_common.py 的 COLUMNS 未含
「類別」字串,請補上即可顯示。
"""

import argparse
import time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from card_common import (
    COLUMNS, NoiseFilter, make_record, save_csv, setup_logger,
)

log = setup_logger("scraper_banks", "scraper_banks.log")


# ─── 卡名 + 亮點 同步擷取 JS (js 策略用) ─────────────────────────────────────

JS_EXTRACT_CARDS_WITH_HIGHLIGHTS = r"""
() => {
    // 共用工具
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
        '無限卡','鈦金卡','白金卡','金卡','普卡','虛擬卡','實體卡','數位卡',
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
    const featRegex = /[％%]|回饋|優惠|紅利|哩程|加碼|首刷|贈|累積|享|點數|分期|無限|新戶|機場|貴賓|現金|消費|刷卡|滿額|無上限/;

    // 階段 1: 找所有卡名葉子節點 (+ img alt)
    const cardEls = [];
    for (const el of document.querySelectorAll('*')) {
        let containerLike = false;
        for (const c of el.children) {
            const ct = (c.textContent || '').trim();
            if (ct.length > 0 && !inlineTags.has(c.tagName)) {
                containerLike = true;
                break;
            }
        }
        if (containerLike) continue;
        const txt = ((el.innerText || el.textContent || '') + '').trim();
        if (!looksLikeCard(txt)) continue;
        if (denyExact.has(txt)) continue;
        if (denyInclude.some(k => txt.includes(k))) continue;
        if ((txt.match(/[、，。！？:：；]/g) || []).length >= 2) continue;
        cardEls.push({el, name: txt});
    }
    for (const img of document.querySelectorAll('img[alt]')) {
        const alt = (img.alt || '').trim();
        if (!looksLikeCard(alt)) continue;
        if (denyExact.has(alt)) continue;
        if (denyInclude.some(k => alt.includes(k))) continue;
        cardEls.push({el: img, name: alt});
    }

    // 去重 (保留第一個出現的元素)
    const seenName = new Set();
    const uniq = [];
    for (const c of cardEls) {
        if (seenName.has(c.name)) continue;
        seenName.add(c.name);
        uniq.push(c);
    }
    const allNames = new Set(uniq.map(c => c.name));

    // 階段 2: 為每張卡找最小 container,從中抓亮點
    const results = [];
    for (const card of uniq) {
        // 由葉節點往上找,找到最小、不含其他卡名的 ancestor
        let container = card.el;
        let parent = container.parentElement;
        let depth = 0;
        while (parent && depth < 8) {
            let hasOther = false;
            for (const e of parent.querySelectorAll('*')) {
                if (e === card.el) continue;
                const t = ((e.innerText || e.textContent || '') + '').trim();
                if (t !== card.name && allNames.has(t)) { hasOther = true; break; }
            }
            if (hasOther) break;
            container = parent;
            parent = parent.parentElement;
            depth++;
        }

        const highlights = [];
        const seenHl = new Set();
        const tryAdd = (raw) => {
            if (!raw) return;
            const clean = raw.trim();
            if (!clean || clean === card.name) return;
            if (seenHl.has(clean)) return;
            if (clean.length < 4 || clean.length > 80) return;
            if (/[\r\n\t]/.test(clean)) return;
            if (allNames.has(clean)) return;
            seenHl.add(clean);
            highlights.push(clean);
        };

        // 優先取 <li> (官網最常見的 bullet 結構)
        for (const li of container.querySelectorAll('li')) {
            if (highlights.length >= 6) break;
            let hasChildList = false;
            for (const c of li.children) {
                if (c.tagName === 'UL' || c.tagName === 'OL') { hasChildList = true; break; }
            }
            if (hasChildList) continue;
            tryAdd(((li.innerText || li.textContent || '') + '').trim());
        }

        // 補充: 含特徵詞的 <p>/<span>/<div> 葉節點
        if (highlights.length < 3) {
            for (const el of container.querySelectorAll('p, span, div')) {
                if (highlights.length >= 6) break;
                let hasBlockChild = false;
                for (const c of el.children) {
                    if (inlineTags.has(c.tagName)) continue;
                    const ct = (c.textContent || '').trim();
                    if (ct) { hasBlockChild = true; break; }
                }
                if (hasBlockChild) continue;
                const t = ((el.innerText || el.textContent || '') + '').trim();
                if (!featRegex.test(t)) continue;
                tryAdd(t);
            }
        }

        const aEl = card.el.closest ? card.el.closest('a') : null;
        results.push({
            text: card.name,
            href: aEl ? aEl.href : '',
            highlights: highlights
        });
    }
    return results;
}
"""


# ─── href 策略 JS (元大用) — 也回傳 highlights ──────────────────────────────

JS_EXTRACT_HREFS_WITH_HIGHLIGHTS = r"""
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
        '信用卡','銀行卡','聯名卡','其他卡','所有卡','卡片','一張卡',
        '熱門推薦卡','世界卡/無限卡','簽帳金融卡','頂級卡','聯名認同卡',
        '比較信用卡','所有信用卡','我的卡','熱門卡','聯名/認同卡','停發卡',
        '採購卡','卡卡','卡','無限卡','鈦金卡','白金卡','金卡','普卡',
    ]);
    const inlineTags = new Set([
        'STRONG','EM','SPAN','I','B','U','BR','SMALL','SUB','SUP','MARK','FONT'
    ]);
    const featRegex = /[％%]|回饋|優惠|紅利|哩程|加碼|首刷|贈|累積|享|點數|分期|無限|新戶|機場|貴賓|現金|消費|刷卡|滿額|無上限/;

    const candidates = [];
    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        if (!href.includes(hrefPart)) continue;

        const texts = [];
        const at = ((a.innerText || a.textContent || '') + '').trim();
        if (at) texts.push(at);
        if (a.title) texts.push(a.title.trim());
        const al = a.getAttribute('aria-label');
        if (al) texts.push(al.trim());
        for (const h of a.querySelectorAll('h1,h2,h3,h4,h5,h6,p,span,strong')) {
            const t = ((h.innerText || h.textContent || '') + '').trim();
            if (t) texts.push(t);
        }
        for (const img of a.querySelectorAll('img[alt]')) {
            const alt = (img.alt || '').trim();
            if (alt) texts.push(alt);
        }
        let p = a.parentElement;
        for (let d = 0; d < 3 && p; d++) {
            for (const h of p.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
                const t = ((h.innerText || h.textContent || '') + '').trim();
                if (t) texts.push(t);
            }
            p = p.parentElement;
        }

        let name = null;
        for (const t of texts) {
            if (looksLikeCard(t) && !denyExact.has(t)) { name = t; break; }
        }
        if (!name) continue;
        candidates.push({a, name});
    }

    const seen = new Set();
    const cards = [];
    for (const c of candidates) {
        if (seen.has(c.name)) continue;
        seen.add(c.name);
        cards.push(c);
    }
    const allNames = new Set(cards.map(c => c.name));

    const results = [];
    for (const card of cards) {
        let container = card.a;
        let parent = container.parentElement;
        let depth = 0;
        while (parent && depth < 8) {
            let hasOther = false;
            for (const e of parent.querySelectorAll('*')) {
                const t = ((e.innerText || e.textContent || '') + '').trim();
                if (t !== card.name && allNames.has(t)) { hasOther = true; break; }
            }
            if (hasOther) break;
            container = parent;
            parent = parent.parentElement;
            depth++;
        }

        const highlights = [];
        const seenHl = new Set();
        const tryAdd = (raw) => {
            if (!raw) return;
            const clean = raw.trim();
            if (!clean || clean === card.name) return;
            if (seenHl.has(clean)) return;
            if (clean.length < 4 || clean.length > 80) return;
            if (/[\r\n\t]/.test(clean)) return;
            if (allNames.has(clean)) return;
            seenHl.add(clean);
            highlights.push(clean);
        };

        for (const li of container.querySelectorAll('li')) {
            if (highlights.length >= 6) break;
            let hasChildList = false;
            for (const c of li.children) {
                if (c.tagName === 'UL' || c.tagName === 'OL') { hasChildList = true; break; }
            }
            if (hasChildList) continue;
            tryAdd(((li.innerText || li.textContent || '') + '').trim());
        }
        if (highlights.length < 3) {
            for (const el of container.querySelectorAll('p, span, div')) {
                if (highlights.length >= 6) break;
                let hasBlockChild = false;
                for (const c of el.children) {
                    if (inlineTags.has(c.tagName)) continue;
                    const ct = (c.textContent || '').trim();
                    if (ct) { hasBlockChild = true; break; }
                }
                if (hasBlockChild) continue;
                const t = ((el.innerText || el.textContent || '') + '').trim();
                if (!featRegex.test(t)) continue;
                tryAdd(t);
            }
        }

        results.push({
            text: card.name,
            href: card.a.href,
            highlights: highlights
        });
    }
    return results;
}
"""


# ─── 類別分類 (Python) ──────────────────────────────────────────────────────

def classify_category(card_name: str, highlights: list[str]) -> str:
    """根據卡名 + 亮點 keyword 對應到類別"""
    name = card_name or ''
    text = name + ' ' + ' '.join(highlights or [])
    nlow = name.lower()

    # 簽帳金融卡 (最先判斷,避免被聯名卡蓋掉)
    if any(k in name for k in ['簽帳金融', '金融卡', '簽帳金融卡', '金融信用卡', '簽金']):
        return '簽帳金融卡'
    if 'debit' in nlow:
        return '簽帳金融卡'

    # 頂級卡:結尾「無限卡」+ 鼎極/世界至尊 等
    if any(k in name for k in ['鼎極', '世界之極', '世界至尊', '無限世界', '極致', '尊榮無限']):
        return '頂級卡'
    if 'infinite' in nlow:
        return '頂級卡'
    if name.endswith('無限卡') and name not in ('無限卡',):
        return '頂級卡'

    # 哩程 (卡名提到航空、哩程相關)
    if any(k in name for k in ['哩程', '航空', '萬里通', '長榮', '中華航', '華航', '星宇',
                                'ANA', '哩數', '飛行', '亞洲萬里', 'KrisFlyer']):
        return '哩程'
    if 'mile' in nlow or 'asia miles' in nlow:
        return '哩程'
    if any(k in text for k in ['累積哩程', '兌換哩程', '哩程兌換', '飛行哩']):
        return '哩程'

    # LINE
    if 'line' in nlow:
        return 'LINE Pay/Points'
    if 'LINE Points' in text or 'LINE Pay' in text or 'LINE POINTS' in text:
        return 'LINE Pay/Points'

    # 現金回饋 (卡名直接帶)
    if '現金回饋' in name or 'cashback' in nlow or 'cash back' in nlow:
        return '現金回饋'

    # 紅利點數
    if any(k in name for k in ['紅利', '點數']):
        return '紅利點數'

    # 聯名卡 (細分電商/購物)
    if '聯名' in name or '聯名認同' in name:
        ecomm = ['Costco', '蝦皮', 'foodpanda', '街口', 'momo', 'PChome',
                 'uniopen', 'SOGO', 'Yahoo', '全聯', '統一', '家樂福', '誠品',
                 '寶雅', '康是美', '屈臣氏', 'agoda', 'Agoda']
        if any(k in name for k in ecomm):
            return '電商/購物聯名卡'
        return '聯名卡'

    # ⭐ 從亮點推:%回饋 → 現金回饋 (要在旅遊之前判斷)
    if '%回饋' in text or '％回饋' in text or '現金回饋' in text:
        return '現金回饋'

    # 旅遊 (亮點有機場/貴賓室/旅平險等)
    if any(k in text for k in ['機場接送', '貴賓室', '旅平險', '旅遊不便險']):
        return '旅遊卡'

    return '一般卡'


# ─── BANK_CONFIGS ───────────────────────────────────────────────────────────
# 中信納入 BANK_CONFIGS,移除原本的 hardcode 路徑

BANK_CONFIGS = {
    "ctbc": {
        # 中信:所有卡片介紹頁 (JS 渲染,Playwright 才能取到內容)
        "name": "中國信託銀行",
        "url": "https://www.ctbcbank.com/content/twrbo/zh_tw/cc_index/cc_product/cc_introduction_index.html",
        "fallback_url": "https://www.ctbcbank.com/content/twrbo/zh_tw/cc_index/cc_product/cc_hot.html",
        "wait_for": "body",
        "strategy": "js",
    },
    "esun": {
        "name": "玉山銀行",
        "url": "https://www.esunbank.com/zh-tw/personal/credit-card/intro",
        "wait_for": "body",
        "strategy": "js",
    },
    "cathaybk": {
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
        "name": "永豐銀行",
        "url": "https://bank.sinopac.com/sinopacBT/personal/credit-card/introduction/list.html",
        "wait_for": "body",
        "strategy": "js",
    },
    "yuanta": {
        # 元大正確路徑:雙層 creditCard
        "name": "元大銀行",
        "url": "https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do",
        "fallback_url": "https://www.yuantabank.com.tw/bank/creditCard/index.do",
        "wait_for": "body",
        "strategy": "href",
        "href_part": "/creditCard/in.do",
    },
    "kgi": {
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


def _build_record(*, bank_name, bank_code, card_name, highlights, apply_url, source):
    """make_record 包裝:追加類別欄。COLUMNS 若沒有「類別」會被丟棄,需自行補。"""
    rec = make_record(
        bank_name=bank_name, bank_code=bank_code,
        card_name=card_name, highlights=highlights,
        apply_url=apply_url, source=source,
    )
    if isinstance(rec, dict):
        rec['類別'] = classify_category(card_name, highlights)
    return rec


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
            raw = page.evaluate(JS_EXTRACT_HREFS_WITH_HIGHLIGHTS, href_part)
        except Exception as e:
            log.warning(f"[{name}] JS href 抓取失敗:{e}")
        if not raw:
            log.warning(f"[{name}] href 策略未取得卡名,回退 js")
            try:
                raw = page.evaluate(JS_EXTRACT_CARDS_WITH_HIGHLIGHTS)
            except Exception as e:
                log.warning(f"[{name}] js 抓取失敗:{e}")
    else:
        try:
            raw = page.evaluate(JS_EXTRACT_CARDS_WITH_HIGHLIGHTS)
        except Exception as e:
            log.warning(f"[{name}] JS 抓取失敗:{e}")

    log.debug(f"[{name}] JS 回傳 {len(raw)} 筆")
    if raw and log.isEnabledFor(10):
        sample = [(r['text'], r.get('highlights', [])[:2]) for r in raw[:3]]
        log.debug(f"[{name}] 前 3 筆樣本:{sample}")

    # 以 NoiseFilter 過濾無效卡名 + 去重 (保留原順序)
    valid_names = NoiseFilter.dedupe(
        [r["text"] for r in raw if NoiseFilter.is_valid(r["text"])]
    )
    valid_set = set(valid_names)
    by_name = {}
    for r in raw:
        if r["text"] in valid_set and r["text"] not in by_name:
            by_name[r["text"]] = r

    records = []
    for cn in valid_names:
        r = by_name.get(cn, {})
        records.append(_build_record(
            bank_name=name, bank_code=code, card_name=cn,
            highlights=r.get("highlights", []) or [],
            apply_url=r.get("href") or soup_url,
            source=soup_url,
        ))

    log.info(f"  ✅ {name}:{len(records)} 張(JS回傳 {len(raw)} → 有效 {len(records)})")
    return records


def _scroll_to_bottom(page, steps: int = 10):
    """捲到底兩輪確保 lazy-load / carousel 都觸發。"""
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
    all_codes = list(BANK_CONFIGS.keys())

    if bank_filter:
        if bank_filter not in all_codes:
            log.error(f"未知代碼:{bank_filter},可用:{', '.join(all_codes)}")
            return save_csv([], output, "banks")
        run_codes = [bank_filter]
    else:
        run_codes = all_codes

    all_records = []

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
        for code in run_codes:
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
    log.info(f"📊 完成:{success}/{len(run_codes)} 家成功")

    log.info(f"📊 總計 {len(all_records)} 張")

    if output is None:
        output = "banks.csv"
    df = save_csv(all_records, output, "banks")
    log.info(f"✅ 儲存:{output}({len(df)} 筆)")
    return df


if __name__ == "__main__":
    all_codes = list(BANK_CONFIGS.keys())
    ap = argparse.ArgumentParser(description="各銀行官網爬蟲 v10")
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
        cols = [c for c in ["銀行名稱", "卡片名稱", "類別", "亮點"] if c in df.columns]
        if not cols:
            cols = list(df.columns)[:4]
        print(df.head(15)[cols].to_string(index=False))