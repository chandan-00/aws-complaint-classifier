"""Clean, balance and split the raw CFPB sample into train/val/test parquet files."""
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from fetch_cfpb_data import CATEGORIES, OUT as RAW

DATA = Path("data")
LABELS_OUT = Path("model/labels.json")
MIN_CHARS = 20
PER_CLASS = 1350          # 6 x 1350 = 8,100 rows, the ~8k target in section 15
SEED = 42

PRODUCT_TO_LABEL = {p: label for label, products in CATEGORIES.items() for p in products}


def main() -> None:
    df = pd.read_json(RAW, dtype={"complaint_id": str})
    df["text"] = df["complaint_what_happened"].fillna("").str.strip()
    df["label"] = df["product"].map(PRODUCT_TO_LABEL)
    original = df["label"].value_counts()

    df = df[df["text"].str.len() >= MIN_CHARS]

    # Template letters get filed many times verbatim. Duplicates would leak across
    # splits; a text filed under more than one label is ambiguous, so drop it outright.
    ambiguous = df.groupby("text")["label"].transform("nunique") > 1
    df = df[~ambiguous].drop_duplicates("text")
    cleaned = df["label"].value_counts()

    print("After filtering and de-duplication:")
    print(cleaned.to_string(), "\n")

    per_class = min(PER_CLASS, cleaned.min())
    df = df.groupby("label", group_keys=False).sample(n=per_class, random_state=SEED)

    train, temp = train_test_split(df, test_size=0.2, stratify=df["label"], random_state=SEED)
    val, test = train_test_split(temp, test_size=0.5, stratify=temp["label"], random_state=SEED)

    cols = ["complaint_id", "text", "label", "product", "date_received"]
    for name, split in [("train", train), ("val", val), ("test", test)]:
        split[cols].reset_index(drop=True).to_parquet(DATA / f"{name}.parquet", index=False)
        print(f"{name:5s} {len(split):5d} rows -> {DATA / f'{name}.parquet'}")

    labels = sorted(df["label"].unique())
    LABELS_OUT.write_text(json.dumps(labels, indent=2) + "\n")
    print(f"labels -> {LABELS_OUT}: {labels}\n")

    # Table for data/README.md (section 15).
    print("| Category | Fetched | After cleaning | Final count |")
    print("|---|---|---|---|")
    for label in labels:
        print(f"| {label} | {original[label]} | {cleaned[label]} | {per_class} |")


if __name__ == "__main__":
    main()
