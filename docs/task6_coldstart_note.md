# Task 6 follow-up: surviving a cold start (replaces app/frontend.py from the first Task 6 zip)

## What you saw
After the services sat idle, logging in showed "Unexpected error (502)". That 502 came from Render's gateway
while the sleeping API was still starting. It was not your code (our API always answers with a JSON message,
and /login never returns 502).

## What the dashboard does now
It can tell a gateway answer (502/503/504 with no JSON "detail") from our own API's errors.
| Situation | What happens |
|---|---|
| Log in, or any page load / refresh (reads) | Waits for the server to wake (polls /health, up to ~75 s, spinner shown), then retries by itself. You just see it work. |
| Sign up, Process, Delete, key changes (anything that changes data) | Wakes the server, then tells you "that request did not go through, please click the button again". Never auto-repeated, so nothing can happen twice. |
| 504 (gateway timed out) on a data-changing action | "We can't be sure that went through. Check (log in again / press Refresh) before trying again." |
| Our API's own errors ("Extraction failed", "paused", "daily limit"...) | Shown as-is. Never mistaken for a sleeping server, never retried. |
| Server won't wake within ~75 s | Friendly "took too long, try again" message. Never hangs forever. |
The sign-in screen's warning also has a "Check again" button.

## Deploy
Replace app/frontend.py, then:
    git add app/frontend.py docs/task6_coldstart_note.md
    git commit -m "Dashboard: wake sleeping API on cold start, never repeat writes"
    git push origin main
Only the dashboard service needs this; the API is unchanged.

## Re-test on the live site
1. Leave both services idle for 15+ minutes (Render shows them as asleep).
2. Open the dashboard and log in right away. Expect: a "waking up" spinner (up to a minute), then you are logged in
   with no error. If you instead see a message, copy it exactly and send it to me.
3. Optional: do the same but press Create account or Process first. Expect "did not go through, click again",
   then it works on the second click.

## Honest limits
- Tested by simulating the gateway's responses (21 checks) plus the full 63-check suite; NOT yet seen against
  real Render cold-start behaviour, so step 2 above is the real test.
- The first request after a long idle can still take up to ~a minute (free hosting). The fix makes it work
  instead of erroring; it can't make it fast. Before a demo, open both services ~2 minutes ahead.
- The "502 from the gateway has no JSON detail" rule matches what you observed. If Render ever sends JSON with
  a "detail" field during wake-up, the dashboard would show it as an ordinary error instead of waiting.
- The hosting "HEAD / 404" and "GET / 404" lines in your API logs at startup are Render's own probes. Harmless.
