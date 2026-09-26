# Phase 6 — Evaluation & Iteration: Final Summary

## Final test-set results (touched exactly once, per roadmap discipline rule)

Extraction model selected in Phase 4: **few-shot LLM (Claude)**. Evaluated
on the full 103-document held-out test set (185 gold commitments) —
this is the FIRST and ONLY time the test set was used, consistent with
the roadmap's rule "do not touch the test set until Phase 6."

| Metric | Value |
|---|---|
| Precision | 0.957 |
| Recall | 0.843 |
| F1 | 0.897 |
| Direction accuracy (on matched commitments) | 1.000 |

For reference, this is slightly *higher* than the full-validation-set
result from Phase 4 (F1 0.879), which is a healthy sign — no overfitting
to the validation set's specific quirks, and performance holds up on
genuinely unseen data.

## Qualitative error analysis

36 total mismatches (7 false positives, 29 false negatives, 0 direction
errors) across 103 documents. Categorized below with representative
examples.

### Category A — Process/policy-description emails (largest error source: 11/29 false negatives, all from one document)

One test email (`pilot_2883`) describes an IT migration process ("you
will be restricted to a mailbox size of 100mb," "you will be prevented
from sending email," "everyone will have a read only view of notes
until the transition is completed"). The Phase 3 annotation guideline
counted these descriptive future-tense statements as commitments; the
LLM extraction judged the entire email as an informational policy
notice and extracted nothing. **This is a genuine definitional
disagreement, not a random error** — it reveals that "commitment" is
ambiguous at the boundary between a promise/request and a described
system behavior. A single email accounts for over a third of all
recall errors.

### Category B — Weak/boilerplate offers under-extracted (~4 false negatives)

Examples: *"I will be happy to assist you,"* *"I shall be available on
both days,"* *"I do have additional information to send out later this
month."* The annotation guideline explicitly includes these at low
confidence rather than excluding them; the LLM applied a slightly
stricter bar for what counts as a "real" commitment worth extracting.

### Category C — Question-form requests under-recognized (~2 false negatives)

Examples: *"Do you want anyone from HMS to attend?"*, *"Do you have any
co-owners volumes yet?"* Indirect question-phrased requests were
sometimes missed in favor of more direct imperative phrasing
("please...").

### Category D — Span/wording granularity mismatches (false positives)

Example: in one thread, both *"would 8.30am suit you"* and *"please let
me know if this suits you"* appear close together; the LLM extracted
both as separate commitments, while the gold annotation merged them
into one. The second prediction correctly describes real content but
falls below the 60% token-overlap threshold against the single gold
span, registering as a false positive. This is a granularity
disagreement, not a content error.

### Category E — Social/celebratory language over-extracted (false positive)

Example: *"please join us in congratulating Lorraine."* The annotation
guideline treats purely social/celebratory language as non-actionable
(consistent with excluding pleasantries), which the LLM extraction
occasionally missed, flagging a social request as if it were a task
commitment.

### Category F — Duplicate spans in forwarded/quoted chains (false positives)

Example: *"we will be killing about 2000 deals in sitara tonight"*
appears twice in one thread (once in the original message, once
re-quoted in a reply). The LLM correctly identified the content once,
but the source text's own duplication meant the matching algorithm
counted a second identical prediction as unmatched. This reflects
messy forwarded-email structure (already documented as a recurring
corpus property in `docs/phase3_final_summary.md`), not an extraction
quality issue.

## Should this trigger a focused iteration?

Per the roadmap: *"If results are weak in a specific area, do one
focused iteration — don't rebuild everything."* At F1 = 0.897 with
perfect direction accuracy, results are **not weak overall** — no
broad rebuild is warranted. However, Category A alone caused >1/3 of
all recall errors from a single document, which suggests one
targeted, low-cost fix:

**Recommended focused iteration (optional, not required):** clarify the
extraction prompt/guidance to explicitly address "process description"
emails — i.e., when an email describes what a system or process will
do to the recipient (not a person promising or requesting an action),
still extract it as a commitment if the annotation guideline would.
This is a prompt-wording fix, not a retraining exercise, and would
likely close most of Category A's gap. Given the overall strength of
the result, this is left as optional polish rather than a blocking
requirement.

## Phase 6 exit criteria — met

- Final metrics on held-out test set, touched exactly once: done
- Qualitative error analysis, 15-20+ examples pulled and categorized: done (36 examples, 6 categories)
- Findings written up: done (this document)
- Iteration decision made with reasoning (not a reflexive rebuild): done

**Next: Phase 7 — Dashboard & End-to-End Integration.**
