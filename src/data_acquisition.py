"""
Step 2.1 — Get the Enron corpus.

Source note: the roadmap's suggested "Kaggle version" isn't reachable from
this build environment's network allowlist. Used instead: the MWiechmann/
enron_spam_data GitHub repo (https://github.com/MWiechmann/enron_spam_data),
which packages the same underlying Enron corpus (Klimt & Yang, 2004) in a
single clean CSV with real message bodies, subjects, and dates, plus a
spam/ham label we use to keep only the genuine (ham) messages.

If you have Kaggle access locally, you can swap this for the Kaggle version
directly — the cleaning/structuring steps downstream don't care about the
source as long as the output matches the expected columns (subject,
message, date).

Usage:
    python src/data_acquisition.py
"""

import zipfile
import io
import urllib.request
from pathlib import Path

import pandas as pd

RAW_ZIP_URL = "https://codeload.github.com/MWiechmann/enron_spam_data/zip/refs/heads/master"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"


def download_and_extract() -> Path:
    """Download the enron_spam_data repo zip and extract the inner CSV."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    outer_zip_path = RAW_DIR / "enron_spam_data_repo.zip"

    print(f"Downloading {RAW_ZIP_URL} ...")
    urllib.request.urlretrieve(RAW_ZIP_URL, outer_zip_path)

    with zipfile.ZipFile(outer_zip_path) as outer_zip:
        inner_zip_name = next(
            n for n in outer_zip.namelist() if n.endswith("enron_spam_data.zip")
        )
        with outer_zip.open(inner_zip_name) as inner_zip_bytes:
            with zipfile.ZipFile(io.BytesIO(inner_zip_bytes.read())) as inner_zip:
                inner_zip.extractall(RAW_DIR)

    csv_path = RAW_DIR / "enron_spam_data.csv"
    assert csv_path.exists(), "Expected enron_spam_data.csv after extraction"
    return csv_path


def load_ham_only(csv_path: Path) -> pd.DataFrame:
    """Load the CSV and keep only genuine (ham) messages."""
    df = pd.read_csv(csv_path)
    df = df[df["Spam/Ham"] == "ham"].copy()
    df = df.dropna(subset=["Message"])
    return df.reset_index(drop=True)


if __name__ == "__main__":
    csv_path = download_and_extract()
    df = load_ham_only(csv_path)
    print(f"Loaded {len(df)} genuine (ham) messages from {csv_path}")
    out_path = RAW_DIR / "enron_ham_raw.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved to {out_path}")
