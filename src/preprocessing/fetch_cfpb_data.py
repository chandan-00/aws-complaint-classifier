"""Retrieve a per-product sample of CFPB complaints that have narratives."""
import json
import time
from pathlib import Path
import requests
import io, csv
API = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
# Verify these strings against a live no-filter query before trusting them.
# CFPB has renamed product categories more than once.
PRODUCTS = [
    "Credit reporting or other personal consumer reports",
    "Debt collection",
    "Mortgage",
    "Credit card",
    "Checking or savings account",
    "Student loan",
]
PER_PRODUCT = 1000
PAGE = 100
OUT = Path("data/raw_complaints.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

def fetch_product(product: str) -> list[dict]:
    rows, seen, frm = [], set(), 0
    while len(rows) < PER_PRODUCT and frm < 10000:
        params = {
            "product": product,
            "has_narrative": "true",
            "size": PAGE,
            "frm": frm,
            "sort": "created_date_desc",
            "date_received_min": "2023-01-01",
            "no_aggs": "true",
        }
        
        r = requests.get(API, headers=HEADERS, params=params, timeout=60)
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
        if not hits:
            break

        new = [h["_source"] for h in hits if h["_source"]["complaint_id"] not in seen]
        if not new:
            print(f"  no new records at frm={frm} — pagination not advancing")
            break
        seen.update(r["complaint_id"] for r in new)
        rows = list(csv.DictReader(io.StringIO(r.text)))
        rows.extend(new)
        frm += PAGE
        time.sleep(0.3)          # be polite to a public government API
        
    print(f"{product[:45]:45s} {len(rows):5d} unique")
    return rows[:PER_PRODUCT]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for product in PRODUCTS:
        all_rows.extend(fetch_product(product))
    OUT.write_text(json.dumps(all_rows))

    print(f"\nTotal: {len(all_rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
    