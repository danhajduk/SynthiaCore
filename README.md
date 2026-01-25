# Synthia (Clean Baseline)

This is a clean, minimal baseline for the Synthia Core + Addon architecture.

## Quick start

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 9001
```

### Frontend
```bash
cd frontend
npm install
./../scripts/sync-addons-frontend.sh
npm run dev -- --port 5173
```

## Docs
- `docsiv at: docs/ARCHITECTURE.md`
