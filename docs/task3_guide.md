# Multi-User Extension, Task 3: Signup / Login / Session Tokens

## What this adds
- POST /signup  : create account (userid + password), logged in immediately
- POST /login   : returns a session token
- GET  /me      : "who am I?" (token check; the dashboard will use this later)
- /health       : now also reports auth_ready (true when DATABASE_URL + SESSION_SECRET are set)

Existing endpoints (/process, /extract, /results, /results/clear) are UNCHANGED.
Your current Gmail automation and dashboard keep working exactly as before.
Task 4 switches them to per-user auth.

## Step 1: Add SESSION_SECRET on Render (API service only)
Generate a long random value (PowerShell):
    -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 48 | % {[char]$_})
Render -> API service -> Environment -> add:
    SESSION_SECRET = <that value>        (must be 32+ characters)
This is what signs login tokens. Never commit it. If it ever leaks, change it
(everyone just has to log in again).
(DATABASE_URL should already be there from Task 1.)

## Step 2: Add 3 packages to requirements.txt
Append these lines to your existing requirements.txt:
    psycopg2-binary
    bcrypt
    PyJWT

## Step 3: Place the files
    src/db.py        (new)
    src/auth.py      (new)
    app/main.py      (replace)

## Step 4: Push
    git add src/db.py src/auth.py app/main.py requirements.txt
    git commit -m "Multi-user Task 3: signup, login, session tokens"
    git push origin main
Render redeploys the API service (the dashboard service redeploys too; harmless).
In the API logs you should NOT see the DATABASE_URL / SESSION_SECRET warnings.
Open <your-api-url>/health : "auth_ready" should be true.

## Step 5: Test on the live API (PowerShell)
Use your API service's URL (the uvicorn one, not the dashboard).

    $api = "https://YOUR-API-SERVICE.onrender.com"
    $body = @{ userid = "test_user1"; password = "my test pass 123" } | ConvertTo-Json

A) Signup (expect token, userid, expires_in):
    Invoke-RestMethod -Method Post -Uri "$api/signup" -ContentType "application/json" -Body $body

B) Login, then ask /me (expect userid test_user1):
    $login = Invoke-RestMethod -Method Post -Uri "$api/login" -ContentType "application/json" -Body $body
    Invoke-RestMethod -Uri "$api/me" -Headers @{ Authorization = "Bearer $($login.token)" }

C) Wrong password (expect 401):
    $bad = @{ userid = "test_user1"; password = "wrong password 123" } | ConvertTo-Json
    try { Invoke-RestMethod -Method Post -Uri "$api/login" -ContentType "application/json" -Body $bad } catch { $_.Exception.Response.StatusCode.value__ }

D) Unknown userid (expect the same 401):
    $ghost = @{ userid = "no_such_user"; password = "whatever 12345" } | ConvertTo-Json
    try { Invoke-RestMethod -Method Post -Uri "$api/login" -ContentType "application/json" -Body $ghost } catch { $_.Exception.Response.StatusCode.value__ }

E) /me with no token (expect 401):
    try { Invoke-RestMethod -Uri "$api/me" } catch { $_.Exception.Response.StatusCode.value__ }

F) Confirm the password is hashed. In Neon's SQL Editor:
    SELECT id, userid, left(password_hash, 7) AS hash_start FROM users;
   hash_start should look like $2b$12$ (a bcrypt hash), never your real password.

(If the very first call is slow, that's Render waking up and/or Neon waking up. Wait and retry.)

## Step 6: Clean up test accounts
Accounts are capped at 15 total, so don't leave test accounts behind.
In Neon's SQL Editor:
    DELETE FROM users WHERE userid LIKE 'test%';

## Design decisions (useful for the report)
- Passwords: bcrypt hashes only; plaintext never stored or logged.
- Tokens: signed JWT, 12-hour lifetime, stateless (no extra table). Trade-off: a
  token cannot be revoked early; it simply expires.
- Userids are case-insensitive (stored lowercase).
- Login failures are identical for "no such user" and "wrong password", and the
  no-such-user path still does a bcrypt comparison so response time does not reveal
  which userids exist.
- Failed-login throttle: 5 wrong attempts per userid per 10 minutes -> 429.
  Trade-offs: in-memory (resets on restart); someone could temporarily lock out
  another person's userid, though no data is exposed.
- Signup is capped at 15 accounts (roadmap limit); signups are serialized with a
  table lock so two simultaneous signups cannot both slip past the cap.
- Signup necessarily says "userid already taken" (unavoidable); login never
  reveals whether a userid exists.
