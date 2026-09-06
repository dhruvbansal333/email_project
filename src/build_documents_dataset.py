"""
Phase 4, prep step — build document-level datasets pairing each thread's
FULL email text with its list of gold commitments. The gold_set/v1 files
only stored commitment-level records (no raw text); this reconstructs
the text from the Label Studio export and groups by thread, using
exactly the same train/val/test thread assignment already locked in
gold_train.json / gold_val.json / gold_test.json.
"""

import json
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EXPORT_PATH = DATA_DIR / "export" / "label_studio_export.json"
GOLD_DIR = DATA_DIR / "gold_set" / "v1"
OUT_DIR = DATA_DIR / "gold_set" / "v1"


def main():
    # thread_id -> full text, from the original export
    export = json.load(open(EXPORT_PATH))
    text_by_thread = {}
    for task in export:
        tid = task["data"].get("thread_id", str(task["id"]))
        text_by_thread[tid] = task["data"]["text"]

    print(f"Loaded text for {len(text_by_thread)} threads from export")

    for split in ["train", "val", "test"]:
        commitments = json.load(open(GOLD_DIR / f"gold_{split}.json"))
        by_thread = defaultdict(list)
        for c in commitments:
            by_thread[c["thread_id"]].append(c)

        documents = []
        missing_text = 0
        for tid, cs in by_thread.items():
            text = text_by_thread.get(tid)
            if text is None:
                missing_text += 1
                continue
            documents.append({
                "thread_id": tid,
                "text": text,
                "commitments": cs,
            })

        out_path = OUT_DIR / f"documents_{split}.json"
        with open(out_path, "w") as f:
            json.dump(documents, f, indent=2)

        print(f"{split}: {len(documents)} documents, {sum(len(d['commitments']) for d in documents)} commitments"
              + (f"  [{missing_text} threads had no matching text!]" if missing_text else ""))


if __name__ == "__main__":
    main()
