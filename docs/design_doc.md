# Design Doc: Extraction & Ranking Architecture Decisions (Phase 1, Step 1.3)

Status: Locked for MVP build. Revisit only if Phase 4/5 evaluation results
force a change — see Cross-Phase Discipline Rules in the roadmap
(don't expand scope mid-project).

## Decision 1: Commitment extraction approach

**Options considered:** fine-tuned transformer (DistilBERT token
classification), prompt-based LLM, hybrid.

**Decision: build both a fine-tuned transformer AND a few-shot LLM
baseline, evaluate both on the same validation set, and carry forward
whichever wins (or a simple hybrid) — as already specified in Phase 4.**

**Reasoning:**
- The baseline survey (`docs/baseline_comparison.md`) showed generic
  spaCy NER cannot do relation-level extraction at all — it only supplies
  candidate entities (names, dates). A transformer or LLM is required at
  minimum for the "who/what/to whom" relation, not just span detection.
- The zero-shot LLM pass already produced reasonable structured output
  with zero training data, including handling relative deadlines and
  conditional commitments spaCy missed entirely. This means a
  prompt-based approach is a credible, low-cost baseline — not just a
  strawman to beat.
- A fine-tuned transformer is expected to be more consistent and
  cheaper to run at inference time once trained, and produces the kind
  of quantifiable token-level P/R/F1 numbers the evaluation section
  needs. But it depends entirely on the gold-labeled dataset from
  Phase 3, which is the single biggest schedule risk in this project.
- Building both, rather than committing to one in advance, directly
  supports the Interview Talking Point on "modeling tradeoffs" and gives
  a real comparison table for the final report instead of an assumed
  answer.
- Explicitly rejected: pure rule-based extraction (regex/cue-phrase
  matching). Lampert, Dale & Paris (2010) show even message-level
  request classification needs statistical features beyond simple
  rules to get reasonable accuracy; full relation extraction (who/what/
  to whom/when) is harder than message-level classification, so
  rule-only extraction is very unlikely to be competitive. Rules will
  still be used inside the baseline (Phase 4, Step 4.1) for calibration.

## Decision 2: Urgency/importance ranking approach

**Options considered:** rule-based weighted scorer, learning-to-rank
(LightGBM ranker).

**Decision: build the rule-based weighted scorer as the primary/default
approach; keep learning-to-rank as a stretch comparison if time allows
after Phase 6.**

**Reasoning:**
- Explainability is a required deliverable (per the finalized scope),
  and a rule-based scorer is explainable by construction — each ranked
  item gets a plain-language reason string for free (e.g., "ranked
  high — deadline in 2 days, explicit commitment"), satisfying Phase 5
  Step 5.3 with no extra modeling work.
- A learning-to-rank model needs a reasonably sized, reliably labeled
  ranking dataset (relative urgency judgments, not just extraction
  labels) to avoid overfitting on a small gold set — this project's
  gold set is sized for extraction, not for training a second ranker
  from scratch. Requiring a second annotation pass for ranking labels
  would strain the Phase 3 timeline, already flagged as the highest
  schedule risk.
- The scope document explicitly allows "a well-justified rule-based
  scoring function" as an acceptable substitute for learning-to-rank —
  this keeps the ranking component inside the locked MVP scope rather
  than becoming a second modeling project.
- If validation shows the rule-based scorer's ranking quality (MAP/NDCG)
  is weak, LightGBM is the fallback per Phase 6's "if results are weak
  in a specific area, do one focused iteration" rule — not a rebuild.

## Summary table

| Component | Chosen approach | Fallback / comparison |
| --- | --- | --- |
| Extraction | Fine-tuned transformer (DistilBERT) | Few-shot LLM prompting, compared head-to-head |
| Ranking | Rule-based weighted scorer | LightGBM learning-to-rank, only if time allows |
| Explainability | Free from rule-based scorer (reason strings) | SHAP, only needed if ranking model is ML-based |

## Open questions carried into Phase 4/5

- Exact feature weights for the rule-based scorer (deadline proximity,
  sender frequency, explicit vs. implicit language) need to be set using
  real gold-set statistics, not guessed in the abstract — defer to
  Phase 5, Step 5.1.
- Whether the transformer or the LLM baseline wins extraction is an open
  empirical question by design — do not pre-decide it here.
