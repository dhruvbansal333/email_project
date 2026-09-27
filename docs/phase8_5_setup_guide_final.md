# Phase 8.5 — Final Setup Guide (with security)

This is the complete, final version, including the shared-secret
authentication added on top of the original design. Do these steps
in order.

## What changed vs. the earlier version
- `app/main.py`: `/process` and `/extract` now REQUIRE a header
  `X-Ingestion-Key` matching a server-side `INGESTION_SECRET`. Missing
  or wrong key -> `401`. Secret not configured on the server at all ->
  `500` (fails loud, never silently open).
- `app/frontend.py`: now sends that same header automatically on every
  `/process` call.
- The Apps Script: now sends that same header too.
- `/health` is deliberately left unsecured, so you and Render's own
  health checks can always confirm the service is alive.

## Step 1 — Generate a secret key

Pick any long random string. Easiest way, in PowerShell:
```powershell
-join ((48..57)+(97..122)|Get-Random -Count 32|%{[char]$_})
```
Or just make up a long random password yourself (24+ characters, mixed
letters/numbers). Save it somewhere for a second — you'll paste this
exact value into THREE places below. Treat it like a password: don't
commit it to Git, don't paste it into any public place.

## Step 2 — Set it on Render

1. Go to your Render dashboard → your web service → **Environment**
2. Add a new environment variable:
   - **Key:** `INGESTION_SECRET`
   - **Value:** the random string from Step 1
3. Save — Render will automatically redeploy with the new variable

## Step 3 — Replace your project files

Replace these three files in your project with the versions in this
package:
- `app/main.py`
- `app/frontend.py`
- (new) `apps_script/commitment_ai_ingestion.gs` — this one isn't part
  of your Docker project; it's what you'll paste into script.google.com
  in Step 6

## Step 4 — Set the secret locally too (for testing before you redeploy)

If you want to test locally before pushing:
```powershell
$env:GOOGLE_API_KEY = "your-gemini-key"
$env:INGESTION_SECRET = "the-same-random-string-from-step-1"
uvicorn app.main:app --reload --port 8000
```
And in a second terminal, before running Streamlit, set the same
variable so the dashboard sends it too:
```powershell
$env:INGESTION_SECRET = "the-same-random-string-from-step-1"
streamlit run app/frontend.py
```
(Both terminals need it set — they're separate processes.)

## Step 5 — Test the security actually works

With the server running locally:

**Test A — no key (should fail with 401 or 500):**
```powershell
curl -X POST http://localhost:8000/process -H "Content-Type: application/json" -d "{\"text\": \"test\"}"
```
Expected: `401 Unauthorized` (if `INGESTION_SECRET` is set on the server
but you didn't send the header) — confirms unauthenticated requests are
correctly rejected.

**Test B — correct key (should succeed):**
```powershell
curl -X POST http://localhost:8000/process -H "Content-Type: application/json" -H "X-Ingestion-Key: the-same-random-string-from-step-1" -d "{\"text\": \"I will send the report by Friday.\"}"
```
Expected: normal `200 OK` with ranked commitments, same as always.

**Test C — dashboard still works end-to-end:**
Open `http://localhost:8501`, paste a test email, click Process. Should
work exactly as before (the dashboard sends the header automatically
now).

## Step 6 — Commit, push, redeploy

```powershell
git add app/main.py app/frontend.py
git commit -m "Phase 8.5 - Add shared-secret authentication to /process and /extract"
git push origin main
```
Render auto-redeploys on push. Watch the Logs tab — confirm you see:
```
Ingestion key configured — /extract and /process require it.
```
(If you instead see the "INGESTION_SECRET is not set" warning, go back
to Step 2 — you likely forgot to add it on Render, or there's a typo
in the variable name.)

Re-test the live URL once redeployed: open the dashboard, paste a test
email, confirm it still processes correctly.

## Step 7 — Set up the Apps Script

1. Go to https://script.google.com → New project
2. Paste in the entire contents of `commitment_ai_ingestion.gs`
3. Edit the CONFIG section at the top:
   ```javascript
   const API_URL = "https://ai-commitment-intelligence.onrender.com/process";
   const INGESTION_SECRET = "the-same-random-string-from-step-1";
   const SEARCH_QUERY = 'is:unread newer_than:7d -label:CommitmentAI-Processed';
   ```
   **This must be the exact same string as Step 1/2 — a single typo
   here means every request gets a 401.**
4. Rename the project to `CommitmentAI-Ingestion`

## Step 8 — Run `setupLabel` once

1. Select `setupLabel` from the function dropdown → **Run**
2. Authorize when prompted (click through the "unverified app" warning
   — expected for a self-authored script)
3. Confirm the log shows `"Created label: CommitmentAI-Processed"`
4. Confirm the label now exists in your Gmail sidebar

## Step 9 — Manual test before setting the trigger

1. Send yourself a test email matching your search query with real
   commitment text, e.g.: *"I'll send you the report by tomorrow
   afternoon. Please confirm by EOD."*
2. Select `processCommitmentEmails` → **Run**
3. Check the execution log:
   - `Processed OK: ...` → success, check your live dashboard for the
     new commitment
   - `AUTH FAILED (401)` → your secret doesn't match between the script
     and Render — go recheck both values character-for-character
   - Any other status code → likely a Render cold start; wait ~40
     seconds and run again
4. Confirm the test email now has the `CommitmentAI-Processed` label

## Step 10 — Confirm no duplicate processing

Run `processCommitmentEmails` again immediately. Log should show:
```
Found 0 thread(s) matching query.
```

## Step 11 — Set the automatic trigger

1. Click the clock icon (Triggers) in the left sidebar
2. **+ Add Trigger**
3. Function: `processCommitmentEmails` · Event source: Time-driven ·
   Type: Minutes timer · Every 5 minutes
4. Save, authorize if prompted again

## Step 12 — Real end-to-end test, no manual clicks

1. Send yourself a fresh test email from a different account
2. Wait 5 minutes without touching anything
3. Confirm: label applied automatically, commitment appears on the live
   dashboard, with zero manual action taken

## Report back
- Did the 401/success curl tests (Step 5) behave as expected?
- Did the Apps Script manual test (Step 9) succeed, or show a 401/other
  error?
- Did the fully-automatic trigger test (Step 12) work within 5 minutes?

Once confirmed, Phase 8.5 is genuinely complete and secured. Next:
**Phase 9 — report & defense prep.**
