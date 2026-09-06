"""
Phase 4, Step 4.2 prep — convert document-level gold commitments into a
BIO-tagged token classification dataset for fine-tuning.

Tag scheme (4 non-O labels, captures direction directly in the tag so
the model learns span + direction jointly, matching the extraction
target):
  O               — not part of a commitment
  B-MADE / I-MADE       — commitment the sender is making
  B-REQUESTED / I-REQUESTED — commitment the sender is requesting

deadline_type and confidence are NOT part of the token-tagging target —
those are handled as a lightweight second-stage classifier over the
extracted span in Step 4.2's ranking/explainability handoff, consistent
with the Phase 1 design doc's "extraction vs ranking" separation.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GOLD_DIR = DATA_DIR / "gold_set" / "v1"

LABELS = ["O", "B-MADE", "I-MADE", "B-REQUESTED", "I-REQUESTED"]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}


def char_span_to_bio(text, commitments):
    """Return a list of (char_start, char_end, tag) intervals, one per
    commitment, by locating commitment_text in the raw text via substring
    search (same approach used throughout Phase 3 for span verification)."""
    spans = []
    for c in commitments:
        needle = c["commitment_text"]
        idx = text.find(needle)
        if idx == -1:
            # try whitespace-normalized fallback
            import re
            norm_text = re.sub(r"\s+", " ", text)
            norm_needle = re.sub(r"\s+", " ", needle)
            norm_idx = norm_text.find(norm_needle)
            if norm_idx == -1:
                continue  # unresolvable, skip (rare — logged below)
            idx = norm_idx  # approximate; good enough for token alignment
            end = idx + len(norm_needle)
        else:
            end = idx + len(needle)
        tag_prefix = "MADE" if c["direction"] == "made" else "REQUESTED"
        spans.append((idx, end, tag_prefix))
    return spans


def simple_tokenize_with_offsets(text):
    """Whitespace tokenizer that tracks character offsets (BIO tags are
    assigned per whitespace token here; the actual transformer tokenizer
    will re-align to subwords at train time using word_ids())."""
    tokens = []
    offset = 0
    for tok in text.split():
        start = text.find(tok, offset)
        end = start + len(tok)
        tokens.append((tok, start, end))
        offset = end
    return tokens


def build_split(split_name):
    documents = json.load(open(GOLD_DIR / f"documents_{split_name}.json"))
    examples = []
    unresolved = 0

    for doc in documents:
        text = doc["text"]
        spans = char_span_to_bio(text, doc["commitments"])
        unresolved += len(doc["commitments"]) - len(spans)

        tokens_with_offsets = simple_tokenize_with_offsets(text)
        tokens = [t[0] for t in tokens_with_offsets]
        tags = ["O"] * len(tokens)

        for start, end, tag_prefix in spans:
            first = True
            for i, (tok, tstart, tend) in enumerate(tokens_with_offsets):
                if tend <= start or tstart >= end:
                    continue
                tags[i] = f"B-{tag_prefix}" if first else f"I-{tag_prefix}"
                first = False

        examples.append({
            "thread_id": doc["thread_id"],
            "tokens": tokens,
            "tags": tags,
        })

    out_path = GOLD_DIR / f"bio_{split_name}.json"
    with open(out_path, "w") as f:
        json.dump(examples, f, indent=2)

    n_commitment_tokens = sum(sum(1 for t in ex["tags"] if t != "O") for ex in examples)
    print(f"{split_name}: {len(examples)} examples, {n_commitment_tokens} commitment tokens, "
          f"{unresolved} commitments unresolved (span not found)")
    return examples


def main():
    for split in ["train", "val", "test"]:
        build_split(split)


if __name__ == "__main__":
    main()
