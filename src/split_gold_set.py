"""
Step 3.4d — Final gold-set split. Splits by THREAD (not by individual
commitment) so no thread's commitments cross train/val/test boundaries,
consistent with the Phase 2 structuring approach. 70/15/15.
"""

import json
import random
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IN_PATH = DATA_DIR / "gold_set" / "v1" / "commitments_deduped.json"
OUT_DIR = DATA_DIR / "gold_set" / "v1"

SPLIT_RATIOS = {"train": 0.70, "val": 0.15, "test": 0.15}
RANDOM_SEED = 42


def main():
    commitments = json.load(open(IN_PATH))

    by_thread = defaultdict(list)
    for c in commitments:
        by_thread[c["thread_id"]].append(c)

    thread_ids = list(by_thread.keys())
    rng = random.Random(RANDOM_SEED)
    rng.shuffle(thread_ids)

    n = len(thread_ids)
    n_train = int(n * SPLIT_RATIOS["train"])
    n_val = int(n * SPLIT_RATIOS["val"])

    splits = {
        "train": thread_ids[:n_train],
        "val": thread_ids[n_train:n_train + n_val],
        "test": thread_ids[n_train + n_val:],
    }

    summary = {}
    for split_name, ids in splits.items():
        split_commitments = [c for tid in ids for c in by_thread[tid]]
        out_path = OUT_DIR / f"gold_{split_name}.json"
        with open(out_path, "w") as f:
            json.dump(split_commitments, f, indent=2)
        summary[split_name] = {
            "threads": len(ids),
            "commitments": len(split_commitments),
        }

    manifest = {
        "version": "v1",
        "seed": RANDOM_SEED,
        "ratios": SPLIT_RATIOS,
        "total_threads_with_commitments": n,
        "total_commitments": len(commitments),
        "summary": summary,
    }
    with open(OUT_DIR / "gold_split_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print("Gold set split summary:")
    for split_name, stats in summary.items():
        print(f"  {split_name}: {stats}")
    print(f"\nSaved to {OUT_DIR}")


if __name__ == "__main__":
    main()
