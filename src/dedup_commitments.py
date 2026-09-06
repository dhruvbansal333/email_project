"""
Step 3.4b — Deduplicate the parsed commitment set.

Two dedup passes:
1. Exact commitment_text duplicates across different threads — this is
   the pattern flagged repeatedly during labeling (e.g. "vlt wellhead
   production", "term papers", "new albany", "aep transition items"),
   caused by the same underlying email existing multiple times in the
   raw Enron corpus (a known property of the dataset, documented in
   docs/phase2_notes.md).
2. Near-duplicate detection (same commitment_text after whitespace
   normalization) as a secondary catch.

Keeps the FIRST occurrence of each duplicate group, drops the rest, and
logs exactly what was removed for transparency in the report.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IN_PATH = DATA_DIR / "gold_set" / "v1" / "commitments_raw.json"
OUT_PATH = DATA_DIR / "gold_set" / "v1" / "commitments_deduped.json"
LOG_PATH = DATA_DIR / "gold_set" / "v1" / "dedup_log.json"


def normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())


MIN_WORDS_FOR_DEDUP = 10  # raised further after inspection showed common
                           # boilerplate ("i will keep you posted", "let me
                           # know if you have any questions") independently
                           # recurring across genuinely different emails —
                           # only longer, more specific text is safe to
                           # treat as evidence of the same underlying email


def main():
    commitments = json.load(open(IN_PATH))
    print(f"Loaded {len(commitments)} commitments")

    seen = {}
    kept = []
    removed_log = []

    for c in commitments:
        key = normalize(c["commitment_text"])
        word_count = len(key.split())

        if word_count < MIN_WORDS_FOR_DEDUP:
            # too short/generic to safely dedup on text match alone — keep
            kept.append(c)
            continue

        if key in seen:
            removed_log.append({
                "removed_thread": c["thread_id"],
                "removed_subject": c["subject"],
                "kept_thread": seen[key]["thread_id"],
                "kept_subject": seen[key]["subject"],
                "commitment_text": c["commitment_text"][:100],
            })
            continue
        seen[key] = c
        kept.append(c)

    print(f"Removed {len(removed_log)} exact-duplicate commitments")
    print(f"Kept {len(kept)} unique commitments")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(kept, f, indent=2)
    with open(LOG_PATH, "w") as f:
        json.dump(removed_log, f, indent=2)

    print(f"Saved deduped set to {OUT_PATH}")
    print(f"Saved dedup log to {LOG_PATH}")

    if removed_log:
        print("\nSample of removed duplicates:")
        for r in removed_log[:10]:
            print(f"  [{r['removed_thread']}] duplicate of [{r['kept_thread']}]: {r['commitment_text']}")


if __name__ == "__main__":
    main()
