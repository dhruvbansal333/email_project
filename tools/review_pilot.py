import json
from collections import defaultdict

FILE = "data/pilot_30_export.json"

with open(FILE, encoding="utf-8") as f:
    data = json.load(f)

print("=" * 70)
print("PILOT ANNOTATION REVIEW")
print("=" * 70)

for task_num, task in enumerate(data, 1):

    results = []
    for annotation in task.get("annotations", []):
        results.extend(annotation.get("result", []))

    commitments = []
    metadata = defaultdict(dict)

    for r in results:
        value = r.get("value", {})
        frm = r.get("from_name")

        if frm == "commitment_span":
            commitments.append({
                "start": value.get("start"),
                "end": value.get("end"),
                "text": value.get("text", "").replace("\n", " "),
                "labels": value.get("labels", [])
            })

        elif frm in ["deadline_type", "confidence", "third_party_reported"]:
            key = (value.get("start"), value.get("end"))
            metadata[key][frm] = value.get("choices", [])

    if not commitments:
        print(f"\nTASK {task_num}: NO COMMITMENTS")
        continue

    print(f"\n{'='*70}")
    print(f"TASK {task_num} | Commitments: {len(commitments)}")
    print(f"{'='*70}")

    for i, c in enumerate(commitments, 1):
        key = (c["start"], c["end"])
        meta = metadata.get(key, {})

        print(f"\nCommitment #{i}")
        print(f"Text       : {c['text']}")
        print(f"Deadline   : {meta.get('deadline_type', 'MISSING')}")
        print(f"Confidence : {meta.get('confidence', 'MISSING')}")
        print(f"Third-party: {meta.get('third_party_reported', 'MISSING')}")

print("\n" + "=" * 70)
print("END REVIEW")
print("=" * 70)
