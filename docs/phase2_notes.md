# Phase 2 Notes: Data Acquisition & Cleaning

## Source substitution (Step 2.1)

The roadmap's suggested "Kaggle version" of the Enron corpus isn't
reachable from this build environment's network allowlist. Used instead:
[MWiechmann/enron_spam_data](https://github.com/MWiechmann/enron_spam_data)
on GitHub, which packages the same underlying Enron corpus (Klimt & Yang,
2004) as a single CSV with real message subjects, bodies, and dates, plus
a spam/ham label. We keep only ham (genuine) messages — 16,493 of them.

**If you have direct Kaggle/CMU access locally**, swap the source in
`src/data_acquisition.py` — `data_cleaning.py`, `structure_dataset.py`,
and everything downstream only depend on having `Subject`, `Message`, and
`Date` columns, not on where they came from.

## Known limitation: no explicit sender/recipient fields

This CSV source dropped email headers except Subject/Date — there's no
`From`/`To` column, unlike the full raw Enron .maildir corpus. This means:
- Thread grouping is done by normalized subject line (stripping Re:/Fwd:
  prefixes), not by actual message headers — a reasonable proxy, but
  noisier than true thread IDs.
- Sender/recipient identity for the annotation guideline's required
  fields will need to come from names extracted from the message body
  text (greeting/signoff lines) during Phase 3 annotation, not from a
  clean metadata field.
- Anonymization currently catches embedded email addresses via regex,
  but some emails in the source text have spaces around punctuation
  (e.g. `name @ enron . com`, an artifact of how this corpus was
  tokenized) and won't match the current regex. Worth a fix before
  Phase 3 labeling begins in earnest, or a manual scan of the subset for
  leftover PII.

## Pipeline run (already executed, outputs included in this package)

1. `src/data_acquisition.py` — downloaded and filtered to 16,493 ham messages.
2. `src/data_cleaning.py` — stripped forwarded headers, disclaimers, and
   signoffs; deduplicated; grouped into pseudo-threads; selected 750
   threads (525 multi-message, 225 singleton) totaling 3,028 messages;
   anonymized names (spaCy NER) and emails (regex).
3. `src/synthetic_generator.py` — 10 hand-authored seed threads, one per
   edge case from the annotation guideline (explicit deadline, implicit
   commitment, multiple deadlines, vague/conditional, group commitment,
   recurring, third-party-reported, weak commitment, non-commitment FYI,
   request-for-inaction). Scale to 150-250 by prompting an LLM with the
   same schema/categories and spot-checking against these seeds.
4. `src/structure_dataset.py` — 70/15/15 train/val/test split **by
   thread** (no thread's messages cross splits), combining real +
   synthetic data. Saved as versioned `data/structured/v1/`.

## Exit criteria check

Per the roadmap: "a cleaned, structured, split dataset sitting in /data,
ready for labeling." ✅ `data/structured/v1/` has train/val/test CSVs
(Enron) + JSONL (synthetic) with a `split_manifest.json` recording the
seed and ratios used, so the split is reproducible.

**Not done yet, by design:** no gold labels exist on the real Enron data
— that's Phase 3. This phase only fixes *which* threads go in which
split, so annotation effort isn't wasted on threads that get reshuffled
later.
