import requests
import pandas as pd
import io
import os
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "crawler_data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DIRECT_URL = "https://www.banking.gov.tw/webdowndoc?file=/stat/opendata/banking66.csv"

def download_credit_card_stats() -> pd.DataFrame:
    resp = requests.get(DIRECT_URL, timeout=30, verify=False)
    resp.encoding = "utf-8-sig"
    df = pd.read_csv(io.StringIO(resp.text))
    
    output_path = os.path.join(OUTPUT_DIR, "credit_card_stats.csv")
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"✅ 已儲存至 {output_path}")
    return df

if __name__ == "__main__":
    df = download_credit_card_stats()
    print(df.head())