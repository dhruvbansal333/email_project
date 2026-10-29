# Ranking Evaluation (Phase 6 addendum)

*Purpose: measure how well the rule-based urgency scorer (`src/rank_score.py`) orders commitments, using independent human urgency labels on a sample of the **validation** split.*

## 1. Why new labels were needed

The existing gold set (`data/gold_set/v1/`) has no urgency labels. Its `confidence` field (high/medium/low) records how clearly a sentence is a commitment, and the scorer uses it as an input (25% weight). The scorer's other inputs (`deadline_type`, `deadline_text`) are also gold fields. Treating any of these as "ground truth urgency" would only test whether the scorer agrees with its own inputs. So an independent HIGH/MEDIUM/LOW urgency judgement is collected for a sample.

| Item | Status |
|---|---|
| Validation split (181 commitments, 101 threads, no thread overlap with train) | Reused as the evaluation population |
| Test split | **Not used.** The code refuses any path containing "test" |
| Existing annotation files | **Not modified.** New files live in `data/ranking_eval/` |
| New human labels | 60 validation commitments, HIGH / MEDIUM / LOW (one rater) |

## 2. Files

| File | What it is |
|---|---|
| `src/ranking_eval.py` | Sheet generation and metrics (standard library only) |
| `tests/test_ranking_eval.py` | 19 tests: sampling, safeguards, metric maths, end-to-end |
| `data/ranking_eval/urgency_sheet_val.csv` | The blind sheet you fill in |
| `data/ranking_eval/sample_manifest.json` | Seed, item ids and the SHA-256 of `gold_val.json` the sample was drawn from |
| `data/ranking_eval/ranking_eval_results.json` | Written by `evaluate` |

The sample is the first 60 validation items ordered by SHA-256(`42|item_id`), so it is reproducible on any Python version. `item_id` is the first 10 hex characters of SHA-1(`thread_id|commitment_text`); all 181 validation ids were checked to be unique.

## 3. Labelling guide (fix this before you start; do not change it afterwards)

**Question to answer for every row:** *If this were on my to-do list today, how soon would I need to act before something goes wrong or someone is let down?*

Use only the four visible columns (subject, commitment text, direction, deadline text). Treat things you promised (`made`) and things asked of you (`requested`) the same way. The sheet deliberately hides the scorer's output and the extraction `confidence`.

| Label | Meaning |
|---|---|
| **HIGH** | Needs action today or within about 1 to 2 days, or is explicitly immediate ("ASAP", "tonight", a hard near deadline) |
| **MEDIUM** | Should be done within roughly a week, or has real but softer time pressure ("this week", "by Friday", "soon") |
| **LOW** | No real time pressure, a vague follow-up, or a deadline weeks away; it could slip a week without harm |

Rules:

1. If torn between MEDIUM and LOW, ask: *would I be bothered if this slipped a week?* Yes means MEDIUM.
2. Emails carry no date, so read "Friday" or "tomorrow" as relative to a message sent a few days earlier.
3. Use the `note` column for doubts. Do not edit any other column, and **do not sort or reorder rows** (`evaluate` rejects a reordered sheet).
4. Label in one or two sittings. Valid values: `HIGH`, `MEDIUM`, `LOW` (also `H`, `M`, `L`, any case).
5. **Do not change labels after seeing results.** Run `evaluate` once, when every row is labelled.

Estimated time: 30 to 40 minutes.

## 4. How to run

```powershell
cd <project folder>
python -m pytest -q tests/test_ranking_eval.py
# The sheet and manifest are already provided. Only run make-sheet if they are missing:
#   python -m src.ranking_eval make-sheet
# 1. Open data\ranking_eval\urgency_sheet_val.csv in Excel, fill urgency_label, save as CSV (keep the same name).
python -m src.ranking_eval evaluate
```

`make-sheet` refuses to overwrite an existing sheet (use `--force` only if you want to discard labels).

## 5. Metrics

All metrics are tie-aware, because the scorer produced only 83 distinct scores for 181 validation items (many items share a score).

| Metric | Meaning |
|---|---|
| **Spearman rho** | Rank correlation between scorer score and human label (HIGH=2, MEDIUM=1, LOW=0), average ranks for ties. Undefined if either side is constant |
| **NDCG@10** | Linear gains (0/1/2). Tied items share the positions they span, i.e. the expected value over random tie-breaking |
| **Pairwise accuracy** | Over all pairs with different human labels: share the scorer orders the same way; ties count 0.5. The share of tied pairs is also reported |
| **R-precision (HIGH)** | Of the scorer's top-R items (R = number of human HIGH), the expected share that are HIGH; ties at the boundary are split proportionally |
| **95% bootstrap CI** | 2,000 resamples of the 60 items (seed 42) |
| **Baselines** | Random ordering (expected value, simulated) and a deadline-urgency-only ordering |
| **Confusion matrix** | Human label vs the scorer's tier (HIGH at 65 or above, MEDIUM at 40 or above, otherwise LOW) |
| **Largest disagreements** | The 8 items whose scorer rank percentile differs most from the human percentile, for error analysis |

The maths is covered by tests, including a cross-check of Spearman against SciPy and a brute-force check of the tie-aware NDCG.

## 6. Limitations (state these in the report)

1. **One rater.** The labels are one person's judgement, not a universal truth. Optional strengthening: a second person labels 15 to 20 of the same rows and agreement (for example Cohen's kappa) is reported.
2. **Small sample (60).** Expect wide confidence intervals; report them, not just point estimates.
3. **Same person annotated the gold set and judges urgency.** Familiarity with the data could correlate the two; not controlled.
4. **No dates in the emails**, so relative deadlines ("tomorrow") cannot be resolved. This is also a limitation of the scorer.
5. **Sender-frequency feature uses train + validation**, as in Phase 5 and production, so that one feature is slightly optimistic on validation items.
6. **No tuning on these labels.** The scorer's weights are hand-set and were fixed before labelling. If weights are changed after looking at results, the new numbers are optimistic and must be reported as such; the remaining 121 validation items are the natural place for a fresh check.
7. **Validation only.** Nothing here touches the held-out test split, which was used once for extraction (Phase 6).
8. **Evidence label.** Test results in this repository are automated checks of the evaluation code. The ranking *results* exist only after the owner labels the sheet and runs `evaluate`.

## 7. Wording for the report (fill in after running)

> Ranking quality was evaluated on a random sample of 60 validation commitments labelled HIGH/MEDIUM/LOW for urgency by one rater, independently of the scorer's inputs. The scorer reached Spearman ρ = __ (95% CI __ to __), pairwise accuracy = __, and NDCG@10 = __, compared with __ for a deadline-only ordering and about 0 for a random ordering. With one rater and 60 items, these results indicate agreement with a single human judgement rather than a universal ground truth.
