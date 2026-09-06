"""
Step 2.3 — Synthetic email thread generator.

Generates synthetic threads covering edge cases that are rare or hard to
find in the real Enron subset: implicit commitments, multiple deadlines,
vague/conditional promises, group commitments, recurring commitments, and
third-party-reported commitments (see the 5 open edge cases in
docs/annotation_guideline_draft.md).

Ground-truth labels are stored alongside the generated text at creation
time (per the roadmap's Step 2.3 checklist item: "don't regenerate later").

This script ships with a hand-authored SEED_THREADS set (10 threads, one
per edge case, including a true negative) as a starting point / quality
bar. Scaling to the full 150-250 threads is a matter of prompting an LLM
with the same schema and edge-case categories, generating several
variations per category, and reviewing the output against this seed set
for consistency, rather than writing 150+ threads by hand.

Usage:
    python src/synthetic_generator.py
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = DATA_DIR / "synthetic" / "synthetic_threads_v1.jsonl"

# Each thread: id, edge_case category, list of messages, and gold labels
# for each commitment present (matching the annotation guideline schema:
# sender, recipient, commitment_text, direction, deadline, deadline_type,
# confidence).

SEED_THREADS = [
    {
        "thread_id": "syn_001",
        "edge_case": "explicit_deadline",
        "messages": [
            {"from": "person_a", "to": "person_b",
             "text": "Hi, can you send the updated budget spreadsheet by Wednesday morning? Need it before the finance review."}
        ],
        "gold_commitments": [
            {"sender": "person_a", "recipient": "person_b",
             "commitment_text": "can you send the updated budget spreadsheet by Wednesday morning",
             "direction": "requested", "deadline": "Wednesday morning",
             "deadline_type": "explicit", "confidence": "high"}
        ],
    },
    {
        "thread_id": "syn_002",
        "edge_case": "implicit_commitment",
        "messages": [
            {"from": "person_c", "to": "person_d",
             "text": "Sure, leave it with me — I'll have something back to you before the trip."}
        ],
        "gold_commitments": [
            {"sender": "person_c", "recipient": "person_d",
             "commitment_text": "I'll have something back to you before the trip",
             "direction": "made", "deadline": "before the trip",
             "deadline_type": "implicit", "confidence": "medium"}
        ],
    },
    {
        "thread_id": "syn_003",
        "edge_case": "multiple_deadlines",
        "messages": [
            {"from": "person_e", "to": "person_f",
             "text": "I'll get you the draft slides by Friday, and then the final numbers once accounting closes the books on the 15th."}
        ],
        "gold_commitments": [
            {"sender": "person_e", "recipient": "person_f",
             "commitment_text": "I'll get you the draft slides by Friday",
             "direction": "made", "deadline": "Friday",
             "deadline_type": "explicit", "confidence": "high"},
            {"sender": "person_e", "recipient": "person_f",
             "commitment_text": "the final numbers once accounting closes the books on the 15th",
             "direction": "made", "deadline": "the 15th",
             "deadline_type": "explicit", "confidence": "high"},
        ],
    },
    {
        "thread_id": "syn_004",
        "edge_case": "vague_conditional",
        "messages": [
            {"from": "person_g", "to": "person_h",
             "text": "I'll follow up with legal once I hear back — might take a few days, will keep you posted either way."}
        ],
        "gold_commitments": [
            {"sender": "person_g", "recipient": "person_h",
             "commitment_text": "I'll follow up with legal once I hear back",
             "direction": "made", "deadline": None,
             "deadline_type": "implicit", "confidence": "medium"}
        ],
    },
    {
        "thread_id": "syn_005",
        "edge_case": "group_commitment",
        "messages": [
            {"from": "person_i", "to": "team",
             "text": "Good call today, everyone. Let's plan to have the migration wrapped up by end of month."}
        ],
        "gold_commitments": [
            {"sender": "person_i", "recipient": "team",
             "commitment_text": "let's plan to have the migration wrapped up by end of month",
             "direction": "requested", "deadline": "end of month",
             "deadline_type": "implicit", "confidence": "low",
             "note": "ambiguous group commitment — see Edge Case 1 in annotation guideline"}
        ],
    },
    {
        "thread_id": "syn_006",
        "edge_case": "recurring_commitment",
        "messages": [
            {"from": "person_j", "to": "person_k",
             "text": "I'll send the weekly status report every Monday morning going forward."}
        ],
        "gold_commitments": [
            {"sender": "person_j", "recipient": "person_k",
             "commitment_text": "I'll send the weekly status report every Monday morning",
             "direction": "made", "deadline": "every Monday morning",
             "deadline_type": "explicit", "confidence": "high",
             "note": "recurring — labeled once per guideline, not expanded into a series"}
        ],
    },
    {
        "thread_id": "syn_007",
        "edge_case": "third_party_reported",
        "messages": [
            {"from": "person_l", "to": "person_m",
             "text": "Sarah said she'd handle the invoices before the audit next week, so we should be covered."}
        ],
        "gold_commitments": [
            {"sender": "Sarah", "recipient": "person_m",
             "commitment_text": "she'd handle the invoices before the audit next week",
             "direction": "made", "deadline": "before the audit next week",
             "deadline_type": "explicit", "confidence": "medium",
             "note": "third-party reported commitment — sender field is the actual committer (Sarah), not the email author"}
        ],
    },
    {
        "thread_id": "syn_008",
        "edge_case": "weak_commitment",
        "messages": [
            {"from": "person_n", "to": "person_o",
             "text": "Thanks for flagging this. I'll take a look when I get a chance this week."}
        ],
        "gold_commitments": [
            {"sender": "person_n", "recipient": "person_o",
             "commitment_text": "I'll take a look when I get a chance this week",
             "direction": "made", "deadline": "this week",
             "deadline_type": "implicit", "confidence": "low"}
        ],
    },
    {
        "thread_id": "syn_009",
        "edge_case": "non_commitment_fyi",
        "messages": [
            {"from": "person_p", "to": "person_q",
             "text": "FYI, the report already went out yesterday. No action needed on your end."}
        ],
        "gold_commitments": [],
    },
    {
        "thread_id": "syn_010",
        "edge_case": "request_for_inaction",
        "messages": [
            {"from": "person_r", "to": "person_s",
             "text": "Please don't send the final version until I confirm with the client on Monday."}
        ],
        "gold_commitments": [
            {"sender": "person_r", "recipient": "person_s",
             "commitment_text": "don't send the final version until I confirm with the client on Monday",
             "direction": "requested", "deadline": "Monday",
             "deadline_type": "explicit", "confidence": "high",
             "note": "request for inaction / prohibitive — see Lampert et al. 2010"}
        ],
    },
]


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        for thread in SEED_THREADS:
            f.write(json.dumps(thread) + "\n")
    print(f"Wrote {len(SEED_THREADS)} seed synthetic threads to {OUT_PATH}")
    print("Scale to 150-250 threads by prompting an LLM with this same schema")
    print("and edge-case categories, then spot-check against these seeds.")


if __name__ == "__main__":
    main()
