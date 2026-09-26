# Phase 7, Step 7.1 — API Layer Setup Guide

## What was built

- `src/gemini_extractor.py` — commitment extraction using the **free
  Gemini API** (Google AI Studio), using the current `google-genai` SDK
  (not the deprecated `google-generativeai` package — that one stopped
  receiving updates, so it was avoided here even though many
  older tutorials still reference it).
- `app/main.py` — FastAPI service with three endpoints:
  - `GET /health` — check the service and Gemini client are ready
  - `POST /extract` — extraction only, raw commitments back
  - `POST /process` — full pipeline: extract → rank → explain (this is
    what the Phase 7.3 dashboard will call)

Ranking reuses Phase 5's `rank_features.py` and `rank_score.py`
unchanged — no logic duplicated or rewritten.

## Setup (run these in your project folder)

```powershell
pip install fastapi uvicorn google-genai
```

Get a free API key: go to https://aistudio.google.com/app/apikey, sign
in with a Google account, click "Create API Key." Free tier is enough
for this project's usage volume.

Set the key as an environment variable (PowerShell):
```powershell
$env:GOOGLE_API_KEY = "AIza...your-key-here"
```
(Mac/Linux: `export GOOGLE_API_KEY="AIza...your-key-here"`)

This only lasts for your current terminal session — you'll need to set
it again if you open a new terminal, or add it to your shell profile /
a `.env` file if you want it to persist.

## Run the API

```powershell
uvicorn app.main:app --reload --port 8000
```

You should see in the terminal:
```
Loaded sender frequency table: 242 senders
Gemini client ready.
```

If you see "WARNING: Set GOOGLE_API_KEY..." instead, the key isn't set
correctly — double check the environment variable in that same
terminal session.

## Test it (per roadmap Step 7.1: "Test the API with sample email threads end-to-end")

**Option A — Interactive docs (easiest):**
Open http://localhost:8000/docs in your browser. This gives you a
clickable UI to try `/process` directly — click "Try it out," paste an
email into the `text` field, click Execute.

**Option B — curl:**
```powershell
curl -X POST http://localhost:8000/process `
  -H "Content-Type: application/json" `
  -d '{\"text\": \"Hi team, I will send the final report by Friday. Please review the attached budget and let me know your thoughts by end of day tomorrow. Thanks, Alex\"}'
```

**Option C — quick standalone smoke test (no server needed):**
```powershell
python src\gemini_extractor.py
```
This runs one sample email straight through `extract_commitments()` and
prints the raw JSON — good for confirming the API key works before
worrying about the FastAPI layer at all.

## Expected output shape

```json
{
  "ranked_commitments": [
    {
      "commitment_text": "I will send the final report by Friday.",
      "direction": "made",
      "deadline_type": "explicit",
      "deadline_text": "by Friday",
      "confidence": "high",
      "sender": "Alex",
      "recipient": null,
      "urgency_score": 78.4,
      "explanation": "[HIGH — 78.4/100] you promised this; explicit deadline (by Friday); high-confidence extraction."
    },
    ...
  ]
}
```

## What's next (not built yet)

- **Step 7.2** (email forwarding input) — per the earlier scope
  decision, this stays deferred; the API above is forwarding-ready
  by design (it accepts any raw text, regardless of source), so
  plugging in a Mailgun/SendGrid webhook later just means adding a new
  route that calls the same `extract_commitments()` + ranking logic —
  no rework needed here.
- **Step 7.3** (Streamlit dashboard) — the paste/upload demo UI that
  calls `/process`.
- **Step 7.4** (full pipeline test with 10-15 unseen samples).

If anything errors when you run this, paste the exact error message
back and I'll help debug it.
