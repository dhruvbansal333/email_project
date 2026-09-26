"""
Phase 5, Step 5.2 — Rule-based weighted scorer.
Phase 5, Step 5.3 — Explainability layer (plain-language reason per item).

Combines features from rank_features.py into a single 0-100 urgency
score per commitment, ranks the list, and generates a human-readable
explanation for each ranked item — this is the exact deliverable the
roadmap's Step 5.3 exit criteria calls for: "ranked commitment list with
an explanation attached to each item, working on the validation set."

Weights are hand-set and documented here (not learned), consistent with
the Phase 1 design decision to use a rule-based scorer as the primary
approach specifically because it gives explainability for free.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Feature weights — sum to 1.0. Deadline urgency dominates (this is a
# "never forget a commitment" tool, so time pressure should drive rank
# more than anything else), confidence second (a shaky extraction
# shouldn't outrank a clear one even if it looks urgent), sender
# importance and explicitness bonus as smaller tie-breaking signals.
WEIGHTS = {
    "deadline_urgency": 0.50,
    "confidence_weight": 0.25,
    "sender_importance": 0.15,
    "explicitness_bonus": 0.10,
}


def score_commitment(features: dict) -> float:
    score = sum(WEIGHTS[k] * features[k] for k in WEIGHTS)
    return round(score * 100, 1)


def generate_explanation(commitment: dict, features: dict, score: float) -> str:
    """Plain-language reason string, per Step 5.3."""
    parts = []

    # Deadline framing
    dtype = commitment.get("deadline_type")
    dtext = commitment.get("deadline_text")
    if dtype == "explicit" and dtext:
        parts.append(f"explicit deadline ({dtext})")
    elif dtype == "explicit":
        parts.append("explicit deadline stated")
    elif dtype == "implicit" and dtext:
        parts.append(f"soft/implicit deadline ({dtext})")
    elif dtype == "implicit":
        parts.append("implicit deadline")
    else:
        parts.append("no deadline stated")

    # Confidence framing
    conf = commitment.get("confidence")
    if conf == "high":
        parts.append("high-confidence extraction")
    elif conf == "low":
        parts.append("low-confidence extraction — verify before acting")

    # Sender framing
    if features["sender_occurrence_count"] >= 5:
        parts.append(f"frequent correspondent ({features['sender_occurrence_count']} commitments on record)")

    # Direction framing (affects wording, not the score itself)
    if commitment.get("direction") == "made":
        parts.insert(0, "you promised this")
    else:
        parts.insert(0, "this was asked of you")

    tier = "HIGH" if score >= 65 else ("MEDIUM" if score >= 40 else "LOW")
    reason = f"[{tier} — {score}/100] " + "; ".join(parts) + "."
    return reason


def main():
    featurized = json.load(open(DATA_DIR / "gold_set" / "v1" / "val_with_features.json"))

    ranked = []
    for c in featurized:
        score = score_commitment(c["features"])
        explanation = generate_explanation(c, c["features"], score)
        ranked.append({
            "thread_id": c["thread_id"],
            "subject": c["subject"],
            "commitment_text": c["commitment_text"],
            "direction": c["direction"],
            "sender": c.get("sender"),
            "deadline_type": c.get("deadline_type"),
            "deadline_text": c.get("deadline_text"),
            "confidence": c.get("confidence"),
            "urgency_score": score,
            "explanation": explanation,
        })

    ranked.sort(key=lambda x: x["urgency_score"], reverse=True)

    out_path = DATA_DIR / "gold_set" / "v1" / "ranked_commitments.json"
    with open(out_path, "w") as f:
        json.dump(ranked, f, indent=2)

    print(f"Ranked {len(ranked)} commitments. Saved to {out_path}\n")
    print("=== Top 10 (highest urgency) ===")
    for item in ranked[:10]:
        print(f"{item['urgency_score']:>5.1f}  {item['explanation']}")
        print(f"        \"{item['commitment_text'][:90]}...\"")
    print("\n=== Bottom 5 (lowest urgency) ===")
    for item in ranked[-5:]:
        print(f"{item['urgency_score']:>5.1f}  {item['explanation']}")


if __name__ == "__main__":
    main()
