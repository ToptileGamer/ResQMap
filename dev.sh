#!/usr/bin/env bash
# Start the ResQMap backend (port 8000) and frontend (port 5173) together.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x "backend/.venv/bin/uvicorn" ]; then
  echo "Setting up the backend virtualenv..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install --upgrade pip >/dev/null
  backend/.venv/bin/pip install -r backend/requirements.txt
fi

if [ ! -d "frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm install)
fi

cleanup() {
  echo
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting backend  -> http://localhost:8000  (docs at /docs)"
(cd backend && .venv/bin/uvicorn main:app --reload --reload-include '*.env*' --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

echo "Starting frontend -> http://localhost:5173"
(cd frontend && npm run dev) &
FRONTEND_PID=$!

wait
