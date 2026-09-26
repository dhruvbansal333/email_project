"""
Phase 7, Step 7.1 — Commitment extraction using the Google Gemini API
(free tier via Google AI Studio), replacing the Claude-based extraction
used during Phase 4/6 evaluation. Same schema, same guideline, so
outputs stay consistent with the labeled gold set.

Uses the current `google-genai` SDK (the older `google-generativeai`
package is deprecated as of this writing — do not use it for new code).

Setup:
    pip install google-genai
    Get a free API key from https://aistudio.google.com/app/apikey
    Set it as an environment variable:
        Windows (PowerShell):  $env:GOOGLE_API_KEY = "AIza..."
        Mac/Linux:              export GOOGLE_API_KEY="AIza..."
"""

import json
import os
import re

from google import genai
from google.genai import types

SYSTEM_PROMPT = """You are extracting commitments from an email for a \
professional commitment-tracking tool. A commitment is a statement where \
the sender either (a) promises to do something themselves ("made"), or \
(b) explicitly asks/expects the recipient to do something ("requested"). \
Exclude pure FYI/status updates, past-tense completed actions, and \
pleasantries with no task attached. Purely descriptive statements about what an automated system/process will do (e.g. \
"your mailbox will be restricted to 100mb") should still be extracted as "made" commitments \
ONLY if the recipient would need to take some action in response (e.g. free up storage, update \
settings, migrate data). General FYI announcements with no required recipient action (e.g. \
"the office will be closed Friday", "the server will restart at midnight") are NOT commitments \
-- exclude them, same as any other pure status update.

For each commitment found, output a JSON object with these fields:
- commitment_text: the EXACT substring from the email (verbatim — used for text search, do not paraphrase or alter punctuation/spacing)
- direction: "made" or "requested"
- deadline_type: "explicit" (a stated date/time), "implicit" (a vague/relative reference like "end of month"), or "none"
- deadline_text: the EXACT substring naming the deadline, or null if deadline_type is "none"
- sender_text: EXACT substring naming who is committing/requesting (name, signoff, or greeting line), or null if not identifiable in the text
- recipient_text: EXACT substring naming who the commitment is directed to, or null if not identifiable
- confidence: "high", "medium", or "low" — how clearly this reads as a real, actionable commitment
- third_party_reported: true if the email reports someone ELSE's commitment rather than the sender's own; false otherwise
- reported_by: if third_party_reported is true, the name of the actual committer; otherwise null

Respond with ONLY a JSON array (no markdown fences, no preamble). Empty array if no commitments."""

MODEL_NAME = "gemini-3.5-flash-lite"  # fast, free-tier-friendly, good for short structured-extraction tasks


def get_client(api_key: str = None) -> genai.Client:
    api_key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GOOGLE_API_KEY environment variable (get a free key at "
            "https://aistudio.google.com/app/apikey)"
        )
    return genai.Client(api_key=api_key)


def extract_commitments(email_text: str, client: genai.Client = None) -> list:
    """Calls Gemini to extract commitments from a single email's text.
    Returns a list of commitment dicts matching the Phase 3 annotation
    schema. Raises on malformed model output rather than silently
    returning an empty list, so callers notice extraction failures."""
    if client is None:
        client = get_client()

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=f"Email:\n\n{email_text}",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",  # ask Gemini to return valid JSON directly
        ),
    )
    raw = response.text.strip()
    raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        commitments = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Gemini returned non-JSON output: {raw[:200]}") from e

    if not isinstance(commitments, list):
        raise ValueError(f"Expected a JSON array, got: {type(commitments)}")

    return commitments


if __name__ == "__main__":
    # Quick manual smoke test — run this file directly after setting
    # GOOGLE_API_KEY to confirm the API call works end-to-end.
    sample_email = """Hi Priya,

I'll send you the revised contract by Friday afternoon. Also, can you
review the attached budget and let me know your thoughts by end of day
tomorrow?

Thanks,
Daniel"""

    print("Testing Gemini extraction on a sample email...")
    results = extract_commitments(sample_email)
    print(json.dumps(results, indent=2))
