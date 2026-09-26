# Phase 8, Step 8.1 — Containerize (Docker)

## What we're building
A single Docker image containing both your FastAPI backend and your
Streamlit dashboard, started together by `start.sh`. Only the
Streamlit port is exposed publicly; the dashboard talks to the API
internally over `localhost:8000`, exactly like your local setup.

## Files in this package
```
Dockerfile
requirements.txt
start.sh
.dockerignore
```

## 1. Place these files
Put all four files at the **root** of your project folder (same level
as `app/`, `src/`, `data/`):
```
ai-commitment-intelligence/
├── Dockerfile          <-- new
├── requirements.txt    <-- new
├── start.sh             <-- new
├── .dockerignore        <-- new
├── app/
│   ├── main.py
│   └── frontend.py
├── src/
│   ├── gemini_extractor.py
│   ├── rank_features.py
│   └── rank_score.py
└── data/
    └── gold_set/v1/...
```

## 2. Install Docker Desktop (if you don't have it)
https://www.docker.com/products/docker-desktop/ — install, then open
it once and make sure it says "Docker Desktop is running" before
continuing.

## 3. Build the image
In your project folder terminal:
```powershell
docker build -t commitment-intelligence .
```
This will take a few minutes the first time (downloading Python,
installing packages). Watch for errors — most likely cause of failure
here is a typo'd package name or a missing file that a COPY step
expected.

## 4. Run the container locally
```powershell
docker run -p 7860:7860 -e GOOGLE_API_KEY="AIza...your key..." commitment-intelligence
```
Note: the key is passed as an environment variable at `docker run`
time — it is NOT baked into the image, and you should never put it
directly in the Dockerfile or commit it to Git.

## 5. Test it
Open http://localhost:7860 in your browser. You should see the same
Streamlit dashboard as before, running entirely inside the container
this time. Paste a test email and confirm it still processes
correctly — this proves the two processes (API + dashboard) can talk
to each other *inside* the container.

## 6. What to check and report back
- Did `docker build` complete without errors?
- Did `docker run` start both processes? (You should see both
  "Uvicorn running on..." and Streamlit's startup message in the
  terminal log.)
- Did processing a test email work from http://localhost:7860?
- If anything failed, paste the exact error text.

## Common issues
- **"Gemini client not configured" inside the container** — you forgot
  the `-e GOOGLE_API_KEY=...` flag on `docker run`.
- **Container starts but dashboard shows "Cannot reach API server"** —
  the `sleep 3` in `start.sh` may not be long enough on a slow machine;
  try increasing it to `sleep 6` and rebuild.
- **Build fails on `COPY data/`** — make sure `data/gold_set/v1/` with
  both JSON files actually exists in your project folder before
  building.

Once this runs cleanly locally, you're ready for **Step 8.2 — deploy
to a free host** (Hugging Face Spaces is the simplest option since it
supports arbitrary Docker containers with a public URL for free).
