# Two small improvements: faster-feeling cold start + Gmail filter help

ONE file changes: app/frontend.py (dashboard only).
NOT changed: the API (app/main.py), database, login/auth, the Gmail script (proved byte-for-byte identical),
environment variables, deployment settings, INGESTION_SECRET, and your old Apps Script trigger.

## 1. Cold start
Cause of what you saw: on the login screen the dashboard sent ONE /health request (8 s timeout). That request
does wake the API, but the page then showed a static warning and never checked again. Streamlit doesn't re-run
by itself, so it stayed stuck until you forced a reload (e.g. after opening the API URL by hand).

Now, on the login screen:
1. "Contacting the server..." (one quick check; this alone wakes a sleeping API).
2. If it isn't answering yet: "Waking up the server... Ns so far" with live seconds. It re-checks every 3 s
   for up to 75 s (the existing WAKE_MAX_SECONDS / WAKE_POLL_SECONDS settings).
3. The moment it answers, the normal Log in / Sign up screen appears BY ITSELF, same page, no reload.
4. If it doesn't answer in time: a clear message + a Retry button. Log in / Sign up stay available (they already
   wake the server and retry themselves). Giving up is remembered, so clicking around doesn't restart a long
   wait; Retry starts a fresh bounded wait.
Paused demo, logged-in pages and all earlier cold-start handling behave as before.

What this CANNOT do (be honest with your evaluators):
- It doesn't make Render faster. Waking usually takes ~30-60 s and sometimes longer; the message says so.
- If the DASHBOARD service itself is asleep, Render shows its own waking page first and none of our code runs
  until it finishes. So a fully cold start can mean two waits one after the other (dashboard, then API).
  Only the second one is improved by this change.
- No uptime promise: after ~15 idle minutes the free services sleep again.
- Worst case before the Retry message appears is roughly 85 s (8 s first check + the 75 s wait).
- Before a demo, open BOTH services a couple of minutes ahead.

## 2. Gmail filter help (Connect Gmail page)
New collapsible section "Optional: label emails automatically with a Gmail filter", between step 3 and
"4. If something looks wrong". Four tabs:
1. Create the filter: beginner steps (Show search options, Search to preview, Create filter, Apply the label ->
   CommitmentAI-Send, optional "Also apply filter to matching conversations"), the "Filter messages like these"
   shortcut, and the note that a reply is only labeled if it also matches.
2. Search ideas: 9 copy-paste Gmail searches (promises, deadlines in text and subject, one sender, a few senders,
   a whole company, sender + keyword, skip promo noise, recent only) and how to read them. Warns to keep filters
   narrow (Gemini free tier + 30/day).
3. Test it: test the search first, create the filter, send a matching email, watch the label appear, wait for
   Done, Refresh the dashboard; apply a label by hand.
4. If it doesn't work: email not labeled / labeled but nothing on the dashboard / too many labeled; where to edit or
   delete a filter; how to re-send a conversation.
The steps follow Google's own Gmail help page. The key, script and install steps are untouched.

## Deploy
    git add app/frontend.py docs/improvements_guide.md
    git commit -m "Dashboard: auto-wake API with progress + Retry; Gmail filter help"
    git push origin main
Render rebuilds both services from the repo; nothing in the API changes. No new variables or packages.

## Live checks
1. Let both services sleep (15+ min). Open the dashboard URL. If Render shows its own waking page, that's normal.
2. When the login screen appears you should see "Contacting the server..." then "Waking up the server... Ns", then the
   login form appears on its own. You should NOT need to open the API URL.
3. Hit the give-up path if you can (e.g. reload during a slow wake): you should get the message + Retry, never a blank page.
4. Log in -> Connect Gmail: confirm the new section sits between step 3 and step 4 and the existing sections are intact.
   DO NOT press "Generate a new key" while testing: it would immediately stop your working Gmail script.
5. Optional: create a filter for a sender you control by following the guide, send a matching email, and confirm it gets
   CommitmentAI-Send, then Done, then appears on the dashboard.

## Rollback (dashboard only; no data, accounts, keys or Gmail script are affected)
A. Fastest, no code: Render -> dashboard service -> Deploys -> pick the last good deploy -> roll back / redeploy it
   (button wording varies by Render version).
B. Git: git revert <the commit above>  then  git push origin main
C. File: copy rollback/frontend_previous.py over app/frontend.py, commit, push. (It is byte-identical to the
   frontend.py in the Task 7 zip you deployed.)

## Tests
Before the change: 257 checks passed across 5 suites.
After: the same 5 suites pass, plus 52 new checks (309 in total), 0 failures.
- ONE existing assertion was updated, deliberately: it expected the old "starting up" warning when the API is down;
  that screen is now an error with a Retry button. Same intent (friendly message, no crash).
- New checks cover: API already awake (exactly one health call, no extra UI), API down (bounded wait, message, Retry,
  forms still usable), API waking mid-wait (continues by itself), a gateway 502 treated as "not ready yet", no re-wait
  after giving up, Retry both while down and after recovery, paused demo; and for Gmail: section order, the 4 tabs,
  required phrases, all 9 sample searches (balanced quotes/brackets, capital OR, example addresses only),
  the Gmail script byte-for-byte unchanged, the Connect Gmail page making exactly the same API calls as before,
  every old text block and heading still present, and key generation still working against the real API.
- I sabotaged the new code 6 ways (no polling, forgets it gave up, Retry doesn't reset, section dropped, typo in a
  sample search, script modified). All 6 were caught.
NOT tested here: real Render timings, Google's real Gmail screens, and the sample searches in a real mailbox (they were
syntax-checked, not run). Gmail's screens can change; the steps follow Google's help page as of now.
