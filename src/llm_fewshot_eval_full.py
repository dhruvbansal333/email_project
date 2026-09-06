import json
from pathlib import Path
import sys
sys.path.insert(0, "src")
from baseline_extraction import token_overlap_ratio

DATA_DIR = Path("data/gold_set/v1")

# Full 101-document few-shot LLM extraction, done by Claude reading every
# validation document directly (no fine-tuning, no gold labels consulted
# beforehand). Same commitment definition used throughout Phase 3: a
# promise ("made") or request ("requested") tied to a real future action;
# excludes FYI/status updates, past-tense completed actions, pleasantries.
LLM_PREDICTIONS_BY_THREAD = {
    "manual_7676": [
        {"text": "what i will try and attempt is keeping all weather data nearby", "direction": "made"},
        {"text": "can kevin order a tall file cabinet to put the material in", "direction": "requested"},
    ],
    "manual_1045": [
        {"text": "i will leave the choice to you all", "direction": "made"},
        {"text": "i will be back in town thursday night", "direction": "made"},
    ],
    "manual_13422": [
        {"text": "based on that conversation, i will be in a better position to direct you to some of the research", "direction": "made"},
        {"text": "let me know when a good time for me to call would be", "direction": "requested"},
    ],
    "manual_29061": [
        {"text": "i will send it to you if you want it", "direction": "made"},
        {"text": "i will try to find an accountant type at el paso", "direction": "made"},
    ],
    "manual_7105": [
        {"text": "please send comments and revisions", "direction": "requested"},
    ],
    "manual_16972": [
        {"text": "i will be in gig harbor for awhile, and can be reached at", "direction": "made"},
        {"text": "i will be moving to gig harbor on thursday and can be reached at", "direction": "made"},
    ],
    "manual_1586": [
        {"text": "we will be identifying what activities are being performed by your team, and shari will be talking about the automation of driver information", "direction": "made"},
    ],
    "manual_12974": [
        {"text": "brad and i will stay on top of it with mark and richard sanders", "direction": "made"},
        {"text": "ask taylor to email his", "direction": "requested"},
    ],
    "pilot_17035": [],
    "manual_12749": [
        {"text": "i will keep you posted", "direction": "made"},
        {"text": "i will keep you informed", "direction": "made"},
    ],
    "manual_8509": [
        {"text": "can you give me some background on bogdan", "direction": "requested"},
        {"text": "i will call you upon my return from europe", "direction": "made"},
        {"text": "in the meantime we will stay in touch via e-mail", "direction": "made"},
    ],
    "manual_12864": [
        {"text": "i will follow up on monday morning", "direction": "made"},
        {"text": "i will talk to y", "direction": "made"},
    ],
    "manual_11916": [
        {"text": "our plan is to sign the purchase and sale with black hills energy capital tonight / tomorrow morning", "direction": "made"},
    ],
    "manual_13384": [
        {"text": "please let me know if this is what you need", "direction": "requested"},
        {"text": "if you will let me know what to eliminate", "direction": "requested"},
        {"text": "i will make the necessary changes", "direction": "made"},
    ],
    "manual_14247": [
        {"text": "i will keep you up to date when i have additional information", "direction": "made"},
    ],
    "manual_7995": [
        {"text": "i will be checking my email regularly", "direction": "made"},
    ],
    "manual_23545": [
        {"text": "please continue to export your data as in the past", "direction": "requested"},
        {"text": "we will", "direction": "made"},
    ],
    "manual_289": [
        {"text": "also, we will sell you 500 mmbtu / d from fcv", "direction": "made"},
    ],
    "manual_5816": [
        {"text": "please, pay", "direction": "requested"},
        {"text": "please let me know who i should contact", "direction": "requested"},
        {"text": "i will take care of it", "direction": "made"},
    ],
    "manual_28266": [
        {"text": "effective immediately, joe jeffers", "direction": "made"},
    ],
    "manual_16751": [
        {"text": "i will provide a copy of his resume to his interviews for review", "direction": "made"},
    ],
    "manual_16883": [
        {"text": "i will maintain this spreadsheet", "direction": "made"},
        {"text": "please let me know if you have questions", "direction": "requested"},
    ],
    "pilot_6531": [
        {"text": "we will await your response to this email before initiating the", "direction": "made"},
        {"text": "we will also pdf certain energy analysis files to you", "direction": "made"},
    ],
    "manual_29134": [
        {"text": "i will not be here tomorrow but can be reached at", "direction": "made"},
    ],
    "manual_7223": [
        {"text": "please send me a short list of times you have available for a two hour meeting", "direction": "requested"},
    ],
    "manual_11705": [
        {"text": "i would appreciate your input", "direction": "requested"},
        {"text": "i will arrange a conference call with the legal and credit teams for monday", "direction": "made"},
    ],
    "manual_1833": [
        {"text": "i will try to get something to you to look at before i go but can make no guarantees", "direction": "made"},
        {"text": "please let me know where we stand", "direction": "requested"},
    ],
    "manual_11105": [
        {"text": "i will attempt to get you macro supply / demand info for eastern us by tommorow cob", "direction": "made"},
    ],
    "manual_7244": [
        {"text": "i will circulate this for review / correction later today, or, at the latest, monday", "direction": "made"},
    ],
    "manual_6915": [
        {"text": "i will be there at 11 : 30 am on friday, september 8, 2000", "direction": "made"},
        {"text": "please let me know what time would be convenient for you", "direction": "requested"},
    ],
    "manual_8120": [
        {"text": "we will take their model's interface and recode the calculation engine", "direction": "made"},
        {"text": "so i will spend the next 4 weeks working on this", "direction": "made"},
    ],
    "manual_14973": [
        {"text": "we will resolve the remaining full legal names on monday morning", "direction": "made"},
    ],
    "manual_14847": [
        {"text": "please let me know if you disagree", "direction": "requested"},
        {"text": "we will include small print along the lines of", "direction": "made"},
    ],
    "manual_9430": [
        {"text": "i will ask her to keep both you and houston hr informed of the situation", "direction": "made"},
    ],
    "manual_8006": [
        {"text": "we will make a short presentation of our activities and research interests", "direction": "made"},
    ],
    "manual_9481": [
        {"text": "can you resend your text document to vince asap", "direction": "requested"},
        {"text": "please, resend me the term papers of your group, each as a separate file", "direction": "requested"},
    ],
    "manual_16919": [
        {"text": "i will be avail", "direction": "made"},
    ],
    "manual_14775": [
        {"text": "great. let me know if i can provide any further help", "direction": "requested"},
        {"text": "we will work", "direction": "made"},
    ],
    "manual_23172": [
        {"text": "please send me your revisions by noon on friday, august 25th", "direction": "requested"},
        {"text": "if you foresee any problems meeting this deadline, please contact me to discuss", "direction": "requested"},
    ],
    "manual_404": [
        {"text": "we'll try next week", "direction": "made"},
    ],
    "manual_9410": [
        {"text": "my teammates and i would like to schedule a time with you to discuss our presentation materials", "direction": "requested"},
        {"text": "we will accommodate your schedules", "direction": "made"},
    ],
    "manual_15012": [
        {"text": "your thoughts would be appreciated", "direction": "requested"},
        {"text": "i will continue to review", "direction": "made"},
    ],
    "manual_6909": [
        {"text": "we will be inserting graphics into the report tomorrow", "direction": "made"},
    ],
    "manual_12005": [
        {"text": "if you have any changes / comments etc please let me know", "direction": "requested"},
        {"text": "i will be confirming these rotations", "direction": "made"},
        {"text": "bryce schneider will be starting in c. july 19th", "direction": "made"},
    ],
    "manual_5886": [
        {"text": "i wondered whether you could have a look at it and let me know what you think", "direction": "requested"},
        {"text": "i also wondered whether you would be interested in speaking at the course", "direction": "requested"},
        {"text": "i will give you a call on monday", "direction": "made"},
    ],
    "manual_14790": [
        {"text": "if you agree, we will capture the proposed changes on the attached form and fax it to ubs team", "direction": "made"},
        {"text": "if he agrees she will authorise the ubs team to produce the amended fo", "direction": "made"},
    ],
    "manual_3588": [
        {"text": "just a th", "direction": "requested"},
    ],
    "manual_14633": [
        {"text": "we do reserve the right to amend and or clarify this plan", "direction": "made"},
    ],
    "manual_23150": [
        {"text": "please let us know any comments or questions", "direction": "requested"},
    ],
    "manual_8310": [
        {"text": "i will need you to complete the attached visa questionnaire and return it to me", "direction": "requested"},
        {"text": "please send to my attention", "direction": "requested"},
    ],
    "manual_12442": [
        {"text": "docs to be exchanged again tonite", "direction": "made"},
        {"text": "trying to get date of ltr agt to be today", "direction": "made"},
    ],
    "manual_2926": [
        {"text": "when we receive the numbers from duke i will forward the true actual numbers to you", "direction": "made"},
    ],
    "manual_7067": [
        {"text": "i'll immediately start doing giuseppe's papers", "direction": "made"},
        {"text": "he said that he is happy to send the $100,000 for your program from his budget", "direction": "made"},
        {"text": "will try to follow up to make sure that the money is sent promptly", "direction": "made"},
    ],
    "manual_28999": [
        {"text": "we will determine capacity monday for the 18th gas day", "direction": "made"},
    ],
    "manual_12602": [
        {"text": "i will pass the info. along to ees to see if they have any interest in paying the $7 million for general advertising exposure", "direction": "made"},
    ],
    "manual_11676": [
        {"text": "we will now terminate the derivatives as the shares were sold", "direction": "made"},
    ],
    "pilot_5473": [
        {"text": "could you let me know when you are able to meet riskcare", "direction": "requested"},
        {"text": "i will try to reach you in houston", "direction": "made"},
        {"text": "otherwise i will give anjam's office a call tomorrow", "direction": "made"},
    ],
    "manual_23835": [
        {"text": "we will need cost codes to charge time etc to", "direction": "requested"},
        {"text": "is this ok with you", "direction": "requested"},
    ],
    "manual_13654": [
        {"text": "please advise", "direction": "requested"},
    ],
    "pilot_12446": [],
    "manual_7963": [
        {"text": "i will share with the group", "direction": "made"},
    ],
    "manual_1844": [
        {"text": "pat radford, my assistant, will be making arrangements for a meeting next week", "direction": "made"},
        {"text": "if there is an urgent issue that needs resolution before my return, please contact barbara gray", "direction": "requested"},
    ],
    "manual_11932": [
        {"text": "i will be circulating in the next few minutes a revised new albany analysis", "direction": "made"},
    ],
    "manual_7940": [
        {"text": "let me see what we can work out, vince, and we'll get back to you", "direction": "made"},
        {"text": "i shall send a message to them explaining that we try to identify the best fit", "direction": "made"},
    ],
    "manual_13440": [
        {"text": "if i can get more info. before our meeting, i will add it", "direction": "made"},
    ],
    "manual_14322": [
        {"text": "can you please send me a copy of any due diligence item that you have sent directly to a particular bidder", "direction": "requested"},
    ],
    "manual_906": [
        {"text": "i will enter in mops as estimates", "direction": "made"},
    ],
    "manual_28934": [
        {"text": "please forward the name(s) to dianne langeland by november 6th", "direction": "requested"},
        {"text": "she will contact the nominee(s) to see if he / she is willing to serve", "direction": "made"},
    ],
    "manual_11323": [
        {"text": "please include the phone numbers given by brian redmond from our meeting ea", "direction": "requested"},
    ],
    "manual_8031": [
        {"text": "if there are any problems with or questions concerning the grains report, please let me know", "direction": "requested"},
    ],
    "manual_22590": [
        {"text": "i'll search for any other related on monday morning", "direction": "made"},
        {"text": "please send it to me and ron baker", "direction": "requested"},
    ],
    "pilot_23671": [
        {"text": "please remember to contact your candidates", "direction": "requested"},
        {"text": "let me know if you have any questions", "direction": "requested"},
    ],
    "manual_12859": [
        {"text": "just to be clear i am expecting mike to let san antonio know today", "direction": "made"},
        {"text": "per your request, i will start providing a daily status report on the wind ppa mtm value", "direction": "made"},
    ],
    "manual_16979": [
        {"text": "we will be meeting at 6:00 pm in the hawthorne room", "direction": "made"},
        {"text": "please let me know if there are any changes to your availability", "direction": "requested"},
    ],
    "manual_8363": [
        {"text": "i will review their results and confirm", "direction": "made"},
    ],
    "manual_14093": [
        {"text": "feel fr", "direction": "requested"},
    ],
    "manual_8444": [
        {"text": "i can take her ino my group", "direction": "made"},
        {"text": "i will generate an offer letter as soon as i know this information", "direction": "made"},
        {"text": "i shall be glad to take her", "direction": "made"},
    ],
    "manual_6928": [
        {"text": "we are in touch with ketra and john and we shall work with them when they are here", "direction": "made"},
        {"text": "can you make arrangements with", "direction": "requested"},
    ],
    "manual_491": [
        {"text": "susan { @ 3 - 5796 } will back up jackie during my absence", "direction": "made"},
    ],
    "manual_22786": [
        {"text": "we will discuss this with our business risk managers sally beck and wes colwell", "direction": "made"},
        {"text": "if we could do the audit september 11 - 22, that would be best for us", "direction": "made"},
    ],
    "manual_3552": [
        {"text": "will you please review this spreadsheet and provide the state and county information", "direction": "requested"},
        {"text": "if you are not the scheduler for this pipe please forward this to the appropriate scheduler", "direction": "requested"},
    ],
    "pilot_2411": [],
    "manual_14286": [
        {"text": "will you please advise", "direction": "requested"},
        {"text": "we will still be able to reject the lease", "direction": "made"},
    ],
    "manual_13561": [
        {"text": "i will send you the entire november position as i understand it", "direction": "made"},
        {"text": "let me send you what i pieced together from joel bennett's position", "direction": "made"},
    ],
    "manual_7725": [
        {"text": "please email your lunch choice to me by monday, december 4, 2000", "direction": "requested"},
    ],
    "manual_13626": [
        {"text": "i will keep you posted", "direction": "made"},
        {"text": "i will find you if this appears to be ready to close", "direction": "made"},
    ],
    "manual_8187": [
        {"text": "the books will be shipped to both you and rice university tomorrow", "direction": "made"},
        {"text": "we will credit their account", "direction": "made"},
        {"text": "if you need anything further, please let me know", "direction": "requested"},
    ],
    "manual_8481": [
        {"text": "we shall try to arrange a video conference with houston when howard is back", "direction": "made"},
        {"text": "i'll track him and find when he is back", "direction": "made"},
        {"text": "i will inform alec and his manager what you want", "direction": "made"},
        {"text": "we shall continue talking to howard when he comes back from nyc", "direction": "made"},
        {"text": "i shall set up an interview with him", "direction": "made"},
    ],
    "manual_12750": [
        {"text": "i will keep you posted", "direction": "made"},
    ],
    "manual_7115": [
        {"text": "we will postone the \" good luck and best wishes \" party for grant", "direction": "made"},
    ],
    "manual_22572": [
        {"text": "please review and provide me with your comments, if any, by monday january 31st", "direction": "requested"},
    ],
    "manual_7040": [
        {"text": "let's talk in the near future to continue our conversation", "direction": "made"},
        {"text": "i will give sheila in hr a call and see if we can work out a contract", "direction": "made"},
    ],
    "manual_11422": [
        {"text": "they will be sending over details on monday", "direction": "made"},
        {"text": "let us know who we should work with on your team", "direction": "requested"},
        {"text": "we will be moving quickly on this", "direction": "made"},
    ],
    "manual_13573": [
        {"text": "don miller and his team are prepared to smile and dial on monday october 29, 2001", "direction": "made"},
    ],
    "manual_13931": [
        {"text": "we will attach a turbine loi to the epc loi", "direction": "made"},
    ],
    "manual_6488": [
        {"text": "i am sending you my presentations and would like to get back to you with some questions", "direction": "made"},
    ],
    "manual_2830": [
        {"text": "please add any items and forward back to me", "direction": "requested"},
        {"text": "i will update", "direction": "made"},
    ],
    "manual_8357": [
        {"text": "i would like to pass sharad's probationary period", "direction": "made"},
        {"text": "please can you let me know as soon as possible", "direction": "requested"},
        {"text": "if the probationary period is passed i will send out a letter", "direction": "made"},
    ],
    "manual_8846": [
        {"text": "i shall call you later today", "direction": "made"},
        {"text": "please send a real options binder to paul", "direction": "requested"},
    ],
    "manual_112": [
        {"text": "i will focus on january '2000", "direction": "made"},
        {"text": "if there are any scheduling issues you need my assistance on for nov. or dec. 1999, please let me know", "direction": "requested"},
        {"text": "i will be on vacation thursday and friday of this week", "direction": "made"},
    ],
    "manual_13818": [
        {"text": "can you let me know how you would prefer to manage this asap", "direction": "requested"},
    ],
}


def main():
    docs = json.load(open(DATA_DIR / "documents_val.json"))
    print(f"Loaded {len(docs)} validation documents")
    print(f"Predictions dict covers {len(LLM_PREDICTIONS_BY_THREAD)} threads")

    missing = [d["thread_id"] for d in docs if d["thread_id"] not in LLM_PREDICTIONS_BY_THREAD]
    if missing:
        print(f"WARNING: {len(missing)} threads missing predictions: {missing}")

    OVERLAP_THRESHOLD = 0.6
    tp, fp, fn = 0, 0, 0
    direction_correct, matched_gold_total = 0, 0

    for doc in docs:
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
        "n_documents": len(docs),
        "n_gold_commitments": sum(len(d["commitments"]) for d in docs),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "direction_accuracy_on_matches": direction_acc,
        "note": "Full 101-document validation set evaluation, done by Claude reading every document directly (no fine-tuning). Same matching methodology (token_overlap_ratio, >=60% threshold) as the Step 4.1 baseline for a fair comparison.",
    }

    print(json.dumps(results, indent=2))
    with open(DATA_DIR / "llm_fewshot_full_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {DATA_DIR / 'llm_fewshot_full_results.json'}")


if __name__ == "__main__":
    main()
