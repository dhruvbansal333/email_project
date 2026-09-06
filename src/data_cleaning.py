"""
Step 2.2 — Clean the data.

- Strip email signatures, forwarded headers, legal disclaimers.
- Deduplicate repeated messages within threads.
- Apply basic anonymization (hash names/emails) even though the source
  data is public, as a demonstrated privacy-by-design practice.
- Group messages into pseudo-threads via normalized subject lines, since
  this CSV source doesn't carry explicit thread IDs (see note in
  data_acquisition.py).

Usage:
    python src/data_cleaning.py
"""

import hashlib
import re
from pathlib import Path

import pandas as pd
import spacy

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_PATH = DATA_DIR / "raw" / "enron_ham_raw.csv"
OUT_PATH = DATA_DIR / "cleaned" / "enron_ham_cleaned.csv"

# --- Regexes for stripping non-author content -----------------------------

FORWARD_HEADER_RE = re.compile(
    r"-{5,}\s*forwarded by.*?-{5,}", re.IGNORECASE | re.DOTALL
)
REPLY_HEADER_RE = re.compile(
    r"^(from|to|cc|subject|sent)\s*:.*$", re.IGNORECASE | re.MULTILINE
)
DISCLAIMER_MARKERS = [
    "this e-mail message may contain",
    "this message is intended only",
    "confidential and may also be privileged",
    "if you have received this",
]
SIGNOFF_RE = re.compile(
    r"\n(regards|thanks|best|cheers|sincerely|thank you)[,.]?\s*\n.{0,80}$",
    re.IGNORECASE | re.DOTALL,
)


def strip_forwarded_and_reply_headers(text: str) -> str:
    text = FORWARD_HEADER_RE.sub(" ", text)
    text = REPLY_HEADER_RE.sub(" ", text)
    return text


def strip_disclaimers(text: str) -> str:
    lowered = text.lower()
    for marker in DISCLAIMER_MARKERS:
        idx = lowered.find(marker)
        if idx != -1:
            text = text[:idx]
            lowered = text.lower()
    return text


def strip_signoff(text: str) -> str:
    return SIGNOFF_RE.sub("", text)


def clean_message(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = strip_forwarded_and_reply_headers(text)
    text = strip_disclaimers(text)
    text = strip_signoff(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def normalize_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes and normalize whitespace/case to group threads."""
    if not isinstance(subject, str):
        return ""
    s = re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", subject, flags=re.IGNORECASE)
    s = re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", s, flags=re.IGNORECASE)  # handle double prefixes
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def anonymize(text: str, nlp) -> str:
    """Hash email addresses and PERSON-tagged names detected by spaCy NER."""
    # Emails first (regex is reliable for this)
    def hash_email(match):
        return "user_" + hashlib.sha256(match.group(0).encode()).hexdigest()[:8] + "@anon"

    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", hash_email, text)

    # Names via spaCy NER (best-effort; not perfect on informal text)
    doc = nlp(text)
    spans = [(ent.start_char, ent.end_char) for ent in doc.ents if ent.label_ == "PERSON"]
    for start, end in sorted(spans, reverse=True):
        name = text[start:end]
        anon = "person_" + hashlib.sha256(name.encode()).hexdigest()[:6]
        text = text[:start] + anon + text[end:]
    return text


TARGET_THREADS = 750  # within the roadmap's 500-1,000 range


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(RAW_PATH)

    print("Cleaning message bodies...")
    df["message_clean"] = df["Message"].apply(clean_message)
    df = df[df["message_clean"].str.len() > 20]  # drop near-empty messages

    print("Deduplicating...")
    before = len(df)
    df = df.drop_duplicates(subset="message_clean")
    print(f"  Dropped {before - len(df)} exact-duplicate messages")

    print("Grouping into pseudo-threads by normalized subject...")
    df["thread_key"] = df["Subject"].apply(normalize_subject)
    df = df[df["thread_key"].str.len() > 0]

    print(f"Selecting a subset of ~{TARGET_THREADS} threads, favoring multi-message threads...")
    thread_sizes = df.groupby("thread_key").size().sort_values(ascending=False)
    # Favor threads with multiple messages, but don't exclude singletons
    # entirely — a mix keeps the dataset representative rather than
    # artificially skewed toward only the longest threads.
    multi_reply_keys = thread_sizes[thread_sizes > 1].index.tolist()
    singleton_keys = thread_sizes[thread_sizes == 1].index.tolist()
    selected_keys = multi_reply_keys[:int(TARGET_THREADS * 0.7)]
    remaining_slots = TARGET_THREADS - len(selected_keys)
    selected_keys += singleton_keys[:remaining_slots]
    df = df[df["thread_key"].isin(selected_keys)].reset_index(drop=True)
    print(f"  Selected {len(df)} messages across {df['thread_key'].nunique()} threads "
          f"({len(multi_reply_keys[:int(TARGET_THREADS*0.7)])} multi-reply, rest singleton)")

    print("Anonymizing selected subset (spaCy NER over each message)...")
    nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
    df["message_anon"] = df["message_clean"].apply(lambda t: anonymize(t, nlp))

    df.to_csv(OUT_PATH, index=False)
    print(f"Saved {len(df)} cleaned messages across {df['thread_key'].nunique()} pseudo-threads to {OUT_PATH}")


if __name__ == "__main__":
    main()
