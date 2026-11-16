# Multi-User End-to-End Test Report (Task 9)

*Roadmap reference: Multi-User Extension Roadmap v2, build step 9 and "Updated Acceptance Checks".*

**Evidence statement.** Every result below was **run by the project owner on the live deployment and reported**; none was independently observed by the assistant who helped prepare this document. Dates and screenshot names are left for the owner to fill in so the report can point to real evidence. No keys, passwords or email content belong in this file.

| # | Test | Result | Date | Evidence file | Notes |
|---|---|---|---|---|---|
| 1 | Signup and consent gate (account is not created without the tick) | PASS | (fill in) | (fill in) | |
| 2 | Generic login error (unknown userid and wrong password give the same message) | PASS | (fill in) | (fill in) | |
| 3 | Dashboard data isolation between two accounts | PASS | (fill in) | (fill in) | |
| 4 | Gmail integration and isolation | PASS | (fill in) | (fill in) | Owner confirmed this used a second, separate Google account and a freshly generated key (owner-reported) |
| 5 | API key isolation (regenerating A's key stops A's old script, B unaffected) | PASS | (fill in) | (fill in) | |
| 6 | Invalid API key returns HTTP 401 | PASS | (fill in) | (fill in) | |
| 7 | Login throttling | PASS | (fill in) | (fill in) | Verified in the UI. Exact HTTP status not recorded |
| 8 | Data survives an API restart | PASS | (fill in) | (fill in) | |
| 9 | "Delete my data" | PASS | (fill in) | (fill in) | |
| 10 | Account deletion and database cleanup | PASS | (fill in) | (fill in) | No rows left for the deleted user (Neon check by the owner) |

## Not covered

- Daily-limit (30 emails/user/day) behaviour was not tested live; it would need a temporary `DAILY_LIMIT_PER_USER` change.
- HTTP 429 from the login throttle was seen in the UI only.
- Load, concurrency and penetration testing were not performed.

## Summary for the final report

10 of 10 planned checks were reported as passing on the live deployment. The owner has confirmed that test 4 used a second, separate Google account and a freshly generated key, which was the one open item for the roadmap's final acceptance criterion. All results remain owner-reported.
