# Multi-User Extension, Task 6: Dashboard with login / signup

Only ONE file changes: app/frontend.py. The API (app/main.py) is NOT touched, so nothing
needs to change on the API service, and there are no new packages or SQL.

## What a visitor sees now
- Not logged in: Log in / Sign up tabs (userid + password, no email). Sign-up shows a notice they
  must tick: no password reset, text goes to Google's Gemini API (free tier: Google may use it to
  improve products and human reviewers may read it), 7-day retention, 30 emails/day, demo project.
- Logged in: Dashboard (usage bar, paste/upload, Process, "Your commitments" table, Delete my data
  with a two-step confirm) and Account (userid, limits, Delete my account with password).
- Sidebar: who you are, Dashboard/Account, Log out.

## Behaviour changes you should know about BEFORE deploying
1. Gmail auto-ingestion output will NOT appear in the new dashboard until Task 7.
   Your current Gmail script still uses the old shared key and writes to the old shared in-memory
   store; the new dashboard shows only each logged-in user's own results. The script keeps running
   and won't error, but its results are invisible until Task 7 gives each user a personal API key.
   (Plan to do Task 7 right after this one.)
2. Refreshing the browser (or opening a new tab) logs you out. The login token lives only in that
   tab's Streamlit session: not in the URL, not in a cookie. This is the "no remember me" design.
3. The dashboard no longer sends or needs INGESTION_SECRET.
4. Your existing account (dhruv) works: just log in. Its Task 4 test results are still there
   (until the 7-day retention removes them).

## Step 1: Deploy
Replace app/frontend.py, then:
    git add app/frontend.py docs/task6_guide.md
    git commit -m "Multi-user Task 6: dashboard with login, signup, per-user results"
    git push origin main
Render redeploys both services (same repo). The dashboard service must keep API_URL set to your API
service's URL (it already is).

## Step 2: Live checks (browser; do the isolation test with a normal window + an incognito window)
1. Open the dashboard: you should see Log in / Sign up tabs. If the API was asleep, you may first see
   "The server is starting up..." (free hosting). Wait a moment and reload.
2. Sign up as a NEW test user (e.g. test_ui1). Read the notice, tick the box. You land on the Dashboard.
3. Paste an email, click Process: "Found N commitment(s)", the usage bar moves to 1 of 30, the table fills.
4. Upload a .txt file with an email in it and Process it. (The automated tests could NOT cover the
   file uploader, so please try it by hand.)
5. Paste 8,001+ characters: red error, Process disabled.
6. Isolation: in an incognito window sign up as test_ui2. The table must be EMPTY (not test_ui1's data).
7. Delete my data -> confirm -> table empties; the usage bar does NOT reset (by design).
8. Account page: try Delete my account with a WRONG password: "Incorrect password." and you stay logged in.
   Then with the right password: logged out, "account deleted" message. Logging in again must fail.
9. Log in as dhruv and confirm your earlier results are there.
10. Refresh the page: you should be logged out and see the login screen again.
11. Cold start: after the services have been idle ~15+ minutes, open the dashboard and log in. The first
    request may take up to a minute; you should get a spinner or a "server is starting up" message, not a crash.

## Step 3 (optional, do it with Task 7): remove the unused INGESTION_SECRET from the DASHBOARD service.
Keep it on the API service until Task 7 moves the Gmail script to a personal key.

## What was and wasn't tested
Tested (63 checks, real API + Postgres, headless Streamlit, Gemini stubbed): login/signup validation and
errors, session handling, expiry, per-user isolation across two live sessions, usage bar, limit and
too-long handling, two-step data deletion, account deletion (wrong password must not log you out), logout,
API unreachable, paused demo, token never rendered or placed in the URL/cookies.
NOT tested: the file uploader, how it looks, and real Render cold-start timing. Check those by hand (Step 2).

## Design notes for the report
- The dashboard never touches the database; every request goes through the API with a Bearer token.
- A 401 on a normal call means "session over" (back to login), but a 401 when deleting an account means
  "wrong password" and must NOT log the user out; these are handled differently on purpose.
- The usage bar and the sign-up notice make the limits visible BEFORE users hit them.
- Sign-up requires explicit acknowledgement of the no-recovery and Gemini free-tier data-use terms.
