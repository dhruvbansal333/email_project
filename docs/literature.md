# Literature Review (Phase 1, Step 1.1)

Three papers on email intent / request / commitment detection, summarized
for grounding this project's extraction and annotation approach.

## 1. Lampert, Dale & Paris (2010) — "Detecting Emails Containing Requests for Action" (NAACL/HLT)

**Task:** Message-level classification of whether an email contains a
request for action (a directive speech act placing an obligation on the
recipient).
**Method:** An SVM classifier trained on lexical (word unigram/bigram),
structural (message length, capitalization, punctuation), and header-based
features, combined with an automated "email zoning" step that first
segments each message into functional zones (author content, greeting,
signoff, quoted reply, forwarded content, signature, etc.) and restricts
classification to the zones actually authored by the sender.
**Dataset:** 664 Enron messages, triple-annotated, with 505 unanimously
agreed messages used for training/evaluation after discarding disagreements.
**Result:** Zoning improved classification accuracy from about 72% to
about 84% and cut errors by roughly 41% relative to the no-zoning baseline,
showing that discarding quoted/forwarded/signature text before
classification is a high-value preprocessing step. A companion finding:
human annotators agreed much more consistently on what counts as a
request than on what counts as a commitment, which is directly relevant
to why this project's own annotation guideline treats "commitment" as the
harder, lower-agreement label to define carefully.

This paper is also the direct precedent for this project's annotation
scheme, since a companion paper by the same authors ("Requests and
Commitments in Email are More Complex Than You Think," 2008) provides the
formal definitions this project's guideline borrows from.

## 2. Lin, Kang, Gamon, Khabsa, Awadallah & Pantel (2018) — "Actionable Email Intent Modeling with Reparametrized RNNs" (AAAI)

**Task:** Predicting what action a recipient will take in response to an
email, framed as action-based annotation rather than traditional
speech-act theory, on the reasoning that action labels are easier to
annotate consistently and scale better across domains.
**Method:** A family of recurrent neural network encoders (RAINBOW —
Recurrently Attentive Neural Bag-of-Words) that share parameters across
domains, tested with a domain-adaptive "reparametrization" scheme so a
model trained on one type of threaded conversation (IRC, Reddit) can
transfer to email.
**Dataset:** A mix of IRC, Reddit, and email threads, plus a minimally
supervised email recipient—action-classification setting.
**Result:** The reparametrized RNNs outperformed common multitask/
multidomain baselines on several speech-act-related tasks, and the model
learned useful representations even with minimal supervision — relevant
to this project's own resource-constrained setting.

## 3. Shu, Mukherjee, Zheng, Awadallah, Shokouhi & Dumais (2020) — "Learning with Weak Supervision for Email Intent Detection" (SIGIR)

**Task:** Detecting three email intents — request information, schedule
meeting, and promise action (the closest published analogue to this
project's "commitment made" label) — under a weak-supervision setup where
only a small amount of hand-labeled data is available.
**Method:** A model called Hydra that jointly learns from a small clean
labeled set and a much larger set of noisy labels derived automatically
from user interaction signals (e.g., a flagged email followed by a reply
is weakly labeled as a "promise action"), combined with label correction
and self-paced curriculum learning to downweight the noisiest weak
examples.
**Dataset:** The Avocado email corpus (with user interaction/calendar
metadata), plus a transfer experiment onto Enron.
**Result:** Hydra improved accuracy 3-12% over strong baselines on
average, and combining a small clean Enron set with weak Avocado labels
outperformed using clean Enron data alone. This is directly relevant to
this project's Phase 3 note that "LLM-assisted pre-labeling with human
verification is acceptable" — it's the same clean+weak philosophy applied
with an LLM instead of interaction-log heuristics as the weak-label source.

## Takeaways for this project

- Email zoning (stripping quoted/forwarded/signature content before
  extraction) is a well-established, cheap preprocessing step with a
  large measured accuracy payoff — worth adding as a cleaning step in
  Phase 2, not just signature/disclaimer stripping.
- "Commitment" detection is consistently reported as harder and lower
  inter-annotator-agreement than "request" detection across all three
  papers — this validates spending real annotation-guideline effort on
  the commitment side specifically (see the 5 open edge cases in
  `docs/annotation_guideline_draft.md`).
- LLM-assisted pre-labeling with human verification (already planned for
  this project) has precedent in the weak-supervision literature as a
  legitimate way to stretch a small hand-labeled set further, provided
  it's reported transparently as a method rather than treated as
  equivalent to fully manual gold labels.
