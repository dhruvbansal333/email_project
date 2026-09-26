"""
Phase 5, Step 5.1 — Feature engineering for urgency/importance ranking.

Computes ranking features on top of extracted commitments:
- deadline_urgency: how soon the deadline sounds, from deadline_type +
  keyword matching in deadline_text (we don't have resolved calendar
  dates — deadlines are free text like "tomorrow" or "next week" — so
  urgency is estimated via keyword tiers, not literal days-until-due;
  this is a real, disclosed scope limitation, not an oversight)
- sender_importance: how often this sender appears across the dataset
  (a frequent correspondent's asks are treated as more consistently
  important than a one-off sender), computed empirically from the data
  itself rather than a fixed VIP list
- confidence_weight: direct mapping from the annotation's confidence field
- explicitness_bonus: explicit deadline language ranks above implicit
- direction_neutral: direction (made/requested) does NOT bias urgency —
  a promise you made and a request made of you are equally worth
  surfacing; direction affects framing/explanation text, not the score
"""

import json
import re
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Keyword tiers for deadline urgency, most-urgent first. Matched against
# deadline_text (case-insensitive substring match).
URGENCY_KEYWORDS = [
    (1.0, ["asap", "immediately", "right away", "urgent"]),
    (0.9, ["today", "this morning", "this afternoon", "tonight", "by end of day", "cob"]),
    (0.75, ["tomorrow", "this evening"]),
    (0.6, ["this week", "by friday", "by monday", "by tuesday", "by wednesday", "by thursday"]),
    (0.4, ["next week"]),
    (0.25, ["next month", "this month"]),
]


def deadline_urgency_score(deadline_type: str, deadline_text: str) -> float:
    """Returns 0.0-1.0. explicit > implicit > none as a base, refined by
    keyword matching within deadline_text when available."""
    if deadline_text:
        text = deadline_text.lower()
        for score, keywords in URGENCY_KEYWORDS:
            if any(kw in text for kw in keywords):
                return score
        # explicit/implicit deadline text present but no keyword matched
        # (e.g. a specific date like "april 26, 2001") — treat as
        # moderately urgent since a concrete deadline exists
        return 0.55 if deadline_type == "explicit" else 0.35

    if deadline_type == "explicit":
        return 0.5  # explicit deadline type but no text span captured
    elif deadline_type == "implicit":
        return 0.3
    return 0.1  # no deadline at all — lowest urgency tier, not zero,
                # since an undated commitment can still matter


CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.65, "low": 0.35}


def build_sender_frequency_table(commitments: list) -> Counter:
    """Empirical sender frequency across the dataset — used as a proxy
    for 'sender importance' per the design doc's ranking feature list."""
    return Counter(c["sender"] for c in commitments if c.get("sender"))


def normalize_frequency(count: int, max_count: int) -> float:
    if max_count <= 1:
        return 0.5
    return 0.3 + 0.7 * (count - 1) / (max_count - 1)  # floor at 0.3, cap at 1.0


def compute_features(commitment: dict, sender_freq_table: Counter, max_sender_freq: int) -> dict:
    urgency = deadline_urgency_score(commitment.get("deadline_type"), commitment.get("deadline_text"))
    confidence = CONFIDENCE_WEIGHTS.get(commitment.get("confidence"), 0.5)

    sender = commitment.get("sender")
    sender_count = sender_freq_table.get(sender, 0) if sender else 0
    sender_importance = normalize_frequency(sender_count, max_sender_freq) if sender else 0.3

    explicitness_bonus = 1.0 if commitment.get("deadline_type") == "explicit" else (
        0.6 if commitment.get("deadline_type") == "implicit" else 0.3
    )

    return {
        "deadline_urgency": round(urgency, 3),
        "sender_importance": round(sender_importance, 3),
        "confidence_weight": round(confidence, 3),
        "explicitness_bonus": round(explicitness_bonus, 3),
        "sender_occurrence_count": sender_count,
    }


def main():
    val = json.load(open(DATA_DIR / "gold_set" / "v1" / "gold_val.json"))
    train = json.load(open(DATA_DIR / "gold_set" / "v1" / "gold_train.json"))

    # Build sender frequency table from train+val combined (a realistic
    # proxy for "who does this person hear from often", not leaking any
    # ranking-relevant label — sender identity isn't the prediction target)
    all_commitments = train + val
    sender_freq_table = build_sender_frequency_table(all_commitments)
    max_sender_freq = max(sender_freq_table.values()) if sender_freq_table else 1

    print(f"Sender frequency table built from {len(all_commitments)} commitments, "
          f"{len(sender_freq_table)} distinct senders, max frequency {max_sender_freq}")

    featurized = []
    for c in val:
        features = compute_features(c, sender_freq_table, max_sender_freq)
        featurized.append({**c, "features": features})

    out_path = DATA_DIR / "gold_set" / "v1" / "val_with_features.json"
    with open(out_path, "w") as f:
        json.dump(featurized, f, indent=2)
    print(f"Saved {len(featurized)} featurized commitments to {out_path}")


if __name__ == "__main__":
    main()
