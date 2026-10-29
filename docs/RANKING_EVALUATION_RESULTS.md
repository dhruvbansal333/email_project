# Ranking Evaluation: Results

*Method, labelling guide and limitations: see `docs/RANKING_EVALUATION.md`. Numbers below are from the project owner's run of `python -m src.ranking_eval evaluate` (22 tests passing locally); they were copied from the owner's terminal output, not re-run elsewhere. The raw output is saved in `data/ranking_eval/ranking_eval_results.json`.*

## 1. Setup

| Item | Value |
|---|---|
| Population | Validation split (181 commitments, 101 threads). Test split not used |
| Sample | 60 commitments, deterministic (seed 42), drawn from `gold_val.json` |
| Human labels | HIGH 16, MEDIUM 19, LOW 25, one rater, labelled blind to the scorer's output and to extraction confidence |
| What the labels measure | **Urgency only** ("how soon would I need to act"), not importance |
| Scorer | Rule-based: 50% deadline urgency, 25% confidence, 15% sender frequency, 10% explicitness |
| Scorer resolution | 40 distinct scores for 60 items; 2% of compared pairs tied |

## 2. Results

| Metric | Scorer | 95% bootstrap CI | Deadline-only ordering | Random (expected) |
|---|---|---|---|---|
| Spearman rho | 0.426 | [0.182, 0.635] | 0.522 | -0.005 |
| NDCG@10 | 0.635 | [0.491, 0.845] | 0.714 | 0.429 |
| Pairwise accuracy | 0.705 | [0.592, 0.810] | 0.739 | 0.497 |
| R-precision (HIGH) | 0.417 | [0.154, 0.667] | 0.510 | 0.266 |

**Tier agreement** (scorer tier at thresholds 65 / 40 vs human label, rows = human):

| | Scorer LOW | Scorer MEDIUM | Scorer HIGH |
|---|---|---|---|
| Human LOW | 15 | 8 | 2 |
| Human MEDIUM | 5 | 6 | 8 |
| Human HIGH | 4 | 5 | 7 |

- Exact tier agreement: 28 of 60 (47%). Within one tier: 54 of 60 (90%).
- Two-tier inversions (human HIGH vs scorer LOW, or the reverse): 6 of 60 (10%).
- Scorer HIGH tier: 7 of 17 are human HIGH (41%). Human HIGH items: 7 of 16 reach the scorer HIGH tier (44%).

**Exploratory paired comparison** (scorer minus deadline-only, same bootstrap resamples; not pre-planned):

| Metric | Difference | 95% CI |
|---|---|---|
| Spearman rho | -0.096 | [-0.200, -0.001] |
| NDCG@10 | -0.078 | [-0.211, +0.038] |
| Pairwise accuracy | -0.034 | [-0.085, +0.014] |
| R-precision (HIGH) | -0.093 | [-0.219, +0.048] |

## 3. Interpretation

1. **The scorer agrees with the human urgency judgement better than chance.** The confidence intervals for Spearman rho and pairwise accuracy exclude the random-ordering values (0 and 0.5). The agreement is moderate, not strong.
2. **On this sample the full scorer was not better than ordering by deadline alone.** All four point differences are negative. Only the Spearman interval excludes zero, and only just (upper bound -0.001); the other three include zero. Four metrics were examined and the comparison was not planned in advance, so this is suggestive, not conclusive.
3. **Possible explanation (a hypothesis, not tested):** the labels measure urgency only, whereas confidence and sender frequency were designed to capture importance. A deadline-only ordering matches what was measured. The study therefore cannot say whether those features help the broader urgency-and-importance goal.

## 4. Error analysis (largest disagreements)

| Pattern | Examples | Mechanism in `src/rank_features.py` |
|---|---|---|
| Long or unresolved deadlines treated as moderately urgent | "the next 4 weeks" (scorer 69.3, human LOW), "January 23" (67.8, human LOW) | Explicit deadline text matching no keyword tier falls back to 0.55. Dates are not resolved against the email date |
| Urgency carried by context, not by a deadline phrase | Human HIGH with no deadline text (e.g. a request to complete a visa questionnaire): scorer 23 to 38 | No deadline text gives 0.1. The scorer reads deadline wording only, not the request itself |
| Vague phrases outside the keyword list | "in the near future" (scorer 36.8, human HIGH) | No keyword match gives the implicit fallback 0.35 |
| Items near a tier boundary | "please plan on attending" (64.9, human LOW) | Consistent with a base deadline score lifted by confidence and sender features (not verified item by item) |

## 5. Limitations

- One rater; some labels are debatable. They were not revised after seeing results.
- 60 items: wide intervals, and a handful of individual labels can move the numbers noticeably.
- The labels cover urgency, not importance.
- The same person built the gold set and judged urgency.
- The sender-frequency table includes validation data (as in production), so that one feature is slightly optimistic.
- No tuning was done on these labels. If the scorer is changed in response to these results, the new numbers on the same 60 items would be optimistic; a fresh sample from the remaining 121 validation items would be needed.

## 6. Future work (not done)

- Resolve deadlines against the email date, and handle durations ("next 4 weeks") and far dates explicitly.
- Use request context, not only deadline words, to detect urgency when no deadline is stated.
- Label importance separately and evaluate the urgency-plus-importance score against it.
- A second rater on a subset to report inter-rater agreement.
- If the scorer is revised, confirm on a fresh validation sample (disjoint from the 60 used here).
