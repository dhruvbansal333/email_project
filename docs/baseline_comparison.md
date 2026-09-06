# Baseline Survey: spaCy Pretrained NER vs. Zero-Shot LLM (Phase 1, Step 1.2)

Ran two approaches over the same 5 sample emails (`notebooks/sample_emails.py`,
synthetic — real Enron samples will replace these once Phase 2 data collection
is done). Goal: understand what a cheap off-the-shelf baseline catches and
misses, to justify the extraction approach chosen in Step 1.3.

## Approach A — spaCy pretrained NER (`en_core_web_sm`)

Ran generic named-entity recognition, no task-specific tuning.

| Email | Entities found |
| --- | --- |
| 1. "I'll send you the revised contract by Friday afternoon..." | Friday (DATE), afternoon (TIME), last-minute (TIME), Daniel (PERSON) |
| 2. "Can someone get me the Q3 numbers before the board call on Thursday?" | Thursday (DATE), Maria (NORP — **misclassified**, should be PERSON) |
| 3. "I'll follow up... once I hear back from legal... Might take a few days." | Sam (PERSON), a few days (DATE), Alex (PERSON) |
| 4. "Let's plan to have the migration wrapped up by end of month." | today (DATE), Rob (PERSON) — **missed "end of month" entirely** |
| 5. "I'll take a look at the logs when I get a chance this week..." | Wei (PERSON), this week (DATE), Jordan (GPE — **misclassified**, should be PERSON) |

**Observations:**
- Reliably finds explicit date/time expressions and most person names.
- Misclassifies some names as NORP/GPE (nationality/location categories) —
  a known weakness of generic NER on informal, sign-off-style names.
- **Finds zero commitments.** NER only labels entity spans (people, dates,
  orgs); it has no concept of "who promised what to whom." It's a useful
  *feature source* (deadline candidates, party candidates) but cannot do
  the extraction task on its own.
- Completely misses "end of month" in Email 4 — spaCy's date detection
  is weakest on relative/vague temporal expressions, which are common in
  real commitment language.

## Approach B — Zero-shot LLM prompting

Prompted with: *"Identify any commitments in this email: who is
committing, what they're committing to, to whom, and any deadline."*
No fine-tuning, no examples given.

| Email | Extracted commitment |
| --- | --- |
| 1 | Daniel commits to sending the revised contract to Priya, deadline: Friday afternoon. High confidence, explicit deadline. |
| 2 | Maria requests Q3 revenue/churn figures from the team, implicit deadline: before Thursday's board call. Correctly identified as a *request placed on others*, not a self-commitment. |
| 3 | Alex commits to following up with Sam, conditional on hearing back from legal; deadline vague ("a few days"). Correctly flagged the conditional structure. |
| 4 | Ambiguous — flagged as a possible team/shared commitment with deadline "end of month," correctly noting it's unclear whether this binds Rob specifically or the group. |
| 5 | Jordan commits to reviewing logs, no firm deadline ("this week" is soft), correctly flagged as **low-confidence/weak commitment**. |

**Observations:**
- Correctly performs the actual task: identifies direction (made vs.
  requested), extracts deadlines including relative ones spaCy missed
  ("end of month"), and flags the same ambiguous/weak cases the
  annotation guideline already anticipates (Edge Cases 1 and 3).
- No training data needed to get a reasonable first pass — but zero-shot
  output isn't guaranteed to be consistent across phrasings or to follow
  a fixed schema without further prompt engineering or fine-tuning.
- Confidence/ambiguity flagging lines up well with the `confidence` field
  already planned in the annotation guideline, which is encouraging.

## Comparison summary

| | spaCy NER | Zero-shot LLM |
| --- | --- | --- |
| Finds people/dates | Yes (with some misclassification) | Yes |
| Identifies commitment relations (who→what→whom) | No | Yes |
| Handles relative deadlines ("end of month") | Weak/missed | Yes |
| Distinguishes made vs. requested | No | Yes |
| Flags ambiguous/conditional cases | No | Yes, unprompted |
| Cost/speed | Very cheap, fast, local | Slower, costs API tokens |
| Consistency without fine-tuning | High (deterministic) | Moderate (needs schema constraints) |

## Implication for Step 1.3 (architecture decision)

spaCy alone cannot do commitment extraction — it's a plausible *feature
generator* (candidate dates/names) for a rule-based system, not a
standalone solution. The zero-shot LLM already gets much of the way there
without any training data, which supports evaluating a fine-tuned
transformer against an LLM-prompting baseline rather than assuming the
transformer wins by default — this framing feeds directly into the
Step 1.3 design doc.
