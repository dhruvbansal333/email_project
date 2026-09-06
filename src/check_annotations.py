import json

with open("data/project-1-json.json", "r", encoding="utf-8") as f:
    data = json.load(f)

total = 0
linked = 0
unlinked = 0
emails_with_commitments = 0

for task in data:
    task_has_commitment = False

    for annotation in task.get("annotations", []):
        results = annotation.get("result", [])

        for r in results:
            if r.get("from_name") != "commitment_span":
                continue

            total += 1
            task_has_commitment = True

            commitment_id = r.get("id")

            has_linked_attribute = any(
                x.get("from_name") in [
                    "deadline_type",
                    "confidence",
                    "third_party_reported"
                ]
                and x.get("id") == commitment_id
                for x in results
            )

            if has_linked_attribute:
                linked += 1
            else:
                unlinked += 1

    if task_has_commitment:
        emails_with_commitments += 1


print("Commitment spans:", total)
print("With linked attributes:", linked)
print("Without linked attributes:", unlinked)
print("Emails with commitments:", emails_with_commitments)