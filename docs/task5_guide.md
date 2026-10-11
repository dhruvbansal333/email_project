# Multi-User Extension, Task 5: Limits, retention, kill-switch

Only app/main.py changes. No new packages, no SQL, no required environment variables
(the defaults below are the roadmap's numbers).

## What it enforces (all on the server, so it holds for any client)
| Protection | Default | What happens |
|---|---|---|
| Text length | 8,000 characters per email | 413, before anything is spent |
| Daily limit | 30 emails per user per day (UTC) | 429 + Retry-After; resets at 00:00 UTC |
| Stored results | newest 200 per user | oldest dropped automatically |
| Retention | 7 days | hidden from reads at once; deleted by an hourly sweep |
| Kill-switch | KILL_SWITCH=on | pauses processing + signups; users can still log in, view, delete |
| GET /usage | - | used today / limits, for the dashboard |

Details worth knowing:
- Order of checks on /process: credentials -> paused? -> length -> Gemini configured -> daily slot -> Gemini.
  A request that is rejected earlier never uses a daily slot or any Gemini quota.
- The daily slot is claimed in ONE atomic SQL statement. 20 simultaneous requests against a limit of 5
  let exactly 5 through (tested).
- Session and API key share one counter (same account). /extract counts too.
- A Gemini failure (502) still counts, because it spent quota.
- The legacy owner path (X-Ingestion-Key) is not counted against a daily limit, but it does get the
  8,000-character cap.
- "Delete after 7 days": expired rows are never returned by /results, and are physically deleted by a sweep
  that runs at startup and then at most hourly, triggered by ANY user's request (so an inactive user's old
  data is still cleaned up). A sleeping service can't sweep; the data is hidden but stays until the next use.
- A failing sweep is logged and ignored; it can never break a real request.
- Overrides (Render -> API service -> Environment), all optional:
  MAX_TEXT_CHARS, DAILY_LIMIT_PER_USER, RESULT_RETENTION_DAYS, MAX_RESULTS_PER_USER, KILL_SWITCH.
  Invalid values (abc, 0, -5) silently fall back to the default.

## Step 1: Two 30-second checks on the CURRENT deployment first (Task 4 gaps)
You never used an API key to call /process or /results live, and the Neon hash check wasn't shown.
    $hk2 = @{ "X-API-Key" = $k2.api_key }
    Invoke-RestMethod -Method Post -Uri "$api/process" -Headers $hk2 -ContentType $j -Body $text | Out-Null
    (Invoke-RestMethod -Uri "$api/results" -Headers $ha).results.Count     # was 2 -> expect 4
    (Invoke-RestMethod -Uri "$api/results" -Headers $hk2).results.Count    # same number: key and login = same account
(If your PowerShell window was closed and $k2 is gone: $k2 = Invoke-RestMethod -Method Post -Uri "$api/apikey" -Headers $ha)
In Neon SQL Editor:
    SELECT user_id, length(key_hash) AS len, left(key_hash,4) AS starts FROM api_keys;
Expect len = 64 and starts is NOT "cai_" (only a hash is stored).

## Step 2: Deploy
Replace app/main.py, then:
    git add app/main.py
    git commit -m "Multi-user Task 5: limits, retention, kill-switch"
    git push origin main
After the API service goes Live, check:
- <api-url>/health  ->  "paused": false
- API logs contain:  Limits: 8000 chars/email, 30 emails/user/day, 7-day retention, 200 results/user. Kill-switch: off.

## Step 3: Live tests (PowerShell; reuse $api, $j, $ha, Status from before)
a) Usage:
    Invoke-RestMethod -Uri "$api/usage" -Headers $ha
   expect used_today, daily_limit 30, max_text_chars 8000, retention_days 7, max_results 200, paused False
b) Length cap (costs no Gemini quota, rejected first):
    $big = @{ text = ("a" * 8001) } | ConvertTo-Json
    Status { Invoke-RestMethod -Method Post -Uri "$api/process" -Headers $ha -ContentType $j -Body $big }     # expect 413
c) No credentials still 401:
    Status { Invoke-RestMethod -Method Post -Uri "$api/process" -ContentType $j -Body $big }                  # expect 401
d) Legacy dashboard + Gmail still work: paste an email in the dashboard (do this one).

## Step 4 (optional but recommended): rehearse the emergency button once
The kill-switch is your "stop everything" control; better to know it works before you need it.
1. Render -> API service -> Environment -> add KILL_SWITCH = on  (Render redeploys; takes a minute or two, not instant)
2. <api-url>/health shows "paused": true.  With a test account:
       Status { Invoke-RestMethod -Method Post -Uri "$api/process" -Headers $ha -ContentType $j -Body $text }   # expect 503
   Logging in, /results and deleting data should still work.
3. DELETE the KILL_SWITCH variable (or set it to off) and let it redeploy. Confirm "paused": false.

## Step 5 (optional): see the daily limit trigger live
Locally it is proven (including the simultaneous-requests race). To see it live without 30 real Gemini calls:
set DAILY_LIMIT_PER_USER = 2 on the API service, redeploy, make 3 /process calls with a test account
(expect 200, 200, 429 with a "Daily limit reached" message), then REMOVE the variable and redeploy.
Remember to delete the test account afterwards:  DELETE FROM users WHERE userid LIKE 'test%';

## Recommended small edits to your current Gmail script (script.google.com)
1. Truncate long bodies so one huge email can't be rejected with 413 and retried every 5 minutes forever:
       const emailText = message.getPlainBody().substring(0, 8000);
2. Per-poll cap (roadmap: 5): change  GmailApp.search(fullQuery, 0, 20)  to  GmailApp.search(fullQuery, 0, 5)
(The multi-user script template in Task 7 will include both.)

## Known limitations (state them in the report)
- The day is UTC (resets 5:30 AM IST), not local time.
- A "poison" email that makes Gemini fail is retried every poll and each attempt uses one of that user's 30
  daily slots, which can lock the rest of their day. Task 7's script template will stop retrying non-retryable failures.
- The kill-switch needs a Render redeploy to take effect (about a minute or two); it is not instant.
- In-memory login-lockout and purge timers reset on restart (by design, documented in Task 3).
- WORST CASE LOAD: 15 users x 30 = 450 Gemini calls/day. Check your CURRENT Gemini free-tier daily quota in
  Google AI Studio (limits change). If it's lower than that, lower DAILY_LIMIT_PER_USER (env var, no code change).
