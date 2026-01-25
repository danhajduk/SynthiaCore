#!/usr/bin/env bash
set -euo pipefail

# Convenience dev launcher (optional)
# Runs backend (9001) and frontend (5173) in separate terminals if available.

echo "Backend: uvicorn app.main:app --reload --port 9001 (in ./backend)"
echo "Frontend: npm run dev -- --port 5173 (in ./frontend)"
echo "Remember: ./scripts/sync-addons-frontend.sh before starting frontend."
