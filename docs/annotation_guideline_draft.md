# Annotation Guideline — Early Draft (Phase 0, Step 0.3)

Status: DRAFT. To be finalized in Phase 3 (Step 3.1) using real examples
pulled from the actual Enron subset, after the 5 open edge cases below are
resolved.

## 1. What counts as a "commitment"

A **commitment** is a statement in an email where a sender:
(a) promises to do something themselves (a **commitment made**), or
(b) explicitly asks/expects the recipient to do something (a **commitment
    requested**, i.e. an obligation placed on someone else).

Both directions are labeled — the system needs to track what the user
owes *and* what is owed to them.

### Example sentences (initial set — expand during pilot labeling)

1. "I'll send you the revised contract by Friday." → commitment made,
   explicit deadline (Friday).
2. "Can you get me the Q3 numbers before the board call?" → commitment
   requested, implicit deadline (before the board call — needs resolution).
3. "I'll follow up once I hear back from legal." → commitment made,
   no explicit deadline (conditional/open-ended).
4. "Let's plan to have this wrapped up by end of month." → ambiguous —
   is this a commitment by the sender, a request of the recipient, or a
   shared/team commitment? (see Edge Case 1 below)
5. "Thanks, I'll take a look." → weak/implicit commitment — low confidence,
   vague scope, no deadline.

## 2. Fields to capture per commitment

| Field | Description | Required? |
| --- | --- | --- |
| `sender` | Person who wrote the email (anonymized ID, not raw name) | Yes |
| `recipient` | Person(s) the commitment is directed to | Yes |
| `commitment_text` | The exact span of text expressing the commitment | Yes |
| `direction` | `made` (sender commits) or `requested` (sender asks recipient) | Yes |
| `deadline` | Normalized date/time if stated or clearly inferable; else null | No |
| `deadline_type` | `explicit`, `implicit`, or `none` | Yes |
| `confidence` | Annotator's confidence the span is truly a commitment: `high` / `medium` / `low` | Yes |
| `thread_id` | Which email thread this came from | Yes |

## 3. Open edge cases to resolve in Phase 1 / early Phase 3

Resolve these using real examples pulled from the Enron subset once data
collection starts — do not guess in the abstract.

1. **Group/shared commitments**: "Let's get this done by Friday" — is this
   a commitment by the sender, a request of the recipient, or both? Current
   lean: label as `requested` if there's a clear recipient list, otherwise
   discard as too ambiguous.
2. **Conditional commitments**: "I'll send it once John approves" — commit
   now with `deadline_type = implicit`, or wait and treat John's approval
   as a blocking precondition worth its own field? Current lean: label as a
   commitment with a `condition` note in the text span, no separate field
   yet (revisit if this pattern is common).
3. **Vague/weak commitments**: "I'll take a look" / "noted, will do" — do
   these count at all, or are they too weak to be useful? Current lean:
   include them but mark `confidence = low`, so the ranking model can learn
   to deprioritize them rather than the extraction step discarding them.
4. **Recurring/standing commitments**: "I'll send the weekly report every
   Monday" — one commitment instance, or does it need to be expanded into
   multiple dated instances? Current lean: label once as a recurring
   commitment; do not auto-expand into a series in v1.
5. **Third-party commitments**: "Sarah said she'd handle the invoices" —
   the sender is reporting someone else's commitment, not making one
   themselves. Current lean: label with `sender = Sarah` (the actual
   committer) if identifiable, not the email author, and flag with a
   `reported_by` note; if too ambiguous, exclude from the gold set.

## 4. Non-commitments (explicitly exclude)

- Pure FYI/status updates with no future action implied
  ("The report was sent yesterday.")
- Past-tense completed actions ("I already sent this.")
- Purely social/pleasantry language with no task attached
  ("Great to see you at the conference!")
- Questions that don't imply an obligation
  ("Do you know if the meeting moved?")

## 5. Pilot labeling process (Phase 3, Step 3.2)

1. Label ~30 emails yourself first as a pilot batch.
2. Review after a day — check for inconsistency, revise this guideline.
3. If a second labeler is available, have them label a 10% overlap sample
   for inter-annotator agreement.

## 6. Revision log

- v0 (Phase 0 draft): initial definitions, fields, and 5 open edge cases.
  To be revised in Phase 3 once real data is available.
