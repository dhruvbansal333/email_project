"""
Step 2.4 — Structure the dataset.

Splits the cleaned Enron subset into train/val/test (70/15/15) BY THREAD
(not by individual message) so that no thread's messages leak across
splits, and combines it with the synthetic threads. Saves as a versioned
file (v1) — never overwrite silently, per the roadmap's Step 2.4 rule.

This runs before annotation (Phase 3). No labels exist yet for the real
Enron subset at this point — that's what Phase 3 produces. This step
only fixes which threads belong to which split, so annotation effort
isn't wasted on threads that later get reshuffled.

Usage:
    python src/structure_dataset.py
"""

import json
import random
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CLEANED_PATH = DATA_DIR / "cleaned" / "enron_ham_cleaned.csv"
SYNTHETIC_PATH = DATA_DIR / "synthetic" / "synthetic_threads_v1.jsonl"
OUT_DIR = DATA_DIR / "structured" / "v1"

SPLIT_RATIOS = {"train": 0.70, "val": 0.15, "test": 0.15}
RANDOM_SEED = 42


def split_threads(thread_ids: list[str], ratios: dict, seed: int) -> dict:
    rng = random.Random(seed)
    shuffled = thread_ids[:]
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_train = int(n * ratios["train"])
    n_val = int(n * ratios["val"])

    return {
        "train": shuffled[:n_train],
        "val": shuffled[n_train:n_train + n_val],
        "test": shuffled[n_train + n_val:],
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Real Enron subset ---
    df = pd.read_csv(CLEANED_PATH)
    enron_thread_ids = df["thread_key"].unique().tolist()
    enron_splits = split_threads(enron_thread_ids, SPLIT_RATIOS, RANDOM_SEED)

    # --- Synthetic threads ---
    synthetic_threads = []
    with open(SYNTHETIC_PATH) as f:
        for line in f:
            synthetic_threads.append(json.loads(line))
    synthetic_ids = [t["thread_id"] for t in synthetic_threads]
    synthetic_splits = split_threads(synthetic_ids, SPLIT_RATIOS, RANDOM_SEED)

    summary = {}
    for split_name in SPLIT_RATIOS:
        enron_ids = set(enron_splits[split_name])
        split_df = df[df["thread_key"].isin(enron_ids)]
        split_df.to_csv(OUT_DIR / f"enron_{split_name}.csv", index=False)

        syn_ids = set(synthetic_splits[split_name])
        split_syn = [t for t in synthetic_threads if t["thread_id"] in syn_ids]
        with open(OUT_DIR / f"synthetic_{split_name}.jsonl", "w") as f:
            for t in split_syn:
                f.write(json.dumps(t) + "\n")

        summary[split_name] = {
            "enron_threads": len(enron_ids),
            "enron_messages": len(split_df),
            "synthetic_threads": len(syn_ids),
        }

    with open(OUT_DIR / "split_manifest.json", "w") as f:
        json.dump({
            "version": "v1",
            "seed": RANDOM_SEED,
            "ratios": SPLIT_RATIOS,
            "summary": summary,
        }, f, indent=2)

    print("Split summary:")
    for split_name, stats in summary.items():
        print(f"  {split_name}: {stats}")
    print(f"\nSaved to {OUT_DIR}")
    print("NOTE: no gold labels yet — that's Phase 3. This only fixes the split.")


if __name__ == "__main__":
    main()
