"""
合併工具 (merge.py)
====================
把兩支爬蟲的 CSV 合併成一份。
- 以「銀行代碼 + 卡片名稱」為鍵去重
- 官網資料 (banks) 優先，roo.cash 補充官網沒抓到的卡片
- 標記每筆資料來自哪個來源

使用方式：
    python merge.py banks_202605.csv roocash_202605.csv
    python merge.py banks_202605.csv roocash_202605.csv --output merged.csv
"""

import argparse
import pandas as pd
from datetime import datetime

from card_common import COLUMNS, setup_logger

log = setup_logger("merge", "merge.log")


def _norm_card_key(name: str) -> str:
    """正規化卡名作為比對鍵（去空白、統一大小寫）"""
    return "".join(str(name).split()).lower()


def merge(banks_csv: str, roocash_csv: str, output: str | None = None) -> pd.DataFrame:
    df_bank = pd.read_csv(banks_csv, encoding="utf-8-sig")
    df_roo = pd.read_csv(roocash_csv, encoding="utf-8-sig")
    log.info(f"官網資料 {len(df_bank)} 筆，roo.cash 資料 {len(df_roo)} 筆")

    # 標記來源
    df_bank = df_bank.copy()
    df_roo = df_roo.copy()
    df_bank["來源標記"] = "官網"
    df_roo["來源標記"] = "roo.cash"

    # 建立官網已有的卡片鍵集合
    bank_keys = set(
        zip(df_bank["銀行代碼"].astype(str),
            df_bank["卡片名稱"].map(_norm_card_key))
    )

    # roo.cash 只保留官網沒有的卡片
    def is_new(row):
        return (str(row["銀行代碼"]), _norm_card_key(row["卡片名稱"])) not in bank_keys

    df_roo_new = df_roo[df_roo.apply(is_new, axis=1)]
    log.info(f"roo.cash 補充了 {len(df_roo_new)} 張官網沒有的卡片")

    merged = pd.concat([df_bank, df_roo_new], ignore_index=True)
    merged = merged.sort_values(["銀行名稱", "卡片名稱"]).reset_index(drop=True)

    if output is None:
        output = f"merged_{datetime.now().strftime('%Y%m')}.csv"
    merged.to_csv(output, index=False, encoding="utf-8-sig")
    log.info(f"✅ 合併完成：共 {len(merged)} 筆，已儲存至 {output}")

    # 摘要
    log.info("── 來源分布 ──")
    for src, cnt in merged["來源標記"].value_counts().items():
        log.info(f"  {src}: {cnt} 筆")

    return merged


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="合併兩支爬蟲的 CSV")
    ap.add_argument("banks_csv", help="scraper_banks.py 輸出的 CSV")
    ap.add_argument("roocash_csv", help="scraper_roocash.py 輸出的 CSV")
    ap.add_argument("--output", help="合併後輸出檔名")
    args = ap.parse_args()

    df = merge(args.banks_csv, args.roocash_csv, args.output)
    print(f"\n📊 合併結果：{len(df)} 筆")
    print(df.groupby(["銀行名稱", "來源標記"])["卡片名稱"].count().to_string())
