# Phase 8.5 — Shared Results Store Fix

## What was wrong
After splitting into two Render services (API + Dashboard) to fix the
405 error, the dashboard's `data/results_store.json` lived only in the
dashboard's own container. The API service (which Gmail ingestion
talks to directly) never touched that file. So Gmail-ingested
commitments were being extracted and ranked correctly, but had nowhere
visible to land.

## What changed
- `app/main.py` — added an in-memory `_results_store` list, shared by
  every call to `/process` regardless of who called it (dashboard or
  Gmail). Added two new endpoints:
  - `GET /results` — returns everything processed so far
  - `POST /results/clear` — empties the store
  Both require the same `X-Ingestion-Key` header as `/process`.
- `app/frontend.py` — no longer reads/writes a local file. Instead
  calls `GET /results` to display the table and `POST /results/clear`
  for the clear button. Added a "Source" column (dashboard vs. gmail)
  and a manual Refresh button.
- `apps_script/commitment_ai_ingestion.gs` — now tags its submissions
  with `"source": "gmail"` so they show up labeled correctly.

## Known limitation (worth noting in your report, not a bug)
The store is in-memory on the API service. If that service restarts
(Render free-tier services do restart, e.g. after a deploy or extended
idle), the store resets to empty. This is the same category of
free-tier limitation you've already documented elsewhere (e.g.
`results_store.json` not surviving restarts) -- just now living in a
different place. Fine for a demo; would need a real database
(Postgres, etc.) for anything production-grade.

## Steps

### 1. Replace files
- `app/main.py`
- `app/frontend.py`
- `apps_script/commitment_ai_ingestion.gs` (re-paste into
  script.google.com, replacing the old version)

### 2. Push to GitHub
```powershell
git add app/main.py app/frontend.py
git commit -m "Phase 8.5 - Shared results store so dashboard sees Gmail-ingested commitments"
git push origin main
```
Both Render services should auto-redeploy (API service picks up the
new endpoints; dashboard service picks up the new frontend.py).

### 3. Test end-to-end
1. Open the dashboard URL. Paste a test email, click Process. Confirm
   it still shows up in the table with `Source: dashboard`.
2. Click **Clear results** — table should empty.
3. In Apps Script, manually run `processCommitmentEmails` on a fresh
   test email. Check the log for `Processed OK` (200, not 405).
4. Go back to the dashboard, click the new **🔄 Refresh** button (or
   just reload the page) — the Gmail-ingested commitment should now
   appear, tagged `Source: gmail`.
5. Confirm both a dashboard-pasted item and a Gmail-ingested item can
   appear in the table at the same time.

### Report back
Does the Gmail-ingested commitment now show up in the dashboard after
clicking Refresh? That's the real confirmation this is fixed.
