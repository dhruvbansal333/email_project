import json
from pathlib import Path
import sys
sys.path.insert(0, "src")
from baseline_extraction import evaluate

DATA_DIR = Path("data/gold_set/v1")

# Predictions made by Claude (few-shot LLM baseline, Step 4.2) reading each
# of the 20 sampled validation documents directly and extracting commitment
# spans + direction, using the exact same schema as the Phase 3 annotation
# guideline. No fine-tuning, no gold labels seen beforehand for this pass.
LLM_PREDICTIONS_BY_THREAD = {
    "manual_15012": [
        {"text": "i will continue to review as this was thown together fairly quickly and i have not had the opportunity to carefully put all the pieces together", "direction": "made"},
        {"text": "your thoughts would be appreciated", "direction": "requested"},
    ],
    "manual_28266": [
        {"text": "we will be sending more information in the very near future", "direction": "made"},
    ],
    "manual_12442": [
        {"text": "docs to be exchanged again tonite", "direction": "made"},
        {"text": "we will agree to their change", "direction": "made"},
        {"text": "trying to get date of ltr agt to be today", "direction": "made"},
    ],
    "manual_13561": [
        {"text": "i will send you the entire november position as i understand it", "direction": "made"},
        {"text": "let me send you what i pieced together from joel bennett's position at cob last night", "direction": "made"},
    ],
    "manual_1586": [
        {"text": "we will be identifying what activities are being performed by your team, and shari will be talking about the automation of driver information", "direction": "made"},
    ],
    "manual_12749": [
        {"text": "i will keep you posted", "direction": "made"},
        {"text": "i will keep you informed", "direction": "made"},
    ],
    "manual_11323": [
        {"text": "please include the phone numbers given by brian redmond from our meeting earlier", "direction": "requested"},
        {"text": "if you have any further questions, please contact me or brian redmond", "direction": "requested"},
    ],
    "manual_11916": [
        {"text": "our plan is to sign the purchase and sale with black hills energy capital tonight/tomorrow morning", "direction": "made"},
        {"text": "i will update when something changes", "direction": "made"},
    ],
    "manual_3588": [
        {"text": "just a thought, let me know what you think", "direction": "requested"},
    ],
    "manual_8363": [
        {"text": "i will review their results and confirm", "direction": "made"},
    ],
    "manual_12974": [
        {"text": "brad and i will stay on top of it with mark and richard sanders", "direction": "made"},
        {"text": "ask taylor to email his opinion on this asap", "direction": "requested"},
    ],
    "manual_13440": [
        {"text": "if i can get more info before our meeting, i will add it", "direction": "made"},
    ],
    "manual_11105": [
        {"text": "i will attempt to get you macro supply/demand info for eastern us by tommorow cob", "direction": "made"},
    ],
    "manual_7105": [
        {"text": "please send comments and revisions", "direction": "requested"},
    ],
    "manual_12864": [
        {"text": "i will follow up on monday morning", "direction": "made"},
        {"text": "i will talk to you in the next days to see if you think i will make enough money for you", "direction": "made"},
    ],
    "manual_11676": [
        {"text": "we will now terminate the derivatives as the shares were sold", "direction": "made"},
    ],
    "manual_28999": [
        {"text": "we will determine capacity monday for the 18th gas day", "direction": "made"},
    ],
    "pilot_17035": [],  # personal party invite, no real commitment
    "manual_8120": [
        {"text": "we will take their model's interface and recode the calculation engine", "direction": "made"},
        {"text": "so i will spend the next 4 weeks working on this", "direction": "made"},
    ],
    "manual_22590": [
        {"text": "i'll search for any other related on monday morning", "direction": "made"},
        {"text": "please send it to me and ron baker", "direction": "requested"},
    ],
}


def main():
    sample = json.load(open(DATA_DIR / "llm_eval_sample.json"))

    # Monkey-patch: build a documents list where 'text' extraction is
    # replaced by our stored predictions, reusing evaluate()'s matching
    # logic exactly as used for the baseline.
    from baseline_extraction import token_overlap_ratio

    tp, fp, fn = 0, 0, 0
    direction_correct, matched_gold_total = 0, 0
    OVERLAP_THRESHOLD = 0.6

    for doc in sample:
        thread_id = doc["thread_id"]
        gold_commitments = doc["commitments"]
        predictions = LLM_PREDICTIONS_BY_THREAD.get(thread_id, [])

        matched_gold_idxs = set()
        for pred in predictions:
            best_match, best_score = None, 0.0
            for i, gold in enumerate(gold_commitments):
                if i in matched_gold_idxs:
                    continue
                score = token_overlap_ratio(pred["text"], gold["commitment_text"])
                if score > best_score:
                    best_score, best_match = score, i
            if best_match is not None and best_score >= OVERLAP_THRESHOLD:
                tp += 1
                matched_gold_idxs.add(best_match)
                if pred["direction"] == gold_commitments[best_match]["direction"]:
                    direction_correct += 1
                matched_gold_total += 1
            else:
                fp += 1
        fn += len(gold_commitments) - len(matched_gold_idxs)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    direction_acc = direction_correct / matched_gold_total if matched_gold_total else 0.0

    results = {
        "n_documents": len(sample),
        "n_gold_commitments": sum(len(d["commitments"]) for d in sample),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "direction_accuracy_on_matches": direction_acc,
        "note": "Evaluated on a 20-document random sample of the validation set (not the full 101), due to the cost of manual per-document LLM extraction. Same matching methodology (>=60% token overlap) as the Step 4.1 baseline for a fair comparison.",
    }

    print(json.dumps(results, indent=2))
    with open(DATA_DIR / "llm_fewshot_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
