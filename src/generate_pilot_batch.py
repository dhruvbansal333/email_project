"""
Step 3.2 (pilot batch) — pull ~30 emails from the real Enron subset,
lightly clean + anonymize, and export as a Label Studio task JSON.

Regenerates minimal cleaning inline since this only needs 30 emails, not
the full 750-thread pipeline (see src/data_cleaning.py from Phase 2 for
the full version — rerun that first if you want the pilot drawn from the
already-deduped/threaded subset instead of raw).

Selection: mixes messages that plausibly contain a commitment (matched
via loose cue words, for pilot value) with a few that plausibly don't
(so the pilot also exercises the "non-commitment" guideline section) —
NOT a random sample, and not meant to be: the pilot's job is to stress-
test the guideline on varied cases, not to be statistically representative.

Usage:
    python src/generate_pilot_batch.py
"""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import spacy

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_PATH = DATA_DIR / "raw" / "enron_ham_raw.csv"
OUT_DIR = DATA_DIR / "pilot_batch"

COMMITMENT_CUES = re.compile(
    r"\b(i'll|i will|we'll|we will|let's|please send|will send|"
    r"get back to you|follow up|by friday|by monday|deadline)\b",
    re.IGNORECASE,
)

FORWARD_HEADER_RE = re.compile(r"-{5,}\s*forwarded by.*?-{5,}", re.IGNORECASE | re.DOTALL)
REPLY_HEADER_RE = re.compile(r"^(from|to|cc|subject|sent)\s*:.*$", re.IGNORECASE | re.MULTILINE)


def clean_message(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = FORWARD_HEADER_RE.sub(" ", text)
    text = REPLY_HEADER_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def anonymize(text: str, nlp) -> str:
    def hash_email(match):
        return "user_" + hashlib.sha256(match.group(0).encode()).hexdigest()[:8] + "@anon"
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", hash_email, text)
    doc = nlp(text)
    spans = [(ent.start_char, ent.end_char) for ent in doc.ents if ent.label_ == "PERSON"]
    for start, end in sorted(spans, reverse=True):
        anon = "person_" + hashlib.sha256(text[start:end].encode()).hexdigest()[:6]
        text = text[:start] + anon + text[end:]
    return text


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(RAW_PATH)
    df["message_clean"] = df["Message"].apply(clean_message)
    df = df[df["message_clean"].str.len().between(40, 1500)]  # skip near-empty and huge auto-notification emails

    has_cue = df["message_clean"].str.contains(COMMITMENT_CUES)
    likely_commitment = df[has_cue].sample(n=22, random_state=42)
    likely_not = df[~has_cue].sample(n=8, random_state=42)
    pilot = pd.concat([likely_commitment, likely_not]).sample(frac=1, random_state=1).reset_index(drop=True)

    print("Anonymizing pilot batch...")
    nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
    pilot["message_anon"] = pilot["message_clean"].apply(lambda t: anonymize(t, nlp))

    tasks = []
    for i, row in pilot.iterrows():
        tasks.append({
            "id": i + 1,
            "data": {
                "text": row["message_anon"],
                "thread_id": f"pilot_{row['Message ID']}",
                "subject": row["Subject"],
                "date": row["Date"],
                "likely_commitment_cue": bool(has_cue.loc[row.name]) if row.name in has_cue.index else None,
            },
        })

    out_path = OUT_DIR / "pilot_30.json"
    with open(out_path, "w") as f:
        json.dump(tasks, f, indent=2)

    print(f"Wrote {len(tasks)} pilot tasks to {out_path}")
    print(f"  {len(likely_commitment)} likely-commitment, {len(likely_not)} likely-not (mixed on purpose)")


if __name__ == "__main__":
    main()
