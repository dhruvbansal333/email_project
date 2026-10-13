# Multi-User Extension, Task 7: Connect Gmail (personal key + ready-made script)

Only app/frontend.py changes. The API is NOT touched: no new packages, no SQL, no new variables.
(apps_script/commitment_ai_gmail_template.gs is a reference copy of the script; it is not deployed.)

## What users get
A new sidebar page, "Connect Gmail":
1. Generate my Gmail key (shown ONCE; only a hash is stored; regenerating needs a confirm and kills the old script).
2. A script with their API URL and key already inside (copy button + .gs download). Before a key exists they
   see the same script with a placeholder, so they can read exactly what they'd be pasting.
3. A 6-step install guide (script.google.com -> paste -> run "setup" -> approve -> label emails).
4. A troubleshooting list.
The page is upfront about: what the app receives (only the text of emails YOU label, first 8,000 characters, plus
your key; never a Google password or token), Gemini free-tier data use, the "unverified app" screen, and Google's
broad Gmail permission wording.

## How the script behaves
- Opt-in per email: it only looks at threads you label CommitmentAI-Send (by hand, or via a Gmail filter).
- Every 5 minutes, at most 5 threads, newest message only, cut to 8,000 characters. Sends text only (no sender,
  subject, attachments).
- Success -> label CommitmentAI-Done (never sent twice).
- This email can never work (400/413/422) -> CommitmentAI-Failed immediately.
- The AI step failed for this email -> retried, counted; after 3 failures -> Failed (one bad email can't drain the
  30/day allowance).
- Not the email's fault (server asleep, daily limit, paused, rejected key, network) -> the run STOPS after the first
  call, nothing is labeled or counted, and it tries again next run. A rejected key logs "generate a new one".
- NEW: a lock stops two runs overlapping (timer + you pressing Run, or a slow run), which could send an email twice.
- setup() is safe to run again: creates the 3 labels and exactly ONE 5-minute timer.
- It only searches, reads and adds its own labels. Logs never contain email text or your key.

## Step 1: Deploy the dashboard
    git add app/frontend.py docs/task7_guide.md apps_script/commitment_ai_gmail_template.gs
    git commit -m "Multi-user Task 7: Connect Gmail page, personal-key script, overlap lock"
    git push origin main
Only the dashboard service needs it. Its API_URL must be the PUBLIC API URL (the page warns if it isn't).

## Step 2: Live test with YOUR Gmail (this part can only be tested for real on your side)
1. Log in. Open Connect Gmail. Click "Generate my Gmail key".
2. Click the copy icon on the script. Open script.google.com, New project (a NEW one; leave your old script alone
   for now), delete the placeholder, paste, Save.
3. Choose function "setup", Run, approve. Expect: "Google hasn't verified this app" (Advanced -> Go to ... -> Allow).
   Read the permission list. The log should say it created 3 labels, and Triggers (clock icon) shows ONE 5-minute timer.
4. In Gmail, label an email with the commitments in it: CommitmentAI-Send.
5. Wait up to 5 minutes. The thread gets CommitmentAI-Done. In the dashboard press Refresh: its commitments appear
   with Source "gmail".
6. Check the negatives: an UNlabeled email is never processed; a very long email (8,000+ characters) is processed
   (cut), not failed; a second poll doesn't resend anything.
7. Press Generate a new key (confirm). Your old script's next run must log that the key was rejected and label nothing.
   Paste the new script to recover.
8. Open the dashboard in a private window as a different user: they must NOT see your Gmail results.

## Step 3: Retire the old shared-key path (only after Step 2 works)
The old script (X-Ingestion-Key) writes to a shared in-memory store that no dashboard shows any more.
1. In the OLD Apps Script project: Triggers -> delete its trigger (or delete the project).
2. Render -> API service -> Environment -> DELETE INGESTION_SECRET. Also delete it from the dashboard service.
3. After the redeploy the API log says: "Legacy ingestion key disabled."
If you do step 2 before step 1, the old script just gets 401 every 5 minutes (harmless, noisy).

## What was tested (95 checks for this task; 257 across all suites, 0 failures)
- The EXACT script text, run in Node against a fake Gmail/Triggers/Storage: setup, opt-in, truncation, per-run cap,
  every error class, poison email, stop-on-first-failure, overlap lock, no secrets in logs, no mail-changing calls.
- End to end: the generated script (with a real key) -> the real API -> real Postgres -> the dashboard, including the
  real 413, real 429 and the revoked-key case.
- The page with Streamlit's test runner: key shown once, hash only stored, regenerate/cancel flows, key discarded when
  you leave the page or log out, hostile API URL can't break out of the script.
- I broke the script on purpose 17 different ways (wrong limit, hammering, leaking the key or email text, lock bugs...).
  The tests caught all 17.
NOT testable here: Google's real consent screens, triggers and quotas, real HTML-only emails, and a real cold start.

## Known limitations (for the report)
- Duplicates after a timeout: if the network drops or times out, the script can't know whether the server finished,
  so it retries; rarely that creates duplicate commitments and uses another daily slot. Chosen over silently losing one.
- Only the email body is sent, so the sender is often "I" or empty (the known sender limitation).
- The key sits inside the script text. Anyone who can read the script can read/write that user's commitments (not
  their Gmail). Regenerating the key revokes it.
- Google's Gmail permission for Apps Script is broad; the script is read-and-label only, but the grant is wide.
- Polling, not push: up to 5 minutes' delay; after a cold start the first poll may wait for the next run.
