"""
PTT 信用卡版 (creditcard) 爬蟲
爬取 2024 年至今所有文章的基本資訊與內文，輸出為 CSV

使用方式：
    uv pip install requests beautifulsoup4 pandas
    python ptt_credit_card_crawler.py

輸出：
    ../crawler_data/ptt_credit_card.csv
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import re
import os
import logging
from datetime import datetime

# ── 設定 ────────────────────────────────────────────────────────────────────
BOARD = "creditcard"
BASE_URL = "https://www.ptt.cc"
START_YEAR = 2024          # 只保留這年（含）之後的文章
OUTPUT_DIR = "../crawler_data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "ptt_credit_card.csv")
REQUEST_DELAY = 0.4        # 每次請求間隔秒數（請勿設定過低，避免對伺服器造成負擔）
MAX_RETRIES = 3            # 請求失敗最多重試次數
BATCH_SIZE = 100           # 每累積多少筆寫入一次 CSV

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.ptt.cc/bbs/creditcard/index.html",
})
SESSION.cookies.set("over18", "1")   # PTT 18禁看板需要此 cookie

CSV_COLUMNS = ["title", "category", "author", "pub_time", "date_display",
               "push_count", "url", "content"]


# ── 工具函式 ─────────────────────────────────────────────────────────────────
def fetch(url: str) -> BeautifulSoup | None:
    """帶重試機制的 GET，回傳 BeautifulSoup 或 None。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.RequestException as e:
            logger.warning(f"第 {attempt} 次請求失敗：{url}  錯誤：{e}")
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt * 2)
    return None


def flush_to_csv(records: list[dict], is_first_batch: bool) -> None:
    """將一批資料用 pandas 寫入（或追加）CSV。"""
    df = pd.DataFrame(records, columns=CSV_COLUMNS)
    mode = "w" if is_first_batch else "a"
    header = is_first_batch
    df.to_csv(OUTPUT_FILE, mode=mode, header=header,
              index=False, encoding="utf-8-sig")


def get_latest_index() -> int:
    """取得最新的看板索引頁編號。"""
    soup = fetch(f"{BASE_URL}/bbs/{BOARD}/index.html")
    if not soup:
        raise RuntimeError("無法取得看板首頁")

    # PTT 上方分頁列：找 class="btn wide" 且文字含「上頁」的連結
    for a in soup.select("a.btn.wide"):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if "上頁" in text or "Prev" in text:
            m = re.search(r"index(\d+)\.html", href)
            if m:
                # 「上頁」指向 N-1，所以最新頁是 N-1+1 = N
                return int(m.group(1)) + 1

    # 備援：從所有 index 連結找最大值
    all_links = soup.find_all("a", href=re.compile(r"index\d+\.html"))
    nums = []
    for a in all_links:
        m = re.search(r"index(\d+)", a.get("href", ""))
        if m:
            nums.append(int(m.group(1)))
    return max(nums) + 1 if nums else 1


def safe_text(parent, selector: str) -> str:
    """從 parent 中以 CSS selector 取得文字，找不到回傳空字串。"""
    tag = parent.select_one(selector)
    return tag.get_text(strip=True) if tag else ""


# ── 爬蟲核心 ─────────────────────────────────────────────────────────────────
def crawl_index_page(page_num: int) -> list[dict]:
    """爬取一頁看板文章列表，回傳「有效」文章基本資訊列表（已過濾刪文）。"""
    url = f"{BASE_URL}/bbs/{BOARD}/index{page_num}.html"
    soup = fetch(url)
    if not soup:
        return []

    articles = []
    for row in soup.select("div.r-ent"):
        title_tag = row.select_one("div.title a")
        if not title_tag:
            # 已刪除文章 → 直接略過，不浪費後續請求
            continue

        title = title_tag.get_text(strip=True)
        post_url = BASE_URL + title_tag["href"]
        author = safe_text(row, "div.author")
        date_str = safe_text(row, "div.date")
        push_count = safe_text(row, "div.nrec span") or "0"

        category_match = re.match(r"\[(.+?)\]", title)
        category = category_match.group(1) if category_match else ""

        articles.append({
            "title": title,
            "url": post_url,
            "author": author,
            "date": date_str,
            "push_count": push_count,
            "category": category,
        })
    return articles


def fetch_post_content(url: str) -> tuple[str, str | None]:
    """爬取單篇文章內文與發文時間，回傳 (內文, 'YYYY-MM-DD HH:MM:SS' 或 None)。"""
    if not url:
        return "", None

    soup = fetch(url)
    if not soup:
        return "", None

    pub_time = None
    for span in soup.select("span.article-meta-value"):
        text = span.get_text(strip=True)
        # PTT 時間格式：Wed Jan  1 12:00:00 2024
        m = re.search(
            r"(\w{3})\s+(\w{3})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4})", text
        )
        if m:
            try:
                pub_time = datetime.strptime(
                    f"{m.group(3)} {m.group(2)} {m.group(5)} {m.group(4)}",
                    "%d %b %Y %H:%M:%S"
                )
            except ValueError:
                pass
            break

    main_content = soup.select_one("div#main-content")
    if not main_content:
        return "", pub_time.strftime("%Y-%m-%d %H:%M:%S") if pub_time else None

    for tag in main_content.select(
        "div.article-metaline, div.article-metaline-right, div.push, span.f2"
    ):
        tag.decompose()

    content = main_content.get_text("\n", strip=True)
    sig_idx = content.find("\n--\n")
    if sig_idx != -1:
        content = content[:sig_idx]

    time_str = pub_time.strftime("%Y-%m-%d %H:%M:%S") if pub_time else None
    return content.strip(), time_str


# ── 主程式 ───────────────────────────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    logger.info(f"開始爬取 PTT {BOARD} 版，目標：{START_YEAR} 年至今")
    logger.info(f"輸出路徑：{OUTPUT_FILE}")

    latest_page = get_latest_index()
    logger.info(f"最新索引頁：{latest_page}")

    batch: list[dict] = []
    total_saved = 0
    is_first_batch = True
    consecutive_old_pages = 0   # 連續整頁過舊的頁數，連續 2 頁則停止

    for page_num in range(latest_page, 0, -1):
        logger.info(f"正在處理索引頁 {page_num}/{latest_page} …")
        articles = crawl_index_page(page_num)

        if not articles:
            time.sleep(REQUEST_DELAY)
            continue

        page_had_valid_article = False
        page_had_old_article = False

        for art in articles:
            content, pub_time_str = fetch_post_content(art["url"])
            time.sleep(REQUEST_DELAY)

            # 若拿不到 pub_time（網路問題 / 文章格式異常），跳過該篇，不影響停止判斷
            if not pub_time_str:
                logger.warning(f"  無法取得發文時間，略過：{art['url']}")
                continue

            year = int(pub_time_str[:4])

            if year < START_YEAR:
                page_had_old_article = True
                continue   # 跳過該篇但繼續檢查同頁其他文章（保險）

            page_had_valid_article = True

            batch.append({
                "title":        art["title"],
                "category":     art["category"],
                "author":       art["author"],
                "pub_time":     pub_time_str,
                "date_display": art["date"],
                "push_count":   art["push_count"],
                "url":          art["url"],
                "content":      content,
            })
            total_saved += 1

            if len(batch) >= BATCH_SIZE:
                flush_to_csv(batch, is_first_batch)
                is_first_batch = False
                batch.clear()
                logger.info(f"  已儲存 {total_saved} 篇文章")

        # 停止策略：整頁都沒有 START_YEAR 之後的文章，且至少出現過舊文，連續 2 頁則停止
        if not page_had_valid_article and page_had_old_article:
            consecutive_old_pages += 1
            logger.info(f"  整頁皆為 {START_YEAR} 年以前文章（連續 {consecutive_old_pages} 頁）")
            if consecutive_old_pages >= 2:
                logger.info("  連續 2 頁皆過舊，停止爬取。")
                break
        else:
            consecutive_old_pages = 0

        time.sleep(REQUEST_DELAY)

    # 寫入剩餘資料
    if batch:
        flush_to_csv(batch, is_first_batch)

    logger.info(f"爬取完成！共儲存 {total_saved} 篇文章 → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
