# Multi-User Extension, Task 4: Per-user auth on the API + API keys + account deletion

## What this does
Every protected endpoint (/process, /extract, /results, /results/clear) now works out
WHO is calling, from any one of:
  1. Authorization: Bearer <session token>   (dashboard login)
  2. X-API-Key: cai_...                       (a user's Gmail script)
  3. X-Ingestion-Key: <global secret>         (LEGACY: your current dashboard + Gmail script)

A user's results are saved in Neon under their own account. A session token and that same
user's API key resolve to the SAME account, so Gmail results show up when they log in.

New endpoints:
  POST /apikey          create/replace your Gmail-script key (shown once; only a hash is stored)
  GET  /apikey          do I have a key? (never reveals it)
  POST /account/delete  delete the account + everything in it (needs the password)

## Why the legacy path is still there
Your live dashboard and Gmail script still send the old global key. If it were removed now,
both would break until Tasks 6 and 7. So it stays, with its own separate in-memory store; it can
never see or touch a user's data. TO RETIRE IT LATER: delete INGESTION_SECRET from the API
service on Render. No code change.

## Step 1: Run one SQL line in Neon (SQL Editor)
    CREATE UNIQUE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
(also in docs/task4_migration.sql; safe to run twice)

## Step 2: Place the files
    app/main.py    (replace)
    src/auth.py    (replace)
No new packages, no new environment variables.

## Step 3: Push
    git add app/main.py src/auth.py
    git commit -m "Multi-user Task 4: per-user auth, API keys, account deletion"
    git push origin main

## Step 4: REGRESSION CHECK FIRST (your live demo must still work)
- Dashboard: paste a test email, click Process -> commitments appear as before.
- (Optional) Gmail script: run processCommitmentEmails once on a test email -> still 200.
If either breaks, stop and tell me before testing anything else.

## Step 5: New-feature tests (PowerShell). Nothing here prints a token or key.
    $api = "https://ai-commitment-api.onrender.com"
    function Status($sb) { try { & $sb | Out-Null; "OK (2xx)" } catch { $_.Exception.Response.StatusCode.value__ } }
    $j = "application/json"
    $a = Invoke-RestMethod -Method Post -Uri "$api/signup" -ContentType $j -Body (@{userid="test_a";password="test pass A 123"}|ConvertTo-Json)
    $b = Invoke-RestMethod -Method Post -Uri "$api/signup" -ContentType $j -Body (@{userid="test_b";password="test pass B 123"}|ConvertTo-Json)
    $ha = @{ Authorization = "Bearer $($a.token)" }
    $hb = @{ Authorization = "Bearer $($b.token)" }
    $text = @{ text = "I'll send the budget report by tomorrow noon. Please review the contract by Friday."; source = "dashboard" } | ConvertTo-Json

1) No credentials is rejected                                  (expect 401)
    Status { Invoke-RestMethod -Method Post -Uri "$api/process" -ContentType $j -Body $text }

2) Process as A with a login session                           (expect commitments back)
    Invoke-RestMethod -Method Post -Uri "$api/process" -Headers $ha -ContentType $j -Body $text

3) A sees them, B does not                                     (expect A: 1+ ; B: 0)
    (Invoke-RestMethod -Uri "$api/results" -Headers $ha).results.Count
    (Invoke-RestMethod -Uri "$api/results" -Headers $hb).results.Count

4) Create A's API key and use it                               (expect A's count to go UP)
    $k = Invoke-RestMethod -Method Post -Uri "$api/apikey" -Headers $ha
    $hk = @{ "X-API-Key" = $k.api_key }
    Invoke-RestMethod -Method Post -Uri "$api/process" -Headers $hk -ContentType $j -Body $text
    (Invoke-RestMethod -Uri "$api/results" -Headers $ha).results.Count

5) An API key cannot manage keys                               (expect 403)
    Status { Invoke-RestMethod -Method Post -Uri "$api/apikey" -Headers $hk }

6) Regenerating kills the old key                              (expect 401)
    $old = $k.api_key
    $k2 = Invoke-RestMethod -Method Post -Uri "$api/apikey" -Headers $ha
    Status { Invoke-RestMethod -Uri "$api/results" -Headers @{ "X-API-Key" = $old } }

7) B clearing their data does not touch A                      (expect A's count unchanged)
    Invoke-RestMethod -Method Post -Uri "$api/results/clear" -Headers $hb
    (Invoke-RestMethod -Uri "$api/results" -Headers $ha).results.Count

8) Account deletion                                            (expect 401, then deleted, then 401)
    Status { Invoke-RestMethod -Method Post -Uri "$api/account/delete" -Headers $hb -ContentType $j -Body (@{password="wrong wrong 123"}|ConvertTo-Json) }
    Invoke-RestMethod -Method Post -Uri "$api/account/delete" -Headers $hb -ContentType $j -Body (@{password="test pass B 123"}|ConvertTo-Json)
    Status { Invoke-RestMethod -Uri "$api/results" -Headers $hb }

9) In Neon SQL Editor, confirm only the key HASH is stored (64 hex chars, never "cai_..."):
    SELECT user_id, length(key_hash) AS len, left(key_hash,4) AS starts FROM api_keys;

## Step 6: Clean up (account cap is 15)
    DELETE FROM users WHERE userid LIKE 'test%';
(deleting a user automatically removes their results, key and usage)

## Things to know
- Do NOT share the link publicly yet. Until Task 5 (limits) is done, anyone who signs up could
  call /process repeatedly and use up your Gemini free quota. Deploy Task 5 next.
- /process returns 503 if saving to the database fails, rather than "succeeding" with data lost.
  The Gmail script then leaves that email unlabeled and retries it next poll (this can cost one
  extra Gemini call; that's the trade-off for never silently losing a commitment).
- The first call after a quiet period can be slow: Render and Neon both sleep when idle.
- API keys use SHA-256 (not bcrypt): keys are 256 random bits, so a slow hash adds nothing.
  Passwords (low-entropy, human-chosen) keep bcrypt.
- Deleting an account needs the password AND a login session. Wrong attempts share the login
  lockout (5 per 10 minutes), so a stolen session token can't be used to guess the password.

## For the report (design decisions)
- Two credential types resolving to one identity; keys can't mint keys or delete accounts.
- The server stores only hashes of passwords and keys; the plaintext key is shown once.
- ON DELETE CASCADE guarantees no residue after account deletion.
- Staged migration: the legacy path kept the demo live during the build and is retired by
  removing one environment variable.
