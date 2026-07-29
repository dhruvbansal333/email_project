# AI Commitment Intelligence System

Extracts commitments (who promised what, to whom, by when) from email threads
and ranks them by urgency and importance, with a short explanation attached
to each ranking decision.

This is the **scoped MVP** version of a larger idea. See
`docs/scope.md` (copy of the finalized scope doc) for the reduction rationale
and `docs/roadmap.md` for the full phase-by-phase execution plan.

## What this project does

- **Commitment extraction**: identifies who made a commitment, what it is,
  to whom, and the deadline (if stated), from an email or thread.
- **Urgency + importance ranking**: ranks open commitments so the most
  pressing ones surface first.
- **Explainability**: a short reason (rule-based or SHAP-derived) for why
  each commitment was ranked where it was.
- **Demo dashboard**: a minimal Streamlit UI showing the ranked list.

## What this project deliberately does NOT do (see Future Work)

Relationship graphs, opportunity recovery, cross-platform memory, team/enterprise
features, live Gmail/Outlook integration. These are documented as roadmap only.

## Project structure

```
ai-commitment-intelligence/
├── data/          # Enron subset + synthetic threads (versioned, never overwritten silently)
├── notebooks/      # Exploration, baseline testing, EDA
├── src/            # Pipeline code: extraction, ranking, explainability, API
├── models/          # Saved model artifacts / checkpoints
├── app/             # Streamlit demo app + FastAPI service
├── docs/            # Literature notes, design docs, annotation guideline, evaluation writeup
├── requirements.txt
└── README.md
```

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download the spaCy baseline model
python -m spacy download en_core_web_sm

# 4. (Optional) create a Weights & Biases account and login
wandb login
```

## Dataset

- Primary: a subset (~500-1,000 threads) of the public Enron Email Corpus.
- Supplementary: synthetic email threads covering edge cases (ambiguous
  deadlines, implicit commitments, multi-person threads).
- No real user Gmail/personal data is collected. See `docs/privacy.md`.

## Status

Phase 0 — project setup in progress. See `docs/roadmap.md` for the full
timeline and exit criteria for each phase.

## License

TBD (add your institution's or a permissive license before making the repo public).
