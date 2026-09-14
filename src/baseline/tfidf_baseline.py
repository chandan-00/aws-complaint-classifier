"""Section 18: TF-IDF + Logistic Regression baseline, the number DistilBERT has to beat."""
import json
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, f1_score
from sklearn.pipeline import make_pipeline

DATA = Path("data")
FIG = Path("diagrams/baseline_confusion_matrix.png")
METRICS = Path("docs/baseline_metrics.json")
SEED = 42


def main() -> None:
    train = pd.read_parquet(DATA / "train.parquet")
    test = pd.read_parquet(DATA / "test.parquet")

    pipe = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=50_000,
                        sublinear_tf=True, stop_words="english"),
        LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED),
    )

    started = time.perf_counter()
    pipe.fit(train.text, train.label)
    fit_s = time.perf_counter() - started

    pred = pipe.predict(test.text)
    report = classification_report(test.label, pred, digits=4, output_dict=True)
    print(classification_report(test.label, pred, digits=4))
    print(f"fit: {fit_s:.1f}s   vocabulary: {len(pipe[0].vocabulary_):,} features")

    labels = sorted(test.label.unique())
    fig, ax = plt.subplots(figsize=(7, 6))
    ConfusionMatrixDisplay.from_predictions(
        test.label, pred, labels=labels, xticks_rotation=45, colorbar=False, cmap="Blues", ax=ax
    )
    ax.set_title(f"TF-IDF + LogReg — macro F1 {report['macro avg']['f1-score']:.4f}")
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=150)
    print(f"confusion matrix -> {FIG}")

    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps({
        "model": "tfidf+logreg",
        "accuracy": report["accuracy"],
        "macro_f1": report["macro avg"]["f1-score"],
        "micro_f1": f1_score(test.label, pred, average="micro"),
        "per_class_f1": {k: v["f1-score"] for k, v in report.items() if k in labels},
        "fit_seconds": round(fit_s, 1),
        "n_train": len(train),
        "n_test": len(test),
    }, indent=2) + "\n")
    print(f"metrics -> {METRICS}")


if __name__ == "__main__":
    main()
