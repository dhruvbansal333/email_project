# Phase 7, Step 7.3 — Streamlit Dashboard Setup Guide

## What this is
`app/frontend.py` is a Streamlit web UI that sits on top of the FastAPI
`/process` endpoint you verified in Step 7.1. You paste (or upload) an
email, it calls the API, and shows ranked commitments in a table.

Results are saved to `data/results_store.json` — a shared store, so this
same table would also show forwarded-email results later if Phase 8.5
(Gmail auto-ingestion) is ever built. No UI changes would be needed for
that.

## 1. Place the file
Put `frontend.py` inside your existing `app/` folder, next to `main.py`:
```
ai-commitment-intelligence/
├── app/
│   ├── main.py
│   └── frontend.py   <-- new
├── src/
│   └── ...
└── data/
    └── gold_set/v1/...
```

## 2. Install dependencies
```powershell
pip install streamlit requests pandas
```

## 3. Start BOTH servers (two separate terminals)

**Terminal 1 — API server (must already be running from Step 7.1):**
```powershell
$env:GOOGLE_API_KEY = "AIza...your key..."
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Streamlit dashboard:**
```powershell
streamlit run app/frontend.py
```
This should automatically open `http://localhost:8501` in your browser.
If it doesn't, open that URL manually.

## 4. What you should see
- A green "✅ API connected — N senders loaded" banner near the top.
  - If you see a red error instead, the API server (Terminal 1) isn't
    running or isn't reachable — check Terminal 1 for errors.
  - If you see a yellow warning about Gemini, `GOOGLE_API_KEY` wasn't
    set before starting the API server — stop it, set the key, restart.
- A text box to paste an email, plus an optional file uploader for
  `.txt`/`.eml` files.
- A "Process" button and a "Clear results" button.
- A results table below, sorted by urgency score (highest first).

## 5. Test it
1. Paste this into the text box:
   ```
   Hi Priya, I'll send you the revised contract by Friday afternoon.
   Also, can you review the attached budget and let me know your
   thoughts by end of day tomorrow?
   ```
2. Click **Process**.
3. You should see a success message ("Found 2 commitment(s)") and the
   table below should populate with both commitments, the "end of day
   tomorrow" one ranked above "Friday afternoon" — matching what you
   already saw in Step 7.1/7.2 testing.
4. Paste a second, different email and click Process again — the table
   should now show commitments from BOTH emails (this confirms the
   shared results store is working correctly across multiple inputs).
5. Click **Clear results** to reset the table to empty and confirm that
   works too.

## 6. Known limitations (fine to note in your report, not bugs)
- The results store is a single flat JSON file — fine at demo scale,
  not meant to scale to many concurrent users. This is consistent with
  the academic-scale limitation already documented for Phase 8.5.
- No authentication/session separation — anyone using this Streamlit
  instance sees the same shared results store. Not a concern for a
  single-user local demo.
- If Gemini extraction fails mid-request (e.g. rate limit), the error
  is shown in the UI rather than crashing the app, but that batch's
  results are not added to the store — you'd need to re-click Process.

## 7. What to report back
- Screenshot or description of the dashboard with at least 2 processed
  emails showing in the table.
- Confirm the urgency ranking order still looks correct (ASAP-style
  deadlines at top).
- Note anything that looked broken or confusing in the UI.

Once this works, you're ready for **Step 7.4 — Full pipeline test**
(running 10-15 unseen sample emails through the UI end-to-end), which
is the last step before Phase 8 (Deployment).
