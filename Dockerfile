# Phase 8, Step 8.1 — Dockerfile
# Packages the FastAPI backend + Streamlit dashboard into one container.
# Only the Streamlit port is exposed publicly; the API is reached
# internally over localhost (see start.sh).

FROM python:3.11-slim

WORKDIR /code

# Install dependencies first (better layer caching -- code changes
# won't force a full dependency reinstall)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the actual project code
COPY app/ ./app/
COPY src/ ./src/
COPY data/ ./data/
COPY start.sh .

RUN chmod +x start.sh

# Hugging Face Spaces expects the app on port 7860 by default.
# Render/other hosts set $PORT themselves; start.sh respects either.
EXPOSE 7860

# GOOGLE_API_KEY must be set as a secret/environment variable on the
# host platform (never baked into the image or committed to Git).
CMD ["./start.sh"]
