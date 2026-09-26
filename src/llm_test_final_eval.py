import json
import sys
from pathlib import Path
sys.path.insert(0, "src")
from baseline_extraction import token_overlap_ratio

DATA_DIR = Path("data/gold_set/v1")

# Final test-set predictions. Test set touched exactly once, per the
# roadmap's cross-phase discipline rule ("Do not touch the test set until
# Phase 6"). Extracted by Claude reading each of the 103 test documents
# directly, same schema as all prior extraction work (Phase 3 labeling,
# Phase 4 validation-set evaluation).
LLM_PREDICTIONS_BY_THREAD = {
    "manual_7780": [{"text": "if not , i will call", "direction": "made"}],
    "manual_13328": [{"text": "i will finalize the hotel and departure times for travel tomorrow", "direction": "made"}],
    "manual_8275": [{"text": "we will send you a list of your team members via email with a hard copy to follow", "direction": "made"}],
    "manual_11038": [{"text": "please feel free to contract my team for questions", "direction": "requested"}],
    "manual_2031": [
        {"text": "just as soon as you can get that to me i will be able to get out a revised draft", "direction": "made"},
        {"text": "can you get me the specifics on the consumer price index", "direction": "requested"},
    ],
    "manual_13542": [{"text": "i will call you shortly", "direction": "made"}],
    "manual_23038": [
        {"text": "would 8.30 am this morning suit you to connect with john over the phone?", "direction": "requested"},
        {"text": "please let me know if this suits you", "direction": "requested"},
        {"text": "sure sally - i will ask lauren to set up a a time", "direction": "made"},
        {"text": "i will call you tomorrow", "direction": "made"},
    ],
    "manual_2443": [],
    "manual_8224": [
        {"text": "please give me some dates and times of your availability during the rest of january", "direction": "requested"},
        {"text": "i will try to coordinate them with our schedule", "direction": "made"},
    ],
    "manual_12811": [{"text": "we will keep you posted on further details as they become available", "direction": "made"}],
    "manual_15": [
        {"text": "could you please resolve this issue for howard", "direction": "requested"},
        {"text": "when this is done , please let george know", "direction": "requested"},
        {"text": "please let me know when this is resolved . we need it resolved by friday , dec 17", "direction": "requested"},
    ],
    "manual_3638": [{"text": "we will be killing about 2000 deals in sitara tonight", "direction": "made"}],
    "manual_11613": [{"text": "i will send your a manual entrust form to your home address for you to complete if necessary", "direction": "made"}],
    "manual_12616": [{"text": "i will advise m3 management that we will not be participating", "direction": "made"}],
    "manual_11395": [{"text": "we can further breakdown the hpl and lrc assets into the components that lydecker is breaking them into by friday", "direction": "made"}],
    "manual_28752": [{"text": "you can call me at 713 856 6525 and i will fax the information to you", "direction": "made"}],
    "manual_3075": [{"text": "we will run the base gas roll tonight per your request", "direction": "made"}],
    "manual_23993": [
        {"text": "please send the list to me and copy mark lindsey", "direction": "requested"},
        {"text": "please begin the process of identifying those employees in each job function", "direction": "requested"},
    ],
    "manual_11100": [{"text": "i will do it in the interim", "direction": "made"}],
    "manual_13198": [{"text": "can you tell me if you have made any progress re : resource allocation for bill bradford ' s credit group", "direction": "requested"}],
    "manual_1268": [
        {"text": "he will be sending revisions this afternoon for all other pipes", "direction": "made"},
        {"text": "i will furnish revised devon volumes this afternoon", "direction": "made"},
    ],
    "manual_2923": [{"text": "when we receive the numbers from duke i will forward the true actual numbers to you", "direction": "made"}],
    "manual_3465": [
        {"text": "i will image it with windows 2000 unless you need nt 4.0", "direction": "made"},
        {"text": "can you provide me with the following information so i can start imaging your pc", "direction": "requested"},
    ],
    "manual_7916": [{"text": "should you have any questions , or need to run different scenarios , please call me at home", "direction": "requested"}],
    "manual_23737": [{"text": "let me know if you have any questions", "direction": "requested"}],
    "manual_437": [
        {"text": "i will update the counterparty records with the new legal names tomorrow", "direction": "made"},
        {"text": "copies of the documents will be sent out this afternoon", "direction": "made"},
    ],
    "manual_11269": [
        {"text": "i will talk to some bankers", "direction": "made"},
        {"text": "i will have a short presentation for the meeting", "direction": "made"},
    ],
    "manual_14109": [
        {"text": "please let me know if you guys are still willing to do 3 - way offsets", "direction": "requested"},
        {"text": "if not we will still take it", "direction": "made"},
    ],
    "manual_23635": [{"text": "nancy and i will work with debbie / some in credit to determine physical / financial guidelines", "direction": "made"}],
    "manual_27779": [
        {"text": "please provide me with a summary of any type of transport options", "direction": "requested"},
        {"text": "i will incorporate these transport options into a capacity spreadsheet", "direction": "made"},
        {"text": "please try to forward this information to me at your earliest convenience", "direction": "requested"},
    ],
    "manual_17254": [{"text": "if you have any questions , please stop by my", "direction": "requested"}],
    "manual_526": [{"text": "i ' ll just have to call you when i can spare the time", "direction": "made"}],
    "manual_14714": [
        {"text": "it was mailed here so i will keep an eye out for it", "direction": "made"},
        {"text": "i will keep on top of it", "direction": "made"},
    ],
    "manual_7410": [
        {"text": "i will be making a request for additional resources", "direction": "made"},
        {"text": "can we aim for week commencing 6th november?", "direction": "requested"},
        {"text": "would you like to teleconference in?", "direction": "requested"},
    ],
    "manual_3509": [{"text": "we need to keep coordinated on these discussions", "direction": "made"}],
    "manual_6633": [
        {"text": "please let me know if clayton does not honor his commitment", "direction": "requested"},
        {"text": "if he fails , i will take the necessary steps", "direction": "made"},
    ],
    "manual_5967": [
        {"text": "please note to hand in the following by no later than april 24", "direction": "requested"},
        {"text": "it is urgent that all your materials be sent by this monday", "direction": "requested"},
    ],
    "manual_530": [
        {"text": "we will need 120 - 125 bbtu / day of fuel gas for the month of april", "direction": "made"},
        {"text": "we will bring down our gas turbine generator on sunday morning", "direction": "made"},
    ],
    "manual_12769": [{"text": "we will be staying in contact throughout the evening", "direction": "made"}],
    "manual_7176": [{"text": "if you would like to do something special for our boss , please inform me", "direction": "requested"}],
    "manual_6059": [{"text": "i will have to remove the extensions from those offices", "direction": "made"}],
    "manual_28466": [
        {"text": "we will serve breakfast in the tw commercial area on thursday 2 / 9 at 8 : 15 am", "direction": "made"},
        {"text": "please join us in congratulating lorraine", "direction": "requested"},
        {"text": "pilar and india , please forward to all of your people", "direction": "requested"},
    ],
    "manual_14721": [{"text": "please let me know if there is anyone at ubs whom you would like me to chase", "direction": "requested"}],
    "manual_16888": [{"text": "we will keep you posted", "direction": "made"}],
    "manual_22683": [
        {"text": "please be prepared to discuss your numbers at that time", "direction": "requested"},
        {"text": "i will bring a spreadsheet summarizing the information to the staff meeting", "direction": "made"},
    ],
    "manual_23004": [
        {"text": "please review and let me know if i have missed anything", "direction": "requested"},
        {"text": "we will be soliciting london ' s input / comments via conference call tomorrow", "direction": "made"},
    ],
    "manual_14329": [{"text": "please contact me directly to discuss how we coordinate canada into your respective retention process", "direction": "requested"}],
    "manual_3213": [{"text": "i will send out pictures later", "direction": "made"}],
    "manual_3091": [{"text": "we will create and submit committed reserves firm tickets for the remaining term of the deals", "direction": "made"}],
    "manual_14914": [{"text": "tomorrow we will be having a quick 15 min phone conference to update mike hutchins on status", "direction": "made"}],
    "manual_177": [{"text": "i will alert you of any revisions as they arise", "direction": "made"}],
    "manual_6242": [
        {"text": "if this is going to be a problem please let me know", "direction": "requested"},
        {"text": "on which date i will be putting the presentation pack together to send to the printers", "direction": "made"},
        {"text": "could you please email it to ldeathridge @ risk . co . uk as a powerpoint file asap", "direction": "requested"},
        {"text": "i will reply to any queries when i return", "direction": "made"},
    ],
    "manual_6005": [
        {"text": "i will call you in about an hour to make sure you received it", "direction": "made"},
        {"text": "let me know when you would like to meet him", "direction": "requested"},
    ],
    "manual_5552": [{"text": "samer will attend", "direction": "made"}],
    "manual_6622": [
        {"text": "please plan to attend a revenue management science kick - off meeting", "direction": "requested"},
        {"text": "we will send out an agenda prior to the meeting", "direction": "made"},
        {"text": "please call kim watson at 713 - 853 - 3098 , by friday , august 18 , if you are unable to attend", "direction": "requested"},
    ],
    "manual_23548": [{"text": "we will implement the steps agreed", "direction": "made"}],
    "manual_16626": [{"text": "if you have any questions , please let me or amy know", "direction": "requested"}],
    "manual_7275": [{"text": "i will have to go to german consulate tomorrow morning", "direction": "made"}],
    "manual_7432": [{"text": "please confirm as i presume anjam is waiting until the last possible minute to accept", "direction": "requested"}],
    "manual_7168": [
        {"text": "please forward me a copy of your resume , as soon as possible", "direction": "requested"},
        {"text": "i will have our hr dept . contact you", "direction": "made"},
    ],
    "manual_11625": [{"text": "please send any comments to me at your earliest convenience", "direction": "requested"}],
    "manual_9341": [
        {"text": "please let me know where you would like to go", "direction": "requested"},
        {"text": "i will make reservations", "direction": "made"},
    ],
    "manual_23386": [{"text": "i will forward any updates as they become available", "direction": "made"}],
    "manual_24026": [
        {"text": "we need to send this list to aep to ensure they agree", "direction": "made"},
        {"text": "we will complete the identification and inventory report of records to be turned over by close of business thursday , april 26 , 2001", "direction": "made"},
        {"text": "we will continue to track and monitor the location of these records", "direction": "made"},
    ],
    "manual_2692": [{"text": "i will be out of the office monday and will update the volumes on tuesday", "direction": "made"}],
    "manual_11153": [{"text": "i will let you know if i hear anything else", "direction": "made"}],
    "manual_11589": [
        {"text": "i will be taking over the weekly hotlist from marlene cameron", "direction": "made"},
        {"text": "can you respond to me via e - mail once the above request has been addressed?", "direction": "requested"},
    ],
    "manual_8299": [
        {"text": "please contact the wharton webcafe team", "direction": "requested"},
        {"text": "we will be happy to assist you", "direction": "made"},
    ],
    "manual_23828": [
        {"text": "please let us know if this is ok with you", "direction": "requested"},
        {"text": "we will announce it accordingly", "direction": "made"},
    ],
    "manual_8480": [
        {"text": "we shall invite howard to visit our office in london again", "direction": "made"},
        {"text": "i will get alec to have howard available for you upon arrive back from his holiday", "direction": "made"},
        {"text": "let me know if this is what you want", "direction": "requested"},
    ],
    "manual_14612": [{"text": "should i plan on just getting access to reuters and setting a curve off of libor on my own?", "direction": "requested"}],
    "manual_6373": [
        {"text": "please , let me know what time would work for you", "direction": "requested"},
        {"text": "i will be returning to houston during the week of july 10", "direction": "made"},
    ],
    "manual_23140": [{"text": "would you please make sure we get the following reports as soon as possible", "direction": "requested"}],
    "manual_11065": [
        {"text": "for our discussion this afternoon we will use the first and third files", "direction": "made"},
        {"text": "let me know if you need anything else for your next week presentation", "direction": "requested"},
    ],
    "pilot_8905": [{"text": "if you could please give me some feedback ( either positive or negative ) as soon as possible", "direction": "requested"}],
    "manual_13685": [{"text": "i will not move to get with john until you approve", "direction": "made"}],
    "manual_8439": [{"text": "i will be happy to help you get in touch with those interested", "direction": "made"}],
    "manual_9301": [{"text": "hopefully while in london i will have time to work on it some more", "direction": "made"}],
    "manual_23337": [
        {"text": "the warwick is sending me a contract that should be here before the end of the week", "direction": "made"},
        {"text": "i will need to meet with sally sometime on friday or monday", "direction": "made"},
        {"text": "if you need me to send out invitations , please let me know", "direction": "requested"},
    ],
    "manual_16602": [{"text": "let me know if you want to go", "direction": "requested"}],
    "manual_13197": [
        {"text": "can you tell me if you have made any progress re : resource allocation for bill bradford ' s credit group", "direction": "requested"},
        {"text": "both of whom recognized the issue and said they would try to address it", "direction": "made"},
    ],
    "manual_14282": [
        {"text": "if you have any comments , please send them to me by 9 : 00 a . m . on friday", "direction": "requested"},
        {"text": "if you have an objection to sending the letter , please call steve kean , mark palmer or me", "direction": "requested"},
    ],
    "manual_11186": [
        {"text": "i will be consulting colleen and geoff for any necessary revision", "direction": "made"},
        {"text": "i will be requesting signatures on wednesday afternoon , march 21", "direction": "made"},
        {"text": "please could we pull together the format inception document this week", "direction": "requested"},
    ],
    "pilot_2883": [],
    "manual_16863": [{"text": "could you send out an announcement on monday announcing john to the floor", "direction": "requested"}],
    "manual_7886": [
        {"text": "please , discontinue credit and renew the two other publications", "direction": "requested"},
        {"text": "we will be happy to renew your subscription to risk", "direction": "made"},
        {"text": "i would appreciate your responding by december 18th", "direction": "requested"},
        {"text": "if you wish to renew these , we will also take care of this for you", "direction": "made"},
    ],
    "manual_12711": [
        {"text": "how about i invite jay on monday?", "direction": "requested"},
        {"text": "flex deal viewer coming along , probably done by the end of the month", "direction": "made"},
        {"text": "going to talk to zie about sitara reliability", "direction": "made"},
    ],
    "manual_54": [{"text": "i will let you know as soon as unify is available", "direction": "made"}],
    "manual_22662": [{"text": "we will have ej phone numbers by monday", "direction": "made"}],
    "manual_5513": [{"text": "we will follow up with this lsu graduate", "direction": "made"}],
    "manual_12243": [{"text": "i will talk to george", "direction": "made"}],
    "manual_23602": [
        {"text": "since i will be in the meeting as well , i can speak up when details need to get hashed out", "direction": "made"},
        {"text": "let me know if i can help", "direction": "requested"},
    ],
    "manual_3636": [
        {"text": "therefore , we request the deals be zeroed out", "direction": "requested"},
        {"text": "we would appreciate further details on why these deals are being killed", "direction": "requested"},
        {"text": "we will be killing about 2000 deals in sitara tonight", "direction": "made"},
    ],
    "manual_14389": [{"text": "for the remainder of this week until my resignation date , i will continue to do my best to wrap - up loose ends", "direction": "made"}],
    "manual_22697": [
        {"text": "i will ask her this evening which night she can stay", "direction": "made"},
        {"text": "i will call or email you tomorrow with a definite", "direction": "made"},
        {"text": "brent price and i will be in the london office next week", "direction": "made"},
    ],
    "manual_14950": [{"text": "i ' m keen to get this communication out to the company by monday morning", "direction": "made"}],
    "manual_6827": [
        {"text": "please , give me a call when you get here", "direction": "requested"},
        {"text": "i shall be glad to meet with you", "direction": "made"},
    ],
    "manual_24028": [
        {"text": "we will complete the identification and inventory report of records to be turned over by close of business thursday , april 26 , 2001", "direction": "made"},
        {"text": "we will continue to track and monitor the location of these records", "direction": "made"},
        {"text": "please call me if you need further clarification", "direction": "requested"},
    ],
    "manual_28911": [
        {"text": "please contact nesa headquarters", "direction": "requested"},
        {"text": "we will be happy to fax or mail the information to your attention", "direction": "made"},
    ],
    "manual_792": [
        {"text": "please supply these savings where your name is listed", "direction": "requested"},
        {"text": "i will need your replies by cob may 31st", "direction": "requested"},
    ],
    "pilot_22667": [],
    "manual_14588": [{"text": "let me know your thoughts", "direction": "requested"}],
    "manual_851": [{"text": "if you have any questions before i leave , just let me know", "direction": "requested"}],
}


def main():
    docs = json.load(open(DATA_DIR / "documents_test.json"))
    print(f"Loaded {len(docs)} test documents")
    pred_ids = set(LLM_PREDICTIONS_BY_THREAD.keys())
    doc_ids = set(d["thread_id"] for d in docs)
    assert pred_ids == doc_ids, f"Mismatch! Missing: {doc_ids - pred_ids}, Extra: {pred_ids - doc_ids}"
    print("Predictions dict covers all test documents exactly.")

    OVERLAP_THRESHOLD = 0.6
    tp, fp, fn = 0, 0, 0
    direction_correct, matched_gold_total = 0, 0
    errors = []  # for qualitative error analysis

    for doc in docs:
        thread_id = doc["thread_id"]
        gold_commitments = doc["commitments"]
        predictions = LLM_PREDICTIONS_BY_THREAD[thread_id]

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
                else:
                    errors.append({
                        "type": "direction_mismatch", "thread_id": thread_id,
                        "predicted": pred["text"], "predicted_direction": pred["direction"],
                        "gold": gold_commitments[best_match]["commitment_text"],
                        "gold_direction": gold_commitments[best_match]["direction"],
                    })
                matched_gold_total += 1
            else:
                fp += 1
                errors.append({"type": "false_positive", "thread_id": thread_id, "predicted": pred["text"]})

        for i, gold in enumerate(gold_commitments):
            if i not in matched_gold_idxs:
                fn += 1
                errors.append({"type": "false_negative", "thread_id": thread_id, "missed_gold": gold["commitment_text"]})

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    direction_acc = direction_correct / matched_gold_total if matched_gold_total else 0.0

    results = {
        "n_documents": len(docs),
        "n_gold_commitments": sum(len(d["commitments"]) for d in docs),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "direction_accuracy_on_matches": direction_acc,
        "note": "FINAL TEST SET evaluation (touched once, per roadmap discipline rule). Full 103-document test set. Same matching methodology as Step 4.1 baseline and full-validation-set evaluation.",
    }

    print(json.dumps(results, indent=2))
    with open(DATA_DIR / "llm_test_final_results.json", "w") as f:
        json.dump(results, f, indent=2)
    with open(DATA_DIR / "test_error_analysis_raw.json", "w") as f:
        json.dump(errors, f, indent=2)
    print(f"\n{len(errors)} total errors logged for qualitative analysis")
    print(f"  false_positive: {sum(1 for e in errors if e['type']=='false_positive')}")
    print(f"  false_negative: {sum(1 for e in errors if e['type']=='false_negative')}")
    print(f"  direction_mismatch: {sum(1 for e in errors if e['type']=='direction_mismatch')}")


if __name__ == "__main__":
    main()
