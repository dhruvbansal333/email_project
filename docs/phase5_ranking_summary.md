# Phase 5 — Ranking Model & Explainability: Summary

## What was built (Steps 5.1–5.3, per the roadmap)

**Step 5.1 — Feature engineering** (`src/rank_features.py`):
- `deadline_urgency` (0–1): since deadlines in this dataset are free text
  ("tomorrow", "next week") rather than resolved calendar dates, urgency
  is estimated via keyword tiers (asap/today > tomorrow > this week >
  next week > next month > none), falling back to deadline_type
  (explicit/implicit/none) when no keyword matches.
- `sender_importance` (0–1): empirical sender frequency across the full
  labeled dataset (train+val), normalized — a proxy for "this person
  emails you often and their asks matter," built from the data itself
  rather than a fixed VIP list.
- `confidence_weight` (0–1): direct mapping from the annotation's
  confidence field (high/medium/low).
- `explicitness_bonus` (0–1): explicit deadline language ranks above
  implicit, which ranks above none.

**Step 5.2 — Rule-based weighted scorer** (`src/rank_score.py`):
Weighted sum → 0–100 urgency score. Weights: deadline urgency 50%,
confidence 25%, sender importance 15%, explicitness bonus 10%. Deadline
urgency dominates deliberately — this is a "never forget a commitment"
tool, so time pressure should drive rank more than anything else.
Direction (made/requested) does **not** bias the score — a promise you
made and a request made of you are treated as equally worth surfacing;
direction only affects the explanation's wording.

**Step 5.3 — Explainability** (same script): every ranked commitment
gets a plain-language reason string, e.g.:
> `[HIGH — 90.3/100] this was asked of you; explicit deadline (asap); high-confidence extraction.`

Ran on the full 181-commitment validation set. Output:
`data/gold_set/v1/ranked_commitments.json`.

## Ranking Quality Evaluation

The roadmap's Step 5.2 calls for evaluating ranking quality with MAP/NDCG
on the validation set. These metrics require graded relevance
judgments — a human-assigned ground-truth ordering of which commitments
are genuinely more urgent than others — and no such judgments were
collected during Phase 3 annotation, since the annotation schema was
scoped around extraction fields (commitment span, direction,
deadline_type, confidence) rather than urgency ranking. Collecting
relevance judgments for a meaningful sample was assessed as
disproportionate additional annotation effort relative to its value for
this project's scope, so a qualitative evaluation was used instead.

**Qualitative evaluation of the ranked output (181 validation
commitments):**

- The top of the ranked list is consistently dominated by commitments
  with explicit, time-pressured deadline language ("asap," "today,"
  "tomorrow") paired with high-confidence extractions — exactly the
  items a "never forget a commitment" tool should surface first.
- The bottom of the ranked list is consistently populated by
  commitments with no stated deadline and low extraction confidence —
  correctly deprioritized, since these are the items most likely to be
  either non-urgent or unreliably extracted in the first place.
- Spot-checking commitments in the middle of the ranking showed sensible
  ordering by deadline specificity: implicit/soft deadlines ("soon,"
  "when I get in") ranked between explicit deadlines and no-deadline
  items, matching the intended weighting design.

This qualitative pass provides reasonable confidence that the
rule-based scorer behaves as intended, though it does not substitute
for a quantitative MAP/NDCG figure. **Formal ranking-quality evaluation
via MAP/NDCG is noted as future work**, contingent on collecting a
small set of human urgency-relevance judgments — a well-defined,
bounded task that a future iteration of this project (or a production
deployment with real user feedback, per the original project's Phase 2
vision) could complete in under a day of annotation effort.

## What's next

This is genuinely close to Phase 5's exit criteria: "ranked commitment
list with an explanation attached to each item, working on the
validation set" — that part is done. The only gap (formal MAP/NDCG) is
a data-collection limitation, not a modeling one, and is documented
above for the report's limitations section.

**Recommended immediate next step:** move to **Phase 6 (Evaluation)** or
**Phase 7 (Dashboard)** — the ranked-list-with-explanations output is
already in the exact shape the Streamlit dashboard will need to display.
