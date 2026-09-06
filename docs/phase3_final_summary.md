# Phase 3 Final Summary — Gold Set Complete

## What was built
- 750 real Enron email threads labeled (30 pilot + 720 across 21 manual
  batches), against the Phase 2 target of ~750.
- Labeling done via LLM-assisted pre-labeling with human verification in
  Label Studio, as explicitly sanctioned in the project's scope document.
- Schema: commitment span, direction (made/requested), deadline_type,
  confidence, third-party-reported flag, plus best-effort sender/
  recipient/deadline-text spans.

## Deduplication
The raw Enron corpus contains genuine duplicate/near-duplicate emails
(the same message appearing in multiple employees' mail folders — a
known property of this dataset, not a labeling artifact). Across
labeling, ~20 duplicate clusters were manually flagged in real time,
plus several recurring reporting templates (e.g. a "wellhead production
estimate" boilerplate reused verbatim across different months' reports
by the same sender).

An automated dedup pass was run on the final export:
- Matched on exact commitment-text equality (after whitespace
  normalization), restricted to spans of 10+ words to avoid false
  positives on short generic boilerplate ("please advise.", "I will
  keep you posted.") that legitimately recurs across genuinely
  different emails.
- Removed 36 duplicate commitments from 1,226 parsed → 1,190 unique
  commitments retained.
- Full removal log saved at `data/gold_set/v1/dedup_log.json` for
  transparency.

## Final gold set
- **1,190 unique labeled commitments** across 679 threads with at least
  one commitment (of 750 total labeled threads; 56 threads correctly
  had zero commitments — meeting reminders, OOO notices, automated
  confirmations, etc.)
- Split 70/15/15 by thread (not by commitment, so no thread crosses
  split boundaries): 475 / 101 / 103 threads → 824 / 181 / 185
  commitments.
- Saved at `data/gold_set/v1/gold_{train,val,test}.json`.

## Label distribution (sanity check)
- Direction: 63.5% made / 36.5% requested — reasonably balanced.
- Deadline type: 50.3% none / 35.0% explicit / 14.7% implicit.
- Confidence: 47.6% high / 40.3% medium / 12.2% low.
- Third-party-reported: 2.9% — a real but minority pattern (Edge Case 5).
- Sender identified: 54.1%; recipient: 20.1%; deadline-text span: 50.3%.
  Lower than 100% by design — these are best-effort fields given the
  data source's lack of clean From/To headers (documented in
  `docs/phase2_notes.md`), not a labeling gap.

## Known limitations, stated honestly
- Sender/recipient identification relies on names in email body text
  (signatures, greetings), not clean metadata — many commitments have
  these fields left null where the information genuinely wasn't
  present in the text.
- A handful of commitments in deeply nested forwarded/reply chains have
  uncertain sender attribution, explicitly flagged with `notes` during
  labeling (visible in the per-commitment data).
- LLM-assisted pre-labeling was used for most batches, verified by a
  human reviewer; this is disclosed as a method, consistent with the
  weak-supervision literature reviewed in Phase 1 (Shu et al., 2020).
