# Label Studio Setup Guide (Phase 3, Step 3.2)

## 1. Install (in your project venv)

```powershell
pip install label-studio
```

## 2. Start it

```powershell
label-studio start
```

This opens a browser window (usually `http://localhost:8080`). Create a
local account when prompted (stays on your machine, no data leaves).

## 3. Create the project

1. Click **Create Project**.
2. Name it something like `commitment-extraction-pilot`.
3. Go to the **Labeling Setup** tab, choose **Custom template / Code**,
   and paste in the contents of `docs/label_studio_config.xml`.
4. Save.

## 4. Import the pilot batch

1. Go to the **Data Import** tab (or **Import** on the project page).
2. Upload `data/pilot_batch/pilot_30.json`.
3. You should see 30 tasks appear.

## 5. IMPORTANT — test on ONE email before labeling all 30

Before labeling all 30, open just the first task and do a full dry run:

1. Highlight commitment #1's text span, tag it `COMMITMENT_MADE` or
   `COMMITMENT_REQUESTED`.
2. With that highlighted region still selected, a **per-region panel**
   should appear (usually on the right side) showing `deadline_type`,
   `confidence`, `third_party_reported`, and `notes` — fill these in.
3. If the email has a second commitment, highlight it as a **separate**
   span. Select it. Confirm a **separate, independent** panel appears for
   this second commitment — its `deadline_type`/`confidence` should be
   blank/unset, not copied from commitment #1.
4. Click back on commitment #1's highlighted span. Confirm its answers
   are still there, unchanged, and different from commitment #2's if you
   set them differently.

**If step 4 fails** (i.e. both commitments show the same answers, or
answers overwrite each other) — stop, the config didn't load correctly.
Re-check that you pasted the full XML from `label_studio_config.xml`
into the Code view, not just part of it, and that you're seeing the
per-region panel (attached to the selected highlight) rather than a
single set of fields fixed at the bottom of the page.

Only once this single-email test passes cleanly should you move on to
labeling the remaining 29.

## 6. Label the rest

For each task:
1. Highlight EACH commitment span separately in the text, tag it
   `COMMITMENT_MADE` or `COMMITMENT_REQUESTED` (this is your `direction`
   field, captured per-commitment).
2. Highlight sender/recipient/deadline-text mentions with the `parties`
   labels (these are just span identification, not per-commitment
   attributes).
3. For EACH commitment span, click it and fill in its own
   `deadline_type`, `confidence`, and `third_party_reported` in the
   per-region panel that appears for that specific highlight.
4. Flag `third_party_reported` if it matches Edge Case 5 from
   `docs/annotation_guideline_final.md` (remember — this is common,
   ~24/750 real threads matched this pattern, so expect to see it).
5. Use the per-commitment notes field for anything the schema doesn't
   capture cleanly (e.g. the `reported_by` name for a third-party
   commitment).

If an email has **no commitment at all** (8 of the 30 pilot emails were
deliberately picked to plausibly be this), just don't add any spans —
skip to the next task. That's a valid, expected outcome for those.

## 7. After the pilot (per roadmap Step 3.2)

- Review your own pilot labels after a day.
- If anything felt ambiguous or the guideline didn't clearly cover it,
  note it — that becomes a guideline revision, not a one-off judgment
  call, so future labeling stays consistent.
- Only then move to Step 3.3 (labeling the full ~750-thread gold set in
  batches of ~100).

## Export format

Label Studio exports to JSON (or CSV/CoNLL) matching this schema —
`Export` button on the project page once you're ready for Step 3.4.
