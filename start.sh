#!/bin/bash
# Starts the FastAPI backend in the background, then the Streamlit
# dashboard in the foreground. Both run inside the same container so
# the dashboard can reach the API over localhost, and only ONE port
# (Streamlit's) needs to be exposed publicly by the host.
set -e

echo "Starting FastAPI backend on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Give the API a moment to load resources (sender table, Gemini client)
# before Streamlit's first health check hits it.
sleep 3

echo "Starting Streamlit dashboard on port ${PORT:-7860}..."
streamlit run app/frontend.py \
    --server.port=${PORT:-7860} \
    --server.address=0.0.0.0 \
    --server.headless=true

# If Streamlit exits, stop the API too.
kill $API_PID
