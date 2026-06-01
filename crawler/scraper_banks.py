"""
各銀行官網爬蟲 (scraper_banks.py) — Playwright
====================================================
v12 (2026-05)

架構:
1. 中信永遠用 ctbc_cards.csv (因 WAF 防護,動態爬無法穩定取得)
2. 其他銀行用 Playwright 動態爬,domcontentloaded 等載入
3. js/href 兩種抓取策略,加 skip 區塊 (nav/header/footer/sidebar)
4. 詳細頁 fallback:列表頁亮點空時才進詳細頁補
5. 元大有分頁:用點擊頁碼按鈕逐頁抓
6. CSV 預設輸出到 ../crawler_data/banks.csv,自動建資料夾

如果輸出 CSV 沒看到「類別」欄,代表 card_common.py 的 COLUMNS 未含
「類別」字串,請補上即可顯示。
"""

import argparse
import random
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from card_common import (
    COLUMNS, NoiseFilter, make_record, save_csv, setup_logger,
)

log = setup_logger("scraper_banks", "scraper_banks.log")

# 預設輸出路徑:相對 script 位置,放到專案的 crawler_data/ 子目錄
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR.parent / "crawler_data" / "banks.csv"

# 寫入 MySQL 的資料表名稱 (None 則不寫 DB,只存 CSV)
DB_TABLE = "bank_cards"


# 中信清單:由 ctbc_cards.py 讀取 ctbc_cards.csv (直接編輯 CSV 即可)
# v13:import 整個模組,執行時才讀「最新」清單 (而非啟動時快照),
#      並可呼叫 sync_from_found() 把動態抓到的新卡寫回 CSV。
try:
    import ctbc_cards
    CTBC_FALLBACK_CARDS = ctbc_cards.CTBC_CARDS  # 啟動快照 (相容舊變數名)
except ImportError:
    ctbc_cards = None
    CTBC_FALLBACK_CARDS = []
    log.warning("找不到 ctbc_cards.py,中信後備清單將為空")

# 中信動態爬取用的卡片列表頁 (預設不啟用,需加 --ctbc-dynamic)。
# 中信有 WAF(APP-1053),動態常被擋;抓到就把新卡寫回 CSV,抓不到就沿用 CSV。
# 若官網改版,只要改這個 URL 即可。
CTBC_CARD_LIST_URL = "https://www.ctbcbank.com/twrbo/zh_tw/cc_index/cc_cardall.html"


# ─── 卡名 + 亮點 同步擷取 JS (js 策略用) ─────────────────────────────────────

JS_EXTRACT_CARDS_WITH_HIGHLIGHTS = r"""
() => {
    // 共用工具
    // 剝尾端括號補述: ( ) （ ） 【 】 [ ]
    const stripTail = (s) => {
        let t = (s || '').trim();
        for (let i = 0; i < 3; i++) {
            const before = t;
            t = t.replace(/[\s\u3000]*[\(（【\[][^\)）】\]]{0,30}[\)）】\]][\s\u3000]*$/, '').trim();
            if (t === before) break;
        }
        return t;
    };
    // 正規化卡名:剝前後箭頭/符號/多餘空白,給最終輸出與比對用
    const normalizeName = (s) => {
        let t = (s || '').replace(/[\u200b\u00a0]/g, ' ').trim();
        // 剝尾端箭頭 / 符號 / "立即申請" "了解更多" 等
        t = t.replace(/[\s\u3000>›»▸▶◦・·＞]+$/g, '').trim();
        t = t.replace(/[\s\u3000]*(立即申請|立即申辦|馬上申辦|了解更多|瞭解更多|更多介紹|查看詳情|詳細介紹|看更多)[\s\u3000]*$/g, '').trim();
        // 剝尾端「- 已停發 / – 停發 / — 已停售」等狀態說明
        t = t.replace(/[\s\u3000]*[\-－–—‐][\s\u3000]*(已停發|停發|已停售|停售|已停止|停止申辦|已暫停)[\s\u3000]*$/g, '').trim();
        // 剝開頭符號 / 箭頭
        t = t.replace(/^[\s\u3000<‹«◂◀＜]+/g, '').trim();
        return t;
    };
    const looksLikeCard = (txt) => {
        if (!txt) return false;
        let t = normalizeName(txt);
        if (t.length < 3 || t.length > 35) return false;
        if (/[\r\n\t]/.test(t)) return false;
        const core = stripTail(t);
        if (core.length < 3) return false;
        return core.endsWith('卡') || core.endsWith('Card') || core.endsWith('card');
    };
    const denyExact = new Set([
        '信用卡','銀行卡','聯名卡','其他卡','所有卡','卡片','一張卡','一卡',
        '熱門推薦卡','世界卡/無限卡','簽帳金融卡','聯名認同卡',
        '比較信用卡','所有信用卡','我的卡','熱門卡','聯名/認同卡','分類卡',
        '採購卡','行動支付卡','企業/採購卡','現金儲值卡','停發卡','整併卡',
        '比較卡','卡卡','卡','回饋卡','分期卡','信用卡卡',
        '虛擬卡','實體卡','數位卡','認同卡','學生卡','女性卡',
    ]);
    const denyInclude = [
        '掛失','補發','辦卡進度','卡片管理','繳款','帳單','信用卡服務',
        '常見問題','卡別','分類標籤','線上辦卡','請選擇您想要的服務',
        '更多介紹','立即申辦','瞭解更多','了解更多','禮遇專區','立即辦卡',
        '卡片總覽','尋找適合','信用卡介紹',
        // 區塊標題語 (會以「卡」結尾但其實是標題,需排除)
        '申請','推薦的信用卡','最受歡迎','受歡迎的信用卡','精選','嚴選',
        '為您推薦','幫您篩選','適合您的','選擇您','哪一張','哪張',
        '比較信用卡','信用卡比較','所有信用卡','全部信用卡','探索',
        // 升級/併入說明文字 (國泰常見)
        '已於','並於','升級為','更名為','併入','整併為','改名為',
        // 圖檔/規格殘留
        'Icon/','70x70','px ','px,','px、',
    ];
    // 動詞開頭的雜物 (按鈕/動作而非卡名),如「申辦凱基信用卡」「我要辦卡」「換發多幣卡」
    const denyStartsWith = [
        '申辦','我要','換發','前往','查詢','立即','馬上','按此','點此',
        '前往申辦','點擊',
    ];
    const inlineTags = new Set([
        'STRONG','EM','SPAN','I','B','U','BR','SMALL','SUB','SUP','MARK','FONT'
    ]);
    const featRegex = /[％%]|回饋|優惠|紅利|哩程|哩|加碼|首刷|贈|累積|享|點數|分期|無限|新戶|機場|貴賓|現金|消費|刷卡|滿額|無上限|停車|接送|禮遇|免費|權益|保險|折抵|回贈|年費|道路救援|分期0利率|0利率/;

    // 階段 1: 找所有卡名葉子節點 (+ img alt)
    // 找出要排除的根節點 (nav/header/footer/sidebar 等),避免把選單文字當卡名/亮點
    // 跳過導覽/側邊/頁尾根節點,避免選單文字被當卡名/亮點。
    // 用精準 token 比對 (class~="nav"),避免誤殺 "card-navigation"/"navbar-cards" 等含卡片內容的容器。
    const skipSelectors = [
        'nav', 'header', 'footer', 'aside',
        '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
        // class 整個 token 等於這些 (空白分隔)
        '[class~="nav"]', '[class~="menu"]', '[class~="sidebar"]', '[class~="header"]',
        '[class~="footer"]', '[class~="breadcrumb"]', '[class~="breadcrumbs"]',
        '[class~="navbar"]', '[class~="navigation"]', '[class~="side-nav"]',
        '[class~="main-nav"]', '[class~="top-nav"]', '[class~="global-nav"]',
        '[class~="sub-nav"]', '[class~="subnav"]', '[class~="submenu"]',
        '[class~="left-nav"]', '[class~="right-nav"]', '[class~="page-nav"]',
        '[class~="category-nav"]', '[class~="category-menu"]', '[class~="category-list"]',
        '[class~="page-menu"]', '[class~="local-nav"]',
        '[class~="cookie-banner"]', '[class~="cookie-notice"]',
        '[id="nav"]', '[id="menu"]', '[id="sidebar"]', '[id="header"]', '[id="footer"]',
        '[id="navbar"]', '[id="navigation"]', '[id="breadcrumb"]',
        '[id~="sidebar"]', '[id~="leftnav"]', '[id~="rightnav"]',
    ];
    const skipRoots = new Set();
    for (const sel of skipSelectors) {
        try { for (const el of document.querySelectorAll(sel)) skipRoots.add(el); } catch (e) {}
    }
    const isInSkip = (el) => {
        let n = el;
        while (n) {
            if (skipRoots.has(n)) return true;
            n = n.parentElement;
        }
        return false;
    };

    const cardEls = [];
    const debugDenied = [];  // 被 deny 規則濾掉的候選 (debug 用)
    for (const el of document.querySelectorAll('*')) {
        if (isInSkip(el)) continue;   // 跳過導覽/側邊/頁尾區內的元素
        let containerLike = false;
        for (const c of el.children) {
            const ct = (c.textContent || '').trim();
            if (ct.length > 0 && !inlineTags.has(c.tagName)) {
                containerLike = true;
                break;
            }
        }
        if (containerLike) continue;
        const rawTxt = ((el.innerText || el.textContent || '') + '').trim();
        if (!looksLikeCard(rawTxt)) continue;
        const txt = normalizeName(rawTxt);
        if (denyExact.has(txt)) { debugDenied.push(txt + ' [denyExact]'); continue; }
        if (denyInclude.some(k => txt.includes(k))) {
            const k = denyInclude.find(k => txt.includes(k));
            debugDenied.push(txt + ' [denyInclude:' + k + ']');
            continue;
        }
        if (denyStartsWith.some(k => txt.startsWith(k))) {
            const k = denyStartsWith.find(k => txt.startsWith(k));
            debugDenied.push(txt + ' [denyStartsWith:' + k + ']');
            continue;
        }
        if ((txt.match(/[、，。！？:：；]/g) || []).length >= 2) {
            debugDenied.push(txt + ' [punct]');
            continue;
        }
        cardEls.push({el, name: txt});
    }
    for (const img of document.querySelectorAll('img[alt]')) {
        if (isInSkip(img)) continue;
        const rawAlt = (img.alt || '').trim();
        if (!looksLikeCard(rawAlt)) continue;
        const alt = normalizeName(rawAlt);
        if (denyExact.has(alt)) { debugDenied.push('[img]'+alt+' [denyExact]'); continue; }
        if (denyInclude.some(k => alt.includes(k))) {
            const k = denyInclude.find(k => alt.includes(k));
            debugDenied.push('[img]'+alt+' [denyInclude:'+k+']');
            continue;
        }
        if (denyStartsWith.some(k => alt.startsWith(k))) {
            const k = denyStartsWith.find(k => alt.startsWith(k));
            debugDenied.push('[img]'+alt+' [denyStartsWith:'+k+']');
            continue;
        }
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
                const t = normalizeName(((e.innerText || e.textContent || '') + '').trim());
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
            // 換行/多空白 → 單一空格 (不再因含換行整條丟棄)
            let clean = (raw + '').replace(/\s+/g, ' ').trim();
            if (!clean || clean === card.name) return;
            if (normalizeName(clean) === card.name) return;
            if (seenHl.has(clean)) return;
            if (clean.length < 4 || clean.length > 80) return;
            if (allNames.has(normalizeName(clean))) return;
            if (/^(了解更多|更多介紹|立即申辦|立即申請|詳細介紹|看更多|前往|查看)/.test(clean)) return;
            seenHl.add(clean);
            highlights.push(clean);
        };

        // 來源 1: <li> bullet
        for (const li of container.querySelectorAll('li')) {
            if (highlights.length >= 6) break;
            let hasChildList = false;
            for (const c of li.children) {
                if (c.tagName === 'UL' || c.tagName === 'OL') { hasChildList = true; break; }
            }
            if (hasChildList) continue;
            tryAdd(li.innerText || li.textContent || '');
        }

        // 來源 2: 含特徵詞的 <p>/<span>/<div>/<dd>/<td> 葉節點 (允許含 <br>)
        if (highlights.length < 3) {
            for (const el of container.querySelectorAll('p, span, div, dd, td')) {
                if (highlights.length >= 6) break;
                let hasBlockChild = false;
                for (const c of el.children) {
                    if (inlineTags.has(c.tagName) || c.tagName === 'BR') continue;
                    const ct = (c.textContent || '').trim();
                    if (ct) { hasBlockChild = true; break; }
                }
                if (hasBlockChild) continue;
                const t = ((el.innerText || el.textContent || '') + '').replace(/\s+/g, ' ').trim();
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
    return { results: results, denied: debugDenied };
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
    const normalizeName = (s) => {
        let t = (s || '').replace(/[\u200b\u00a0]/g, ' ').trim();
        t = t.replace(/[\s\u3000>›»▸▶◦・·＞]+$/g, '').trim();
        t = t.replace(/[\s\u3000]*(立即申請|立即申辦|馬上申辦|了解更多|瞭解更多|更多介紹|查看詳情|詳細介紹|看更多)[\s\u3000]*$/g, '').trim();
        // 剝尾端「- 已停發 / – 停發 / — 已停售」等狀態說明
        t = t.replace(/[\s\u3000]*[\-－–—‐][\s\u3000]*(已停發|停發|已停售|停售|已停止|停止申辦|已暫停)[\s\u3000]*$/g, '').trim();
        t = t.replace(/^[\s\u3000<‹«◂◀＜]+/g, '').trim();
        return t;
    };
    const looksLikeCard = (txt) => {
        if (!txt) return false;
        let t = normalizeName(txt);
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
        '現金回饋卡','哩程卡','一般卡','御璽卡','晶緻卡','世界卡','商務卡',
        '認同卡','銀行卡','悠遊卡','一卡通',
    ]);
    const denyInclude = [
        '掛失','補發','辦卡進度','卡片管理','繳款','帳單','信用卡服務',
        '常見問題','卡別','線上辦卡','更多介紹','立即申辦','瞭解更多','了解更多','立即辦卡',
        '申請我們','最受歡迎','受歡迎的信用卡','推薦的信用卡','信用卡比較',
        // 升級/併入說明文字
        '已於','並於','升級為','更名為','併入','整併為','改名為',
        // 圖檔/規格殘留
        'Icon/','70x70','px ','px,','px、',
    ];
    // 動詞開頭的雜物 (按鈕/動作而非卡名)
    const denyStartsWith = [
        '申辦','我要','換發','前往','查詢','立即','馬上','按此','點此',
        '前往申辦','點擊',
    ];
    const inlineTags = new Set([
        'STRONG','EM','SPAN','I','B','U','BR','SMALL','SUB','SUP','MARK','FONT'
    ]);
    const featRegex = /[％%]|回饋|優惠|紅利|哩程|哩|加碼|首刷|贈|累積|享|點數|分期|無限|新戶|機場|貴賓|現金|消費|刷卡|滿額|無上限|停車|接送|禮遇|免費|權益|保險|折抵|回贈|年費|道路救援|分期0利率|0利率/;

    // 跳過 nav/header/footer/sidebar (元大左側選單有 "所有卡片"/"頂級卡" 等假連結會誤判)
    // 跳過導覽/側邊/頁尾根節點,避免選單文字被當卡名/亮點。
    // 用精準 token 比對 (class~="nav"),避免誤殺 "card-navigation"/"navbar-cards" 等含卡片內容的容器。
    const skipSelectors = [
        'nav', 'header', 'footer', 'aside',
        '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
        // class 整個 token 等於這些 (空白分隔)
        '[class~="nav"]', '[class~="menu"]', '[class~="sidebar"]', '[class~="header"]',
        '[class~="footer"]', '[class~="breadcrumb"]', '[class~="breadcrumbs"]',
        '[class~="navbar"]', '[class~="navigation"]', '[class~="side-nav"]',
        '[class~="main-nav"]', '[class~="top-nav"]', '[class~="global-nav"]',
        '[class~="sub-nav"]', '[class~="subnav"]', '[class~="submenu"]',
        '[class~="left-nav"]', '[class~="right-nav"]', '[class~="page-nav"]',
        '[class~="category-nav"]', '[class~="category-menu"]', '[class~="category-list"]',
        '[class~="page-menu"]', '[class~="local-nav"]',
        '[class~="cookie-banner"]', '[class~="cookie-notice"]',
        '[id="nav"]', '[id="menu"]', '[id="sidebar"]', '[id="header"]', '[id="footer"]',
        '[id="navbar"]', '[id="navigation"]', '[id="breadcrumb"]',
        '[id~="sidebar"]', '[id~="leftnav"]', '[id~="rightnav"]',
    ];
    const skipRoots = new Set();
    for (const sel of skipSelectors) {
        try { for (const el of document.querySelectorAll(sel)) skipRoots.add(el); } catch (e) {}
    }
    const isInSkip = (el) => {
        let n = el;
        while (n) {
            if (skipRoots.has(n)) return true;
            n = n.parentElement;
        }
        return false;
    };

    const candidates = [];
    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.getAttribute('href') || '';
        if (!href.includes(hrefPart)) continue;
        if (isInSkip(a)) continue;

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
            if (!looksLikeCard(t)) continue;
            const nm = normalizeName(t);
            if (denyExact.has(nm)) continue;
            if (denyInclude.some(k => nm.includes(k))) continue;
            if (denyStartsWith.some(k => nm.startsWith(k))) continue;
            name = nm;
            break;
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
                const t = normalizeName(((e.innerText || e.textContent || '') + '').trim());
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
            let clean = (raw + '').replace(/\s+/g, ' ').trim();
            if (!clean || clean === card.name) return;
            if (normalizeName(clean) === card.name) return;
            if (seenHl.has(clean)) return;
            if (clean.length < 4 || clean.length > 80) return;
            if (allNames.has(normalizeName(clean))) return;
            if (/^(了解更多|更多介紹|立即申辦|立即申請|詳細介紹|看更多|前往|查看)/.test(clean)) return;
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
            tryAdd(li.innerText || li.textContent || '');
        }
        if (highlights.length < 3) {
            for (const el of container.querySelectorAll('p, span, div, dd, td')) {
                if (highlights.length >= 6) break;
                let hasBlockChild = false;
                for (const c of el.children) {
                    if (inlineTags.has(c.tagName) || c.tagName === 'BR') continue;
                    const ct = (c.textContent || '').trim();
                    if (ct) { hasBlockChild = true; break; }
                }
                if (hasBlockChild) continue;
                const t = ((el.innerText || el.textContent || '') + '').replace(/\s+/g, ' ').trim();
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

_PCT_FEEDBACK_RE = re.compile(r'[%％]\s*回饋')


def classify_category(card_name: str, highlights: list[str]) -> str:
    """根據卡名 + 亮點 keyword 對應到類別"""
    name = card_name or ''
    # 剝除尾端括號補述 (邀請制)/(停發)/【已停發】 等,供結尾比對用
    name_core = re.sub(
        r'[\s\u3000]*[\(（【\[][^\)）】\]]{0,30}[\)）】\]][\s\u3000]*$', '', name).strip()
    text = name + ' ' + ' '.join(highlights or [])
    nlow = name.lower()

    # 簽帳金融卡 (最先判斷,避免被聯名卡蓋掉)
    if any(k in name for k in ['簽帳金融', '金融卡', '簽帳金融卡', '金融信用卡', '簽金']):
        return '簽帳金融卡'
    if 'debit' in nlow:
        return '簽帳金融卡'

    # 頂級卡:結尾「無限卡」(剝括號後) + 鼎極/世界至尊 等
    if any(k in name for k in ['鼎極', '世界之極', '世界至尊', '無限世界', '極致', '尊榮無限']):
        return '頂級卡'
    if 'infinite' in nlow:
        return '頂級卡'
    if name_core.endswith('無限卡') and name_core != '無限卡':
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

    # ⭐ 從亮點推:%回饋 → 現金回饋 (容忍 % 與「回饋」間的空白,放在旅遊之前)
    if _PCT_FEEDBACK_RE.search(text) or '現金回饋' in text:
        return '現金回饋'

    # 旅遊 (亮點有機場/貴賓室/旅平險等)
    if any(k in text for k in ['機場接送', '貴賓室', '旅平險', '旅遊不便險']):
        return '旅遊卡'

    return '一般卡'


# ─── BANK_CONFIGS ───────────────────────────────────────────────────────────
# 中信納入 BANK_CONFIGS,移除原本的 hardcode 路徑

BANK_CONFIGS = {
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
        "detail_fallback": True,   # 列表頁亮點空的卡,進詳細頁補抓
        "detail_limit": 40,
    },
    "yuanta": {
        # 元大:list.do 卡片清單為 AJAX 動態載入,需等 in.do 連結出現
        # 卡片詳細頁 pattern: /bank/creditCard/creditCard/in.do?id=XXX
        # 有分頁 (1/2/3/4),先試 click 頁碼,失敗則改 URL 分頁
        "name": "元大銀行",
        "url": "https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do",
        "fallback_urls": [
            "https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do?creditcard_type=1",
            "https://www.yuantabank.com.tw/bank/creditCard/index.do",
        ],
        "wait_for": "a[href*='/creditCard/in.do']",
        "wait_for_optional": True,
        "strategy": "href",
        "href_part": "/creditCard/in.do",
        "paginate": True,
        "max_pages": 6,
        # URL 分頁 fallback:當 click 失敗時,改用 URL 直接導航
        # {p} 會被換成頁碼。元大常見參數名:currentPage、p、pageNo
        "paginate_url_template": "https://www.yuantabank.com.tw/bank/creditCard/creditCard/list.do?currentPage={p}",
        "detail_fallback": True,
        "detail_limit": 60,
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


def _is_discontinued(card_name: str, highlights: list[str]) -> bool:
    """判斷是否為停發卡 (卡名或亮點含停發字樣)"""
    text = (card_name or '') + ' ' + ' '.join(highlights or [])
    return any(k in text for k in ['停發', '已停止', '停止申辦', '停止發卡', '已停售', '停售'])


def _build_record(*, bank_name, bank_code, card_name, highlights, apply_url, source):
    """make_record 包裝:追加「類別」「狀態」欄。
    COLUMNS 若沒有這兩欄會被 save_csv 丟棄,需在 card_common.py 補上。"""
    rec = make_record(
        bank_name=bank_name, bank_code=bank_code,
        card_name=card_name, highlights=highlights,
        apply_url=apply_url, source=source,
    )
    if isinstance(rec, dict):
        rec['類別'] = classify_category(card_name, highlights)
        rec['狀態'] = '停發' if _is_discontinued(card_name, highlights) else '發行中'
    return rec


def _ctbc_current_cards() -> list:
    """取得中信「最新」清單 (而非啟動快照)。
    有 ctbc_cards 模組就回它目前的 CTBC_CARDS,否則回啟動快照。"""
    if ctbc_cards is not None:
        return ctbc_cards.CTBC_CARDS
    return CTBC_FALLBACK_CARDS


def _ctbc_fallback_records(name: str, code: str) -> list[dict]:
    """中信:用 ctbc_cards.csv 清單產生 records (動態未啟用或失敗時的來源)"""
    records = []
    for cn, url, hl in _ctbc_current_cards():
        records.append(_build_record(
            bank_name=name, bank_code=code, card_name=cn,
            highlights=hl, apply_url=url, source=url,
        ))
    return records


def _scrape_ctbc_dynamic(page, name: str, code: str, debug: bool = False) -> list[dict]:
    """嘗試動態爬中信官網。成功抓到卡 → 呼叫 ctbc_cards.sync_from_found()
    把新卡寫回 CSV,再用合併後的最新清單產生 records;
    抓取被擋/失敗 → 回傳 None,讓呼叫端 fallback 回 CSV 清單。"""
    cfg = {
        "name": name,
        "url": CTBC_CARD_LIST_URL,
        "wait_for": "body",
        "strategy": "js",
    }
    try:
        records = scrape_bank(page, code, cfg, debug=debug)
    except Exception as e:
        log.warning(f"[{name}] 動態爬取例外:{e}")
        records = []

    # 把動態抓到的卡 (卡名/連結/亮點) 整理成 sync 需要的格式
    found = []
    for r in records:
        if not isinstance(r, dict):
            continue
        hl = [r.get(f"回饋亮點{i}", "") for i in (1, 2, 3)]
        found.append((r.get("卡片名稱", ""), r.get("申辦連結", ""),
                      [h for h in hl if h]))

    if ctbc_cards is None:
        log.warning(f"[{name}] 無 ctbc_cards 模組,無法同步,改用啟動快照")
        return records or None

    # 交給 ctbc_cards 比對 + 寫回 (內含 MIN_FOUND 保護:過少自動跳過不寫)
    report = ctbc_cards.sync_from_found(found, write=True, logger=log)
    if report.get("skipped"):
        # 被 WAF 擋 / 抓太少 → 回 None,呼叫端改用現有 CSV 清單
        return None

    # 用合併後的最新清單重建 records,確保輸出含這次新增的卡
    return _ctbc_fallback_records(name, code)


def _human_pause(page, lo=1000, hi=2500):
    """隨機停頓,模擬人類閱讀"""
    try:
        page.wait_for_timeout(random.randint(lo, hi))
    except Exception:
        pass


def _human_mouse(page):
    """隨機滑鼠移動,降低行為指紋"""
    try:
        for _ in range(random.randint(2, 4)):
            x = random.randint(100, 1300)
            y = random.randint(100, 800)
            page.mouse.move(x, y, steps=random.randint(3, 8))
            page.wait_for_timeout(random.randint(120, 400))
    except Exception:
        pass


def scrape_bank(page, code: str, cfg: dict, debug: bool = False) -> list[dict]:
    name = cfg["name"]
    # 蒐集所有要嘗試的 URL
    urls = [cfg["url"]]
    if "fallback_url" in cfg:
        urls.append(cfg["fallback_url"])
    if "fallback_urls" in cfg:
        urls.extend(cfg["fallback_urls"])

    referer = cfg.get("referer")

    soup_url = None
    wait_sel = cfg.get("wait_for", "body")
    wait_optional = cfg.get("wait_for_optional", False)

    for url in urls:
        log.info(f"開始爬取:{name}({url})")
        # 用 domcontentloaded:銀行頁有大量追蹤碼/廣告/lazy-load,永遠到不了 networkidle,
        # DOM 載完就先抓,真正要等的東西交給後面的 wait_for_selector + scroll。
        nav_kwargs = {"timeout": 30000, "wait_until": "domcontentloaded"}
        if referer:
            nav_kwargs["referer"] = referer
        try:
            page.goto(url, **nav_kwargs)
        except PWTimeout:
            log.warning(f"[{name}] domcontentloaded 逾時")
            continue
        except Exception as e:
            log.warning(f"[{name}] 載入失敗:{e}")
            continue

        # 人類化:停頓 + 滑鼠移動,順便給 JS 一點時間執行
        _human_pause(page, 1500, 2800)
        _human_mouse(page)

        # 等待目標 selector
        if wait_sel and wait_sel != "body":
            try:
                page.wait_for_selector(wait_sel, timeout=15000)
                log.debug(f"[{name}] 等到 selector: {wait_sel}")
            except PWTimeout:
                if not wait_optional:
                    log.warning(f"[{name}] 等不到 {wait_sel}")

        page.wait_for_timeout(1000)
        soup_url = url
        break

    if not soup_url:
        log.error(f"[{name}] 所有 URL 載入失敗")
        return []

    _scroll_to_bottom(page)
    page.wait_for_timeout(1500)

    if debug:
        try:
            # 短 timeout + 不等字型 (animations=disabled 順便加快)
            page.screenshot(path=f"debug_{code}.png", full_page=True,
                            timeout=15000, animations="disabled")
            log.info(f"[{name}] 截圖:debug_{code}.png")
        except Exception as e:
            # full_page 失敗常見原因:字型 CDN 慢、頁面過長。改截 viewport 救一下
            log.warning(f"[{name}] full_page 截圖失敗 ({e.__class__.__name__}),改截可視範圍")
            try:
                page.screenshot(path=f"debug_{code}.png",
                                timeout=10000, animations="disabled")
                log.info(f"[{name}] 截圖 (viewport):debug_{code}.png")
            except Exception as e2:
                log.warning(f"[{name}] viewport 截圖也失敗,略過:{e2.__class__.__name__}")

    strategy = cfg.get("strategy", "js")
    raw = []
    paginate = cfg.get("paginate", False)
    max_pages = cfg.get("max_pages", 6)

    if strategy == "href":
        href_part = cfg.get("href_part", "")
        try:
            raw = page.evaluate(JS_EXTRACT_HREFS_WITH_HIGHLIGHTS, href_part)
        except Exception as e:
            log.warning(f"[{name}] JS href 抓取失敗:{e}")
        # 分頁:先試 click,失敗試 URL 分頁
        if paginate:
            seen_hrefs = {r.get("href") for r in raw}
            url_template = cfg.get("paginate_url_template")  # 含 {p} 的 URL
            # 元大常見參數名,如果 cfg 給的 template 不行,試這些
            url_param_names = ["currentPage", "page", "p", "pageNo", "pageIndex"]
            for pg in range(2, max_pages + 1):
                page_loaded = False
                # 策略 A: click 頁碼按鈕
                if _click_page_number(page, pg, name):
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except PWTimeout:
                        pass
                    page.wait_for_timeout(2500)
                    page_loaded = True
                # 策略 B: URL 分頁(click 失敗時試)
                if not page_loaded:
                    candidate_urls = []
                    if url_template and "{p}" in url_template:
                        candidate_urls.append(url_template.replace("{p}", str(pg)))
                    # 從目前 url 衍生:基底 url + 不同參數名
                    base = soup_url.split("?")[0]
                    for pname in url_param_names:
                        candidate_urls.append(f"{base}?{pname}={pg}")
                    for cand in candidate_urls:
                        try:
                            page.goto(cand, timeout=20000, wait_until="domcontentloaded")
                            page.wait_for_timeout(2000)
                            page_loaded = True
                            log.debug(f"[{name}] URL 分頁到第 {pg} 頁:{cand}")
                            break
                        except Exception:
                            continue
                if not page_loaded:
                    log.debug(f"[{name}] 第 {pg} 頁無法載入 (click/URL 皆失敗),結束分頁")
                    break

                _scroll_to_bottom(page, steps=5)
                try:
                    page_raw = page.evaluate(JS_EXTRACT_HREFS_WITH_HIGHLIGHTS, href_part)
                except Exception as e:
                    log.warning(f"[{name}] 第 {pg} 頁抓取失敗:{e}")
                    continue
                added = 0
                for r in page_raw:
                    h = r.get("href")
                    if h and h not in seen_hrefs:
                        seen_hrefs.add(h)
                        raw.append(r)
                        added += 1
                log.info(f"[{name}] 第 {pg} 頁新增 {added} 張 (累計 {len(raw)})")
                if added == 0:
                    log.debug(f"[{name}] 第 {pg} 頁無新卡,結束分頁")
                    break
        if not raw:
            log.warning(f"[{name}] href 策略未取得卡名,回退 js")
            try:
                _r = page.evaluate(JS_EXTRACT_CARDS_WITH_HIGHLIGHTS)
                raw = _r.get("results", []) if isinstance(_r, dict) else _r
                if debug and isinstance(_r, dict) and _r.get("denied"):
                    log.info(f"[{name}] 被 deny 過濾的候選 ({len(_r['denied'])} 筆):")
                    for d in _r["denied"][:20]:
                        log.info(f"        - {d}")
            except Exception as e:
                log.warning(f"[{name}] js 抓取失敗:{e}")
    else:
        try:
            _r = page.evaluate(JS_EXTRACT_CARDS_WITH_HIGHLIGHTS)
            raw = _r.get("results", []) if isinstance(_r, dict) else _r
            if debug and isinstance(_r, dict) and _r.get("denied"):
                log.info(f"[{name}] 被 deny 過濾的候選 ({len(_r['denied'])} 筆):")
                for d in _r["denied"][:20]:
                    log.info(f"        - {d}")
        except Exception as e:
            log.warning(f"[{name}] JS 抓取失敗:{e}")

    log.debug(f"[{name}] JS 回傳 {len(raw)} 筆")
    if raw and log.isEnabledFor(10):
        sample = [(r['text'], r.get('highlights', [])[:2]) for r in raw[:3]]
        log.debug(f"[{name}] 前 3 筆樣本:{sample}")

    # 以 NoiseFilter 過濾無效卡名 + 去重
    valid_names = NoiseFilter.dedupe(
        [r["text"] for r in raw if NoiseFilter.is_valid(r["text"])]
    )
    valid_set = set(valid_names)
    by_name = {}
    for r in raw:
        if r["text"] in valid_set and r["text"] not in by_name:
            by_name[r["text"]] = r

    records = []
    metas = []  # 與 records 對齊:(card_name, href, highlights)
    for cn in valid_names:
        r = by_name.get(cn, {})
        hl = r.get("highlights", []) or []
        href = r.get("href") or soup_url
        records.append(_build_record(
            bank_name=name, bank_code=code, card_name=cn,
            highlights=hl, apply_url=href, source=soup_url,
        ))
        metas.append({"card_name": cn, "href": href, "highlights": hl})

    # 詳細頁 fallback:列表頁抓不到亮點 (空) 的卡,且設定允許時,進詳細頁補抓
    if cfg.get("detail_fallback"):
        _fill_highlights_from_detail(
            page, name, code, records, metas, soup_url, cfg)

    log.info(f"  ✅ {name}:{len(records)} 張(JS回傳 {len(raw)} → 有效 {len(records)})")
    return records


# 詳細頁抓亮點:掃整頁找含特徵詞的 li / 短文字節點 (通用,不依賴特定 class)
JS_EXTRACT_DETAIL_HIGHLIGHTS = r"""
() => {
    const featRegex = /[％%]|回饋|優惠|紅利|哩程|哩|加碼|首刷|贈|累積|享|點數|分期|無限|新戶|機場|貴賓|現金|消費|刷卡|滿額|無上限|停車|接送|禮遇|免費|權益|保險|折抵|回贈|道路救援/;
    // 強過濾:導覽/服務性詞,常出現於 menu/sidebar
    const navWords = /常見問題|聯絡|據點|登入|分行|ATM|信用卡服務|信用卡介紹|卡片總覽|信用卡查詢|卡友權益|活動專區|線上申辦|卡片管理|帳單查詢|繳款|掛失|補發|個人服務|數位金融|中小企業|法人企業|信託服務|永續|關於|搜尋|英文|EN|集團|新聞|採購|招募|職涯|徵才|匯率|利率|存款|外匯|貸款|保險|理財|投資|加密|防詐|隱私|宣告|聲明|措施|條款|公告|法定|揭露|消費者保護|友善|無障礙|連結|導覽|協助|交通類權益|國外旅遊|服務與條款|其他權益|點數專區|鑽金會員|現金儲值卡|簽帳金融卡|聯名認同卡|企業.採購卡|行動支付卡|所有卡片|頂級卡|銀行卡|熱門卡|活動優惠及公告|定型化契約|收費標準|分類標籤|個人金融|法人金融|紅利折抵特店|紅利兌換服務|紅利兌換|優惠商店|分期特店|優惠活動|商品優惠|信用卡理財|信用卡產品/;
    const inlineTags = new Set(['STRONG','EM','SPAN','I','B','U','BR','SMALL','SUB','SUP','MARK','FONT']);

    // 跳過導覽/側邊/頁尾根節點 (精準 token 比對,避免誤殺含卡片的容器)
    const skipSelectors = [
        'nav', 'header', 'footer', 'aside',
        '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
        // class 整個 token 等於這些 (空白分隔)
        '[class~="nav"]', '[class~="menu"]', '[class~="sidebar"]', '[class~="header"]',
        '[class~="footer"]', '[class~="breadcrumb"]', '[class~="breadcrumbs"]',
        '[class~="navbar"]', '[class~="navigation"]', '[class~="side-nav"]',
        '[class~="main-nav"]', '[class~="top-nav"]', '[class~="global-nav"]',
        '[class~="sub-nav"]', '[class~="subnav"]', '[class~="submenu"]',
        '[class~="left-nav"]', '[class~="right-nav"]', '[class~="page-nav"]',
        '[class~="category-nav"]', '[class~="category-menu"]', '[class~="category-list"]',
        '[class~="page-menu"]', '[class~="local-nav"]',
        '[class~="cookie-banner"]', '[class~="cookie-notice"]',
        '[id="nav"]', '[id="menu"]', '[id="sidebar"]', '[id="header"]', '[id="footer"]',
        '[id="navbar"]', '[id="navigation"]', '[id="breadcrumb"]',
        '[id~="sidebar"]', '[id~="leftnav"]', '[id~="rightnav"]',
    ];
    const skipRoots = new Set();
    for (const sel of skipSelectors) {
        try {
            for (const el of document.querySelectorAll(sel)) skipRoots.add(el);
        } catch (e) {}
    }
    // 給定節點是否在任何 skipRoot 內 (含自身)
    const isInSkip = (el) => {
        let n = el;
        while (n) {
            if (skipRoots.has(n)) return true;
            n = n.parentElement;
        }
        return false;
    };

    // 鎖定主內容容器:優先 <main>/[role=main]/.content/.main,沒有就用 body
    let root = document.querySelector('main, [role="main"], .main-content, #main-content, .content-main, .product-detail, .credit-card-detail');
    if (!root) root = document.body;
    if (!root) return [];

    const out = [];
    const seen = new Set();
    const add = (raw) => {
        if (out.length >= 6) return;
        let t = (raw + '').replace(/\s+/g, ' ').trim();
        if (!t || t.length < 5 || t.length > 90) return;
        if (seen.has(t)) return;
        if (!featRegex.test(t)) return;
        if (navWords.test(t)) return;
        if (/^(了解更多|更多|立即申辦|立即申請|詳細|看更多|前往|查看|注意事項|適用對象|申辦條件|相關)/.test(t)) return;
        // 排除過多分隔符的句子 (通常是選單列)
        if ((t.match(/[、，。;]/g) || []).length >= 4) return;
        // 短文 (<=8字) 且完全沒標點/數字/英文 → 八成是選單項目 (如「紅利折抵特店」)
        const hasMark = /[、，。：；！？\d%％()（）「」『』+\-\/]/.test(t);
        const hasEnglish = /[a-zA-Z]/.test(t);
        if (t.length <= 8 && !hasMark && !hasEnglish) return;
        seen.add(t);
        out.push(t);
    };

    // 判斷 <ul>/<ol> 是否為「選單樣」list (整個 list 都是短文且互不關聯)
    const isMenuList = (listEl) => {
        const lis = Array.from(listEl.children).filter(c => c.tagName === 'LI');
        if (lis.length < 3) return false;  // 條目少不算選單
        let shortCount = 0;
        let featCount = 0;
        for (const li of lis) {
            const txt = (li.innerText || li.textContent || '').trim();
            if (!txt) continue;
            if (txt.length < 10) shortCount++;
            if (featRegex.test(txt) && !navWords.test(txt)) featCount++;
        }
        // 多數條目極短 (<10字) 且很少含真正特徵詞 → 是選單
        return shortCount >= lis.length * 0.7 && featCount <= 1;
    };

    // 來源 1: 主內容區的 <li>,跳過「選單樣」list 內的條目
    for (const li of root.querySelectorAll('li')) {
        if (out.length >= 6) break;
        if (isInSkip(li)) continue;
        let hasList = false;
        for (const c of li.children) if (c.tagName==='UL'||c.tagName==='OL'){hasList=true;break;}
        if (hasList) continue;
        // 檢查所屬 ul/ol 整體是否為選單樣
        const parentList = li.closest('ul, ol');
        if (parentList && isMenuList(parentList)) continue;
        add(li.innerText || li.textContent || '');
    }
    // 來源 2: 主內容區的 p/div/dd/td/h3/h4 葉節點
    if (out.length < 4) {
        for (const el of root.querySelectorAll('p, div, dd, td, h3, h4')) {
            if (out.length >= 6) break;
            if (isInSkip(el)) continue;
            let hasBlock = false;
            for (const c of el.children) {
                if (inlineTags.has(c.tagName) || c.tagName==='BR') continue;
                if ((c.textContent||'').trim()) { hasBlock = true; break; }
            }
            if (hasBlock) continue;
            add(el.innerText || el.textContent || '');
        }
    }
    return out;
}
"""


def _fill_highlights_from_detail(page, name, code, records, metas, list_url, cfg):
    """對亮點為空的卡,逐一進詳細頁補抓亮點。會明顯變慢,故僅補空的。
    records 與 metas 索引對齊;補到亮點後就地用 _build_record 重建該筆。"""
    idx_empty = [i for i, m in enumerate(metas)
                 if not m["highlights"]
                 and m["href"] and m["href"] != list_url
                 and str(m["href"]).startswith("http")]
    if not idx_empty:
        log.debug(f"[{name}] 無需進詳細頁 (列表頁亮點皆已取得)")
        return
    limit = cfg.get("detail_limit", 40)
    todo = idx_empty[:limit]
    log.info(f"[{name}] {len(idx_empty)} 張亮點為空,進詳細頁補抓 (上限 {limit},實補 {len(todo)})")

    filled = 0
    for n, i in enumerate(todo, 1):
        m = metas[i]
        url = m["href"]
        try:
            page.goto(url, timeout=40000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            hl = page.evaluate(JS_EXTRACT_DETAIL_HIGHLIGHTS)
            if hl:
                # 就地重建該筆 record,確保「亮點」「類別」欄位名與其他筆一致
                records[i] = _build_record(
                    bank_name=name, bank_code=code,
                    card_name=m["card_name"], highlights=hl,
                    apply_url=url, source=url,
                )
                metas[i]["highlights"] = hl
                filled += 1
                log.debug(f"[{name}] ({n}/{len(todo)}) {m['card_name']}: 補到 {len(hl)} 條")
            else:
                log.debug(f"[{name}] ({n}/{len(todo)}) {m['card_name']}: 詳細頁也無亮點")
        except Exception as e:
            log.debug(f"[{name}] 詳細頁失敗 {url}: {e}")
        page.wait_for_timeout(500)
    log.info(f"[{name}] 詳細頁補抓完成:{filled}/{len(todo)} 張補到亮點")


def _click_page_number(page, pg_num: int, name: str) -> bool:
    """嘗試點擊指定頁碼按鈕。回傳是否成功點擊。
    多策略:Playwright locator + JS 在頁面內搜索可點擊元素。"""
    # 策略 1: locator 試常見 selector
    selectors = [
        f'.pagination a:has-text("{pg_num}")',
        f'.page-item:has-text("{pg_num}")',
        f'[class*="paging"] a:has-text("{pg_num}")',
        f'a[data-page="{pg_num}"]',
        f'[aria-label*="第 {pg_num} 頁"]',
        f'[aria-label*="page {pg_num}"]',
        f'a:has-text("{pg_num}")',
        f'button:has-text("{pg_num}")',
    ]
    for sel in selectors:
        try:
            locator = page.locator(sel).filter(has_text=str(pg_num))
            count = locator.count()
            for i in range(min(count, 8)):
                el = locator.nth(i)
                try:
                    txt = (el.inner_text(timeout=1500) or "").strip()
                except Exception:
                    continue
                if txt != str(pg_num):
                    continue
                try:
                    el.scroll_into_view_if_needed(timeout=1500)
                except Exception:
                    pass
                try:
                    el.click(timeout=2500)
                    log.debug(f"[{name}] 點擊第 {pg_num} 頁 (selector)")
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    # 策略 2: JS 在頁面找所有可點擊元素,文字剛好是 pg_num,且像分頁
    js = r"""
    (pgNum) => {
        const candidates = [];
        // 找所有可能是頁碼的元素:a/button/span/li/div 且文字剛好是 pgNum
        for (const el of document.querySelectorAll('a, button, span, li, div')) {
            const t = (el.innerText || el.textContent || '').trim();
            if (t !== String(pgNum)) continue;
            // 太大的元素不是頁碼 (例如整段內容)
            const rect = el.getBoundingClientRect();
            if (rect.width > 100 || rect.height > 80) continue;
            // 必須可視 (有寬高)
            if (rect.width === 0 || rect.height === 0) continue;
            candidates.push(el);
        }
        // 選最有可能是頁碼的:周圍 100px 有兄弟頁碼 (1/2/3 或更多)
        for (const el of candidates) {
            const parent = el.parentElement;
            if (!parent) continue;
            let siblingPgs = 0;
            for (const sib of parent.children) {
                if (sib === el) continue;
                const st = (sib.innerText || sib.textContent || '').trim();
                if (/^\d+$/.test(st) || /上一頁|下一頁|前一頁|後一頁|»|«|<|>/.test(st)) {
                    siblingPgs++;
                }
            }
            if (siblingPgs >= 1) {
                el.scrollIntoView({block:'center'});
                el.click();
                return true;
            }
        }
        return false;
    }
    """
    try:
        ok = page.evaluate(js, pg_num)
        if ok:
            log.debug(f"[{name}] 點擊第 {pg_num} 頁 (JS 兄弟頁碼)")
            return True
    except Exception as e:
        log.debug(f"[{name}] JS 找頁碼失敗:{e}")
    return False


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


def run(bank_filter=None, output=None, headless=True, debug=False,
        ctbc_dynamic=False):
    all_codes = list(BANK_CONFIGS.keys()) + ["ctbc"]

    if bank_filter:
        if bank_filter not in all_codes:
            log.error(f"未知代碼:{bank_filter},可用:{', '.join(all_codes)}")
            out_path = Path(output) if output else DEFAULT_OUTPUT
            out_path.parent.mkdir(parents=True, exist_ok=True)
            return save_csv([], str(out_path), "banks", table=DB_TABLE)
        run_codes = [bank_filter]
    else:
        run_codes = all_codes

    all_records = []
    ctbc_pending = False  # 動態模式下,中信延後到 playwright 區塊處理

    # 中信:預設不跑 Playwright,直接用 ctbc_cards.csv (避開 WAF/APP-1053)。
    # 加 --ctbc-dynamic 時改走動態爬,抓到新卡會寫回 CSV。
    if "ctbc" in run_codes:
        if ctbc_dynamic:
            ctbc_pending = True  # 進 playwright 後再爬,這裡先不移除
            run_codes = [c for c in run_codes if c != "ctbc"]
        else:
            cur = _ctbc_current_cards()
            log.info(f"中國信託銀行:使用 ctbc_cards.csv 清單 ({len(cur)} 張)")
            all_records.extend(_ctbc_fallback_records("中國信託銀行", "ctbc"))
            run_codes = [c for c in run_codes if c != "ctbc"]
            if not run_codes:
                # 只跑中信(靜態)的話直接存檔
                out_path = Path(output) if output else DEFAULT_OUTPUT
                out_path.parent.mkdir(parents=True, exist_ok=True)
                df = save_csv(all_records, str(out_path), "banks", table=DB_TABLE)
                log.info(f"✅ 儲存:{out_path}({len(df)} 筆)")
                return df

    # 動態中信 + 沒有其他銀行要跑:仍需 playwright,不可在此提前 return

    with sync_playwright() as p:
        # 優先嘗試系統真實 Chrome (channel='chrome'),指紋比 bundled Chromium 更乾淨;
        # 環境沒裝 Chrome 時自動 fallback 回 Chromium。
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--start-maximized",
        ]
        browser = None
        used_channel = None
        for channel in ("chrome", None):
            try:
                kwargs = dict(headless=headless, args=launch_args)
                if channel:
                    kwargs["channel"] = channel
                browser = p.chromium.launch(**kwargs)
                used_channel = channel or "chromium(bundled)"
                break
            except Exception as e:
                log.warning(f"啟動 channel={channel} 失敗:{e}")
        if browser is None:
            raise RuntimeError("無法啟動瀏覽器 (chrome 與 chromium 皆失敗)")
        log.info(f"使用瀏覽器:{used_channel}")

        # 關鍵:不偽造 UA 版本。取得 Chromium 真實 UA,只把 Headless 字樣拿掉,
        # 並據此產生「對得上」的 sec-ch-ua client hints,避免 UA/版本矛盾被 WAF 抓。
        tmp_page = browser.new_page()
        real_ua = tmp_page.evaluate("() => navigator.userAgent")
        tmp_page.close()
        ua = real_ua.replace("HeadlessChrome", "Chrome")
        m = re.search(r"Chrome/(\d+)", ua)
        major = m.group(1) if m else "142"
        sec_ch_ua = (f'"Chromium";v="{major}", '
                     f'"Google Chrome";v="{major}", '
                     f'"Not?A_Brand";v="99"')

        context = browser.new_context(
            user_agent=ua,
            viewport={"width": 1440, "height": 900},
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            extra_http_headers={
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": ("text/html,application/xhtml+xml,application/xml;"
                           "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"),
                "sec-ch-ua": sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
        # 強化反偵測:抹除自動化指紋,並補齊真瀏覽器才有的物件
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-TW', 'zh', 'en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => {
                return [
                    {name: 'PDF Viewer'}, {name: 'Chrome PDF Viewer'},
                    {name: 'Chromium PDF Viewer'}, {name: 'Microsoft Edge PDF Viewer'},
                    {name: 'WebKit built-in PDF'}
                ];
            }});
            Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
            Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
            window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
            const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
            if (originalQuery) {
                window.navigator.permissions.query = (params) =>
                    params && params.name === 'notifications'
                        ? Promise.resolve({state: Notification.permission})
                        : originalQuery(params);
            }
            // WebGL vendor/renderer 偽裝成常見硬體
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(p) {
                if (p === 37445) return 'Intel Inc.';
                if (p === 37446) return 'Intel Iris OpenGL Engine';
                return getParameter.call(this, p);
            };
        """)
        page = context.new_page()

        # 中信動態爬取 (--ctbc-dynamic):抓到就 sync 新卡回 CSV;
        # 被 WAF 擋/抓太少 → fallback 回 ctbc_cards.csv 既有清單。
        if ctbc_pending:
            log.info("中國信託銀行:嘗試動態爬取 (--ctbc-dynamic)…")
            try:
                ctbc_recs = _scrape_ctbc_dynamic(
                    page, "中國信託銀行", "ctbc", debug=debug)
            except Exception as e:
                log.error(f"[中國信託銀行] 動態爬取失敗:{e}")
                ctbc_recs = None
            if ctbc_recs is None:
                cur = _ctbc_current_cards()
                log.info(f"中國信託銀行:動態未成功,改用 ctbc_cards.csv ({len(cur)} 張)")
                ctbc_recs = _ctbc_fallback_records("中國信託銀行", "ctbc")
            all_records.extend(ctbc_recs)

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

    # 處理 output 路徑:預設 ../crawler_data/banks.csv,自動建資料夾
    out_path = Path(output) if output else DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = save_csv(all_records, str(out_path), "banks", table=DB_TABLE)
    log.info(f"✅ 儲存:{out_path}({len(df)} 筆)")
    return df


if __name__ == "__main__":
    all_codes = list(BANK_CONFIGS.keys()) + ["ctbc"]
    ap = argparse.ArgumentParser(description="各銀行官網爬蟲 v13")
    ap.add_argument("--bank", help=f"銀行代碼:{', '.join(all_codes)}")
    ap.add_argument("--output", default=None,
                    help=f"輸出 CSV (預設 {DEFAULT_OUTPUT})")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--ctbc-dynamic", action="store_true",
                    dest="ctbc_dynamic",
                    help="嘗試動態爬中信(預設用 ctbc_cards.csv);"
                         "抓到新卡會自動寫回 CSV,被擋則沿用 CSV")
    args = ap.parse_args()

    if args.debug:
        log.setLevel("DEBUG")

    df = run(
        bank_filter=args.bank,
        output=args.output,
        headless=not args.show,
        debug=args.debug,
        ctbc_dynamic=args.ctbc_dynamic,
    )
    print(f"\n📊 共 {len(df)} 張卡片")
    if not df.empty:
        print(df.groupby("銀行名稱")["卡片名稱"].count().to_string())
        print("\n範例:")
        cols = [c for c in ["銀行名稱", "卡片名稱", "類別", "亮點"] if c in df.columns]
        if not cols:
            cols = list(df.columns)[:4]
        print(df.head(15)[cols].to_string(index=False))