"""
Step 3.4a — Parse the Label Studio export into a flat, commitment-level
dataset. Groups per-region result entries (labels + choices + textarea)
by their shared region id, and separately collects 'parties' spans
(sender/recipient/deadline-text) which are independent regions.
"""

import json
from pathlib import Path
from collections import defaultdict

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EXPORT_PATH = DATA_DIR / "export" / "label_studio_export.json"
OUT_PATH = DATA_DIR / "gold_set" / "v1" / "commitments_raw.json"


def parse_task(task):
    text = task["data"]["text"]
    thread_id = task["data"].get("thread_id", str(task["id"]))
    subject = task["data"].get("subject", "")

    annotation = task["annotations"][0]
    results = annotation["result"]

    # Group everything by region id
    by_id = defaultdict(dict)
    parties = []

    for r in results:
        from_name = r["from_name"]
        rid = r["id"]
        val = r["value"]

        if from_name == "commitment_span":
            by_id[rid]["commitment_text"] = val.get("text", "").strip()
            by_id[rid]["direction"] = (
                "made" if "COMMITMENT_MADE" in val.get("labels", []) else "requested"
            )
            by_id[rid]["start"] = val.get("start")
            by_id[rid]["end"] = val.get("end")
        elif from_name == "deadline_type" and "start" in val:
            # per-region choice (has start/end = tied to a specific span)
            by_id[rid]["deadline_type"] = val.get("choices", [None])[0]
        elif from_name == "confidence" and "start" in val:
            by_id[rid]["confidence"] = val.get("choices", [None])[0]
        elif from_name == "third_party_reported" and "start" in val:
            by_id[rid]["third_party_reported"] = val.get("choices", [None])[0] == "yes_see_edge_case_5"
        elif from_name == "notes" and "start" in val:
            by_id[rid]["notes"] = " ".join(val.get("text", []))
        elif from_name == "parties":
            label = val.get("labels", [None])[0]
            parties.append({
                "label": label,
                "text": val.get("text", "").strip(),
                "start": val.get("start"),
                "end": val.get("end"),
            })

    commitments = []
    for rid, fields in by_id.items():
        if "commitment_text" not in fields:
            continue  # orphan choice entry with no matching span, skip

        # attach nearest parties within/near this commitment's span (best-effort:
        # a party mention is "attached" if its span falls within +-100 chars of
        # the commitment span, a simple proximity heuristic)
        c_start, c_end = fields.get("start", 0), fields.get("end", 0)
        sender = recipient = deadline_text = None
        for p in parties:
            if p["start"] is None:
                continue
            near = (c_start - 150) <= p["start"] <= (c_end + 150)
            if not near:
                continue
            if p["label"] == "SENDER" and sender is None:
                sender = p["text"]
            elif p["label"] == "RECIPIENT" and recipient is None:
                recipient = p["text"]
            elif p["label"] == "DEADLINE_TEXT" and deadline_text is None:
                deadline_text = p["text"]

        commitments.append({
            "thread_id": thread_id,
            "subject": subject,
            "commitment_text": fields.get("commitment_text"),
            "direction": fields.get("direction"),
            "deadline_type": fields.get("deadline_type", "none"),
            "deadline_text": deadline_text,
            "confidence": fields.get("confidence", "medium"),
            "third_party_reported": fields.get("third_party_reported", False),
            "notes": fields.get("notes"),
            "sender": sender,
            "recipient": recipient,
        })

    return text, commitments


def main():
    tasks = json.load(open(EXPORT_PATH))
    print(f"Loaded {len(tasks)} tasks from export")

    all_commitments = []
    zero_commitment_threads = 0
    for task in tasks:
        text, commitments = parse_task(task)
        if not commitments:
            zero_commitment_threads += 1
        all_commitments.extend(commitments)

    print(f"Parsed {len(all_commitments)} total commitments")
    print(f"{zero_commitment_threads} threads had zero commitments")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(all_commitments, f, indent=2)
    print(f"Saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
