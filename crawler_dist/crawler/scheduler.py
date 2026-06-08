# -*- coding: utf-8 -*-
"""
crawler/scheduler.py — 每晚 21:00 自動爬蟲 + 爬完自動清理
======================================================================
本檔把「分散式爬蟲(producer/worker)」與「資料清理(clean_credit_cards.py)」
串成一條每晚自動執行的流程。排程器本身只做「派工 → 等待 → 清理」三步,
實際爬蟲仍在常駐 worker 上平行執行(沿用既有架構,不重造輪子)。

每天 21:00(Asia/Taipei)觸發一次,流程:
  ① 派工 dispatch_all()
     沿用 crawler/producer_*.py:先「清空」三張原始表各一次,再把
     PTT / banks / card_stats 任務送進 RabbitMQ 佇列,由 worker 消費。
  ② 等待 wait_until_idle()
     輪詢「RabbitMQ 佇列深度」+「Celery inspect 進行中任務」,
     直到三個佇列清空且沒有 worker 正在跑任務 → 判定爬完。
  ③ 清理 run_cleaning()
     執行 clean_credit_cards.main():讀原始表 → 清理/特徵工程 →
     寫入 *_clean 與 dashboard_agg(原始表不動)。

設計原則:
  - 清空只在派工時做一次(沿用 producer),worker 全程 append,避免互相清空。
  - 等待採「佇列深度 + 進行中任務」雙重判定,並要求連續多次閒置才收工,
    避免 worker 還沒接手就被誤判為「爬完」。
  - 任一階段失敗只記 log、不讓排程器整個崩潰,下一晚會再跑一輪。

環境變數(皆有預設值):
  CRAWL_HOUR / CRAWL_MINUTE        每天觸發時間,預設 21 / 0
  RUN_ON_START                     設 1 → 容器啟動後立即先跑一輪(方便測試),預設 0
  WAIT_TIMEOUT_SEC                 等待爬完的逾時上限(秒),預設 10800(3 小時)
  POLL_INTERVAL_SEC                輪詢間隔(秒),預設 20
  IDLE_CONFIRM                     需連續幾次判定閒置才算爬完,預設 3
  RABBITMQ_HOST / _ACCOUNT / _PASSWORD ...   broker 連線(派工 + 監控佇列)
  MYSQL_HOST / _PORT / _DB / _ACCOUNT / _USER / _PASSWORD   建表 + 清理
    註:db_common 讀 MYSQL_ACCOUNT、clean_credit_cards 讀 MYSQL_USER,
        部署時兩者請設成相同值(見 docker-compose-card-scheduler.yml)。

啟動(由 compose 覆寫):
  python -m crawler.scheduler
"""
import os
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from crawler.worker import app

# 三個來源對應的佇列名稱(對齊 crawler/worker.py 的 task_routes)
QUEUES = ["ptt", "banks", "card_stats"]


def _env_int(name: str, default: int) -> int:
    """讀整數型環境變數,格式錯誤就退回預設值。"""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── ① 派工 ────────────────────────────────────────────────────────────
def dispatch_all() -> None:
    """沿用三個 producer:清空對應原始表一次 + 派工到三個佇列。"""
    # 延遲匯入:避免排程器一啟動就連 DB / 連網(只在真正要派工時才載入)
    from crawler import producer_card_stats, producer_banks, producer_ptt

    logger.info("① 開始派工(清空原始表一次 → 任務送進佇列)")
    # 先派較短的 stats / banks,最後派最長的 ptt;三者在不同佇列上由 worker 平行跑
    for name, mod in (
        ("card_stats", producer_card_stats),
        ("banks", producer_banks),
        ("ptt", producer_ptt),
    ):
        try:
            mod.main()
            logger.info(f"  ✔ {name} 派工完成")
        except Exception as e:  # 單一來源失敗不影響其他來源
            logger.exception(f"  ✗ {name} 派工失敗:{e}")
    logger.info("① 派工結束")


# ── ② 等待爬完 ─────────────────────────────────────────────────────────
def _queue_ready_counts() -> dict:
    """回傳 {佇列名: 佇列中待處理(ready)訊息數};佇列不存在/查詢失敗視為 0。

    每個佇列用獨立連線做 passive 查詢,避免 passive declare 失敗時
    讓共用 channel 失效而影響其他佇列。
    """
    counts = {}
    for q in QUEUES:
        try:
            with app.connection_for_read() as conn:
                ch = conn.channel()
                res = ch.queue_declare(queue=q, passive=True)  # 只查詢不建立
                counts[q] = int(getattr(res, "message_count", 0))
        except Exception:
            counts[q] = 0  # 佇列尚未建立(沒派過工)或查詢失敗 → 視為 0
    return counts


def _busy_task_count() -> int:
    """worker 上 active + reserved 的任務數;若沒有任何 worker 回應回傳 -1。

    prefetch_multiplier=1 之下,大量任務仍排在 broker 佇列(不在 reserved),
    所以「進行中任務數」只計 worker 已抓走的部分,需搭配佇列深度一起判斷。
    """
    insp = app.control.inspect(timeout=5)
    try:
        if not (insp.ping() or {}):
            return -1  # 沒有 worker 在線/回應
        active = insp.active() or {}
        reserved = insp.reserved() or {}
        return (sum(len(v) for v in active.values())
                + sum(len(v) for v in reserved.values()))
    except Exception:
        return -1


def wait_until_idle() -> None:
    """輪詢直到「佇列清空 + 無進行中任務」連續達標,或逾時。"""
    timeout = _env_int("WAIT_TIMEOUT_SEC", 3 * 3600)
    interval = _env_int("POLL_INTERVAL_SEC", 20)
    need_confirm = max(1, _env_int("IDLE_CONFIRM", 3))

    logger.info(
        f"② 等待爬蟲完成(逾時 {timeout}s、每 {interval}s 輪詢、"
        f"需連續 {need_confirm} 次閒置才收工)"
    )
    start = time.time()
    idle_streak = 0       # 連續判定為閒置的次數
    seen_work = False     # 是否曾偵測到有工作(避免 worker 還沒接手就誤判)
    no_worker_warned = False

    while True:
        elapsed = int(time.time() - start)
        if elapsed > timeout:
            logger.warning(
                f"② 等待逾時({elapsed}s)→ 仍進入清理,請事後檢查 worker / 佇列狀態"
            )
            return

        ready = _queue_ready_counts()
        ready_total = sum(ready.values())
        busy = _busy_task_count()

        if ready_total > 0 or busy > 0:
            seen_work = True

        # 沒有 worker 在線時提醒一次:任務會卡在佇列無人消費
        if busy == -1 and ready_total > 0 and not no_worker_warned:
            logger.warning("② 偵測不到線上 worker,但佇列仍有任務,請確認 worker 是否在跑")
            no_worker_warned = True

        # 「閒置」= 佇列全空且沒有 worker 正在跑任務(busy 必須確切為 0)
        all_idle = (ready_total == 0) and (busy == 0)
        idle_streak = idle_streak + 1 if (all_idle and seen_work) else 0

        logger.info(
            f"  輪詢 t={elapsed}s 佇列ready={ready} 進行中={busy} "
            f"閒置連續={idle_streak}/{need_confirm}"
        )

        if idle_streak >= need_confirm:
            logger.info("② 判定爬蟲已完成(佇列清空 + 無進行中任務)")
            return

        # 從未偵測到任何工作 + 過了寬限期 → 視為「這輪沒新工作」,直接清理
        if (all_idle and not seen_work
                and elapsed >= max(60, interval * 2)):
            logger.warning("② 從未偵測到任務(可能派工失敗或無新工作)→ 直接進入清理")
            return

        time.sleep(interval)


# ── ③ 資料清理 ─────────────────────────────────────────────────────────
def run_cleaning() -> None:
    """執行 clean_credit_cards.main():原始表 → 清理 → *_clean / dashboard_agg。"""
    logger.info("③ 開始資料清理 clean_credit_cards.py")
    try:
        import clean_credit_cards  # 頂層模組,鏡像內 /app(PYTHONPATH=/app)
        clean_credit_cards.main()
        logger.info("③ 資料清理完成 → *_clean / dashboard_agg 已更新")
    except SystemExit:
        raise
    except Exception as e:
        logger.exception(f"③ 資料清理失敗(原始表未受影響):{e}")


# ── 每晚排程主流程 ─────────────────────────────────────────────────────
def nightly_job() -> None:
    """串起三步:派工 → 等待爬完 → 清理。"""
    logger.info("==================== 每晚排程開始 ====================")
    t0 = time.time()
    try:
        dispatch_all()
        wait_until_idle()
        run_cleaning()
    except Exception as e:  # 保險:整段包起來,絕不讓排程器掛掉
        logger.exception(f"排程執行發生未預期錯誤:{e}")
    finally:
        logger.info(
            f"==================== 排程結束(耗時 {int(time.time() - t0)}s) ===================="
        )


def main() -> None:
    hour = _env_int("CRAWL_HOUR", 21)
    minute = _env_int("CRAWL_MINUTE", 0)

    # 背景排程器,時區 Asia/Taipei
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(
        id="nightly_crawl_and_clean",
        func=nightly_job,
        trigger="cron",
        hour=str(hour),         # 每天 21 點
        minute=str(minute),     # 整點 0 分
        day_of_week="*",        # 每天
        coalesce=True,          # 錯過的排程只補跑一次
        max_instances=1,        # 同時只允許一個實例(上一輪沒跑完不重疊啟動)
        misfire_grace_time=3600,  # 容器剛重啟等情況,1 小時內補跑
    )
    logger.info(
        f"已註冊每日排程:每天 {hour:02d}:{minute:02d}(Asia/Taipei)"
        f" 爬蟲 → 等爬完 → 資料清理"
    )

    scheduler.start()
    logger.info("排程器已啟動,常駐等待中…")

    # RUN_ON_START=1:容器一起來就先跑一輪(部署後不想等到晚上才驗證時很方便)
    if os.getenv("RUN_ON_START", "0") == "1":
        logger.info("RUN_ON_START=1 → 啟動後立即先跑一輪")
        nightly_job()

    # 主執行緒保持存活,背景排程器才不會跟著退出
    try:
        while True:
            time.sleep(600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("收到結束訊號,關閉排程器…")
        scheduler.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
