import json
from pathlib import Path

INPUT_FILE = Path("data/project-1-json.json")
OUTPUT_FILE = Path("data/commitments_raw.json")


with open(INPUT_FILE, "r", encoding="utf-8") as f:
    tasks = json.load(f)


records = []
unlinked = []


for task in tasks:
    task_id = task["id"]

    for annotation in task.get("annotations", []):
        results = annotation.get("result", [])

        # First collect actual commitment spans
        commitments = {}

        for r in results:
            if r.get("from_name") != "commitment_span":
                continue

            value = r.get("value", {})
            labels = value.get("labels", [])

            if not labels:
                continue

            commitment_id = r.get("id")

            commitments[commitment_id] = {
                "task_id": task_id,
                "text": value.get("text", ""),
                "start": value.get("start"),
                "end": value.get("end"),
                "direction": labels[0],
            }

        # Attach commitment-level attributes
        for commitment_id, record in commitments.items():

            found_attribute = False

            for r in results:
                if r.get("id") != commitment_id:
                    continue

                from_name = r.get("from_name")
                value = r.get("value", {})
                choices = value.get("choices", [])

                if not choices:
                    continue

                found_attribute = True

                if from_name == "deadline_type":
                    record["deadline_type"] = choices[0]

                elif from_name == "confidence":
                    record["confidence"] = choices[0]

                elif from_name == "third_party_reported":
                    record["third_party_reported"] = choices[0]

            if found_attribute:
                records.append(record)
            else:
                record["attribute_status"] = "unlinked"
                unlinked.append(record)


with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(records, f, indent=2, ensure_ascii=False)


print("Done!")
print("Total commitment spans:", len(records) + len(unlinked))
print("Clean records:", len(records))
print("Unlinked records:", len(unlinked))
print("Saved to:", OUTPUT_FILE)

if unlinked:
    print("\nUnlinked commitments:")
    for r in unlinked:
        print(
            f"Task {r['task_id']} | "
            f"{r['start']}:{r['end']} | "
            f"{r['text'][:100]}"
        )