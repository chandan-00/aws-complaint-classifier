"""Retrieve a per-category sample of CFPB complaints that have narratives.

CFPB stopped publishing consumer narratives (the search API and the bulk CSV
both dropped `complaint_what_happened` in Sep 2026), so this reads the CC0
Hugging Face snapshot of the narrative-bearing complaints instead:
BEE-spoke-data/consumer-finance-complaints, config `has-text`
(1.69M rows, 2015-03-19 .. 2024-02-09, ~925 MB of parquet, downloaded once).
"""
import json
from pathlib import Path

import pandas as pd
from huggingface_hub import snapshot_download

REPO = "BEE-spoke-data/consumer-finance-complaints"
CACHE = Path("data/hf_cfpb")
OUT = Path("data/raw_complaints.json")

# Canonical category -> CFPB product names it covers. CFPB renamed both credit
# reporting and credit card during 2023, so both spellings occur in the window.
CATEGORIES = {
    "credit_reporting": [
        "Credit reporting or other personal consumer reports",
        "Credit reporting, credit repair services, or other personal consumer reports",
    ],
    "debt_collection": ["Debt collection"],
    "mortgage": ["Mortgage"],
    "credit_card": ["Credit card", "Credit card or prepaid card"],
    "checking_savings": ["Checking or savings account"],
    "student_loan": ["Student loan"],
}
PER_CATEGORY = 2000
DATE_MIN = "2023-01-01"
SEED = 42

# Snapshot column -> the API field names the rest of the pipeline uses.
COLUMNS = {
    "Complaint ID": "complaint_id",
    "Date received": "date_received",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Company": "company",
    "State": "state",
    "Consumer complaint narrative": "complaint_what_happened",
}


def load_snapshot() -> pd.DataFrame:
    snapshot_download(REPO, repo_type="dataset", allow_patterns="has-text/*.parquet", local_dir=CACHE)
    files = sorted((CACHE / "has-text").glob("*.parquet"))
    df = pd.concat((pd.read_parquet(f, columns=list(COLUMNS)) for f in files), ignore_index=True)
    return df.rename(columns=COLUMNS)


def main() -> None:
    df = load_snapshot()
    df = df[df["date_received"] >= DATE_MIN]
    # "Credit card or prepaid card" also holds prepaid-card complaints.
    df = df[~df["sub_product"].fillna("").str.contains("prepaid", case=False)]

    parts = []
    for category, products in CATEGORIES.items():
        pool = df[df["product"].isin(products)]
        take = pool.sample(n=min(PER_CATEGORY, len(pool)), random_state=SEED)
        print(f"{category:18s} {len(pool):7d} available  {len(take):5d} sampled")
        parts.append(take)

    out = pd.concat(parts, ignore_index=True)
    out["complaint_id"] = out["complaint_id"].astype(str)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out.to_dict(orient="records")))
    print(f"\nTotal: {len(out)} rows -> {OUT}")


if __name__ == "__main__":
    main()
