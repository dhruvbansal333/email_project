# AI Commitment Intelligence System

Extracts commitments (who promised what, to whom, by when) from email text,
ranks them by urgency, and explains each ranking in plain language — so a
professional never loses track of what they owe or are owed.

**🔗 Live demo:** https://ai-commitment-intelligence.onrender.com/
*(Free-tier hosting: the app sleeps after inactivity — first load may take
30-50 seconds to wake up. This is expected, not a bug.)*

---

## What it does

Paste an email or thread into the dashboard, and the system:
1. Extracts every commitment (made or requested), with sender, recipient,
   deadline, and confidence
2. Scores each one 0–100 for urgency, combining deadline urgency, sender
   frequency, and extraction confidence
3. Generates a plain-language explanation for why each item was ranked
   where it was

## Architecture

```mermaid
flowchart TD
    A[User pastes/uploads email text] --> B[Streamlit Dashboard]
    B -->|POST /process| C[FastAPI Backend]
    C --> D[Gemini LLM Extraction]
    D -->|raw commitments| E[Rule-based Ranking Engine]
    E -->|urgency score + explanation| F[Per-user results<br/>Neon Postgres]
    F --> B
    G[Gold-labeled Sender History<br/>750 Enron threads] -.loaded at startup.-> E
```

Both the API and the dashboard run inside a single Docker container
(see `start.sh`) — the dashboard reaches the API over `localhost`
internally, and only the dashboard's port is exposed publicly by the host.

## Results (test set, held out, touched once)

| Metric | Score |
|---|---|
| Precision | 0.957 |
| Recall | 0.843 |
| F1 | 0.897 |
| Direction accuracy | 100% |

1,190 gold-labeled commitments, from a 750-thread Enron Email Corpus subset
+ 10 synthetic edge-case threads, 70/15/15 split. Full error analysis: 36
mismatches across 6 categories (see `docs/phase6_evaluation.md`).

## Tech stack

| Layer | Tool |
|---|---|
| Extraction | Gemini free-tier API (`google-genai` SDK), few-shot prompting |
| Ranking | Rule-based multi-factor scorer (`src/rank_score.py`) |
| Backend | FastAPI (`app/main.py`) |
| Frontend | Streamlit (`app/frontend.py`) |
| Deployment | Docker, hosted free on Render |

## Running it locally

```bash
pip install -r requirements.txt

# Terminal 1 - API
export GOOGLE_API_KEY="your-key-here"     # PowerShell: $env:GOOGLE_API_KEY="..."
uvicorn app.main:app --reload --port 8000

# Terminal 2 - Dashboard
streamlit run app/frontend.py
```
Or via Docker:
```bash
docker build -t commitment-intelligence .
docker run -p 7860:7860 -e GOOGLE_API_KEY="your-key-here" commitment-intelligence
```

## Project structure

```
app/
  main.py          # FastAPI: /health, /extract, /process
  frontend.py       # Streamlit dashboard
src/
  gemini_extractor.py    # LLM-based commitment extraction
  rank_features.py       # Feature engineering for ranking
  rank_score.py           # Urgency scoring + explanation generation
data/
  gold_set/v1/            # 1,190 gold-labeled commitments, train/val/test split
docs/                     # Phase-by-phase setup guides and evaluation writeups
Dockerfile, start.sh, requirements.txt   # Deployment
```

## Known limitations (disclosed, not hidden)

- **Sender identification** can resolve to a pronoun (e.g. "I") on
  first-person text with no named signoff.
- **Conditional deadlines** ("if the client signs off today, we need X by
  Friday") extract the deadline but don't yet preserve the condition itself.
- **Free-tier hosting**: cold starts after inactivity. The dashboard waits
  for the API to wake up before showing login. Results are stored per user in
  Neon Postgres, so they survive restarts, and are deleted after 7 days.
- **Gmail ingestion** is built (a self-authored Google Apps Script per user,
  personal API key, label-based opt-in). Polling runs every 5 minutes, and a
  network timeout can rarely cause a duplicate result.
- **Privacy**: see the section below. Email text is sent to Google's *free*
  Gemini tier, and the demo is not intended for users in the EEA, Switzerland
  or the UK.

## Privacy & data handling

Users sign up with a userid and password only (no email, so **no password
reset**). Only the *extracted* commitments are stored, per user, for 7 days;
the full email text is not saved. Email text is sent to Google's Gemini API on
the free tier, where Google may use content to improve its products, so the
demo should only be used with sample or non-confidential emails.

- In the app: sidebar → **Privacy & consent** (also readable before sign-up).
- Technical details, evidence labels and known limitations:
  [`docs/PRIVACY_AND_SECURITY.md`](docs/PRIVACY_AND_SECURITY.md).
- Tests that keep the notice honest against the code:
  `python -m pytest -q tests/test_privacy_page.py`.

This is a student demo: no professional security audit or legal review.

## Scope note

This is a deliberately narrowed slice of a larger "AI professional memory"
concept — full relationship graphs, opportunity recovery, and cross-platform
memory are explicitly out of scope and documented as future work, not
silently dropped. See the companion scope and roadmap documents for the
full reasoning.
