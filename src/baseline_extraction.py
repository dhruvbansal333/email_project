"""
Phase 4, Step 4.1 — Rule-based / regex + spaCy NER baseline.

Approach: split each email into sentences (spaCy), flag sentences
containing commitment cue phrases, classify direction via simple
first-person-modal vs. imperative/question heuristics, extract a
deadline_type guess via date/time entity presence.

This deliberately does NOT try to be clever — it's the baseline the
main model (Step 4.2) needs to beat, consistent with the roadmap's own
instruction: "Implement a rule-based/regex + spaCy NER baseline, run it
on the validation set, record precision/recall/F1 as your baseline
number."

Evaluation metric: since this is span extraction (not classification),
we use sentence-level overlap — a predicted commitment sentence counts
as a match if it has significant token overlap with a gold commitment
span in the same document (captures "did the baseline find the right
sentence" without requiring exact character-level span match, which
would be unreasonably strict for a rule-based system).
"""

import json
import re
from pathlib import Path

import spacy

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
VAL_PATH = DATA_DIR / "gold_set" / "v1" / "documents_val.json"
OUT_PATH = DATA_DIR / "gold_set" / "v1" / "baseline_results.json"

nlp = spacy.load("en_core_web_sm")

# --- Rule-based extraction ---

MADE_CUES = re.compile(
    r"\b(i|we)\s*(?:'ll|will|shall|am going to|are going to|plan to|intend to)\b",
    re.IGNORECASE,
)
REQUESTED_CUES = re.compile(
    r"^(please|could you|can you|would you|will you)\b|\bplease\b",
    re.IGNORECASE,
)
COMMITMENT_CUE = re.compile(
    r"\b(i'll|i will|we'll|we will|shall|please|could you|can you|would you|"
    r"let me know|get back to you|follow up|will send|will forward|will call|"
    r"will provide|will have|will need|will update)\b",
    re.IGNORECASE,
)
DATE_ENT_LABELS = {"DATE", "TIME"}


def extract_commitments_ruled(text):
    doc = nlp(text)
    predictions = []
    for sent in doc.sents:
        s = sent.text.strip()
        if len(s) < 5:
            continue
        if not COMMITMENT_CUE.search(s):
            continue

        if MADE_CUES.search(s):
            direction = "made"
        elif REQUESTED_CUES.search(s):
            direction = "requested"
        else:
            direction = "requested" if s.split()[0].lower() in {
                "send", "let", "please", "give", "call", "review", "confirm"
            } else "made"

        has_date_ent = any(ent.label_ in DATE_ENT_LABELS for ent in sent.ents)
        deadline_type = "explicit" if has_date_ent else "none"

        predictions.append({
            "text": s,
            "direction": direction,
            "deadline_type": deadline_type,
        })
    return predictions


# --- Evaluation: sentence-level overlap matching ---

def token_overlap_ratio(a, b):
    ta = set(re.findall(r"\w+", a.lower()))
    tb = set(re.findall(r"\w+", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


OVERLAP_THRESHOLD = 0.6


def evaluate(documents):
    tp, fp, fn = 0, 0, 0
    direction_correct = 0
    matched_gold_total = 0

    for doc in documents:
        gold_commitments = doc["commitments"]
        predictions = extract_commitments_ruled(doc["text"])

        matched_gold_idxs = set()
        for pred in predictions:
            best_match, best_score = None, 0.0
            for i, gold in enumerate(gold_commitments):
                if i in matched_gold_idxs:
                    continue
                score = token_overlap_ratio(pred["text"], gold["commitment_text"])
                if score > best_score:
                    best_score, best_match = score, i

            if best_match is not None and best_score >= OVERLAP_THRESHOLD:
                tp += 1
                matched_gold_idxs.add(best_match)
                if pred["direction"] == gold_commitments[best_match]["direction"]:
                    direction_correct += 1
                matched_gold_total += 1
            else:
                fp += 1

        fn += len(gold_commitments) - len(matched_gold_idxs)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    direction_acc = direction_correct / matched_gold_total if matched_gold_total else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "direction_accuracy_on_matches": direction_acc,
    }


def main():
    documents = json.load(open(VAL_PATH))
    print(f"Evaluating rule-based baseline on {len(documents)} validation documents "
          f"({sum(len(d['commitments']) for d in documents)} gold commitments)...")

    results = evaluate(documents)

    print("\n=== Rule-based + spaCy Baseline (Step 4.1) — Validation Results ===")
    print(f"  Precision: {results['precision']:.3f}")
    print(f"  Recall:    {results['recall']:.3f}")
    print(f"  F1:        {results['f1']:.3f}")
    print(f"  TP={results['tp']}  FP={results['fp']}  FN={results['fn']}")
    print(f"  Direction accuracy (on matched spans): {results['direction_accuracy_on_matches']:.3f}")
    print(f"\n  (Match criterion: predicted sentence and gold commitment span share")
    print(f"   >= {OVERLAP_THRESHOLD*100:.0f}% token overlap relative to the shorter span.)")

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {OUT_PATH}")


if __name__ == "__main__":
    main()
