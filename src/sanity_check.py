"""
Step 3.4c — Sanity-check the label distribution of the final gold set.
Per the roadmap's Step 3.4: "Sanity-check label distribution (how many
commitments, how many with deadlines, etc.)"
"""

import json
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IN_PATH = DATA_DIR / "gold_set" / "v1" / "commitments_deduped.json"


def main():
    commitments = json.load(open(IN_PATH))
    n = len(commitments)
    print(f"=== Gold Set Sanity Check ===")
    print(f"Total unique commitments: {n}\n")

    unique_threads = len(set(c["thread_id"] for c in commitments))
    print(f"Threads contributing at least one commitment: {unique_threads}")
    print(f"Average commitments per contributing thread: {n / unique_threads:.2f}\n")

    print("--- Direction ---")
    for k, v in Counter(c["direction"] for c in commitments).most_common():
        print(f"  {k}: {v} ({100*v/n:.1f}%)")

    print("\n--- Deadline type ---")
    for k, v in Counter(c["deadline_type"] for c in commitments).most_common():
        print(f"  {k}: {v} ({100*v/n:.1f}%)")

    print("\n--- Confidence ---")
    for k, v in Counter(c["confidence"] for c in commitments).most_common():
        print(f"  {k}: {v} ({100*v/n:.1f}%)")

    n_third_party = sum(1 for c in commitments if c["third_party_reported"])
    print(f"\n--- Third-party-reported ---")
    print(f"  yes: {n_third_party} ({100*n_third_party/n:.1f}%)")
    print(f"  no: {n - n_third_party} ({100*(n-n_third_party)/n:.1f}%)")

    n_sender = sum(1 for c in commitments if c["sender"])
    n_recipient = sum(1 for c in commitments if c["recipient"])
    n_deadline_text = sum(1 for c in commitments if c["deadline_text"])
    print(f"\n--- Best-effort fields (expected to be partial, per Phase 2 known limitation) ---")
    print(f"  sender identified: {n_sender} ({100*n_sender/n:.1f}%)")
    print(f"  recipient identified: {n_recipient} ({100*n_recipient/n:.1f}%)")
    print(f"  deadline_text span identified: {n_deadline_text} ({100*n_deadline_text/n:.1f}%)")

    lengths = [len(c["commitment_text"].split()) for c in commitments]
    print(f"\n--- Commitment span length (words) ---")
    print(f"  min: {min(lengths)}, max: {max(lengths)}, avg: {sum(lengths)/len(lengths):.1f}")

    # Flag anything that looks off
    print("\n--- Flags ---")
    if n_sender / n < 0.3:
        print(f"  [NOTE] Only {100*n_sender/n:.0f}% of commitments have an identified sender — expected given the data source's lack of clean From/To headers (see docs/phase2_notes.md), not a labeling error.")
    made_pct = 100 * sum(1 for c in commitments if c["direction"] == "made") / n
    if made_pct > 75 or made_pct < 25:
        print(f"  [NOTE] Direction split is skewed ({made_pct:.0f}% made) — worth mentioning in the report as a class imbalance to account for in modeling.")
    else:
        print(f"  [OK] Direction split looks reasonably balanced ({made_pct:.0f}% made / {100-made_pct:.0f}% requested).")


if __name__ == "__main__":
    main()
