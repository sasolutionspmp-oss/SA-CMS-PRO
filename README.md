# SA-CMS Pro

SA-CMS Pro is S&A Solutions' command-and-control platform that unifies project intake, estimation, compliance, and CRM workflows. The monorepo now exposes three primary developer entry points:

- **Backend** – FastAPI application under `backend/app` with SQLAlchemy + Alembic migrations.
- **Frontend** – React 18 / Vite operator console in `frontend/`.
- **Desktop Shell** – Electron wrapper in `desktop/` that embeds the web app and bootstraps the backend.

Legacy Python services that powered the desktop client remain available under `app/` and `packages/`, but new development targets the stack described above.

## Repository Layout

```
backend/            # FastAPI service, Alembic migrations, dev tooling
frontend/           # React + Vite SPA
desktop/            # Electron shell for the operator console
app/, packages/     # Legacy service modules (ingest, metrics, etc.)
config/             # Shared YAML configuration
scripts/            # Historical PowerShell automation
```

## Requirements

- Python 3.11+
- Node.js 18+
- npm (or pnpm/yarn if you prefer, the scripts use npm by default)

## Backend Quick Start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install --upgrade pip
pip install -r ../requirements.txt
python scripts/dev.py  # applies alembic migrations & seeds dev-token user
uvicorn app.main:app --reload --port 8000
```

`DATABASE_URL` can override the default SQLite database. Set it in your shell before running the dev script:

```bash
export DATABASE_URL="sqlite:///$(pwd)/local.db"
```

## Frontend Quick Start

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs on http://localhost:5173 and proxies `/api/*` requests to http://localhost:8000. Use an `Authorization: Bearer dev-token` header when calling the API during development.

## Electron Shell

```bash
cd desktop
npm install
npm run dev
```

The dev script launches the Vite dev server, runs migrations, boots the FastAPI service on port 8000, and finally opens an Electron window pointed at http://localhost:5173. For a production-like run against the built assets use:

```bash
npm run prod
```

This command builds the React app, ensures the backend is migrated/seeded, and serves the compiled UI from `frontend/dist` inside the Electron window while continuing to use your local Python interpreter.

To create a distributable installer with an embedded Python runtime run:

```bash
npm run dist
```

The packaging workflow compiles the frontend, vendors a `desktop/python-runtime` virtual environment populated from `requirements.txt`, and copies the FastAPI service into the Electron bundle. Installers land under `desktop/dist/` (for Windows builds the default output is an `.exe`). Use `npm run package` to generate an unpacked directory for manual inspection. The cached virtual environment can be refreshed by deleting `desktop/python-runtime/` or by forcing a reinstall with `SA_CMS_PYTHON=<path-to-python> npm run bundle:python`.

## Smoke Tests

With the backend running (`uvicorn app.main:app --reload --port 8000`):

```bash
curl -H "Authorization: Bearer dev-token" http://localhost:8000/orchestrator
curl -H "Authorization: Bearer dev-token" http://localhost:8000/estimate
curl -H "Authorization: Bearer dev-token" http://localhost:8000/indices/regions
```

All three endpoints should return `200 OK` JSON payloads.

## Database Management

Alembic configuration lives under `backend/alembic/`. To create new migrations:

```bash
cd backend
alembic revision -m "your message"
python scripts/dev.py
```

`python scripts/dev.py` always runs `alembic upgrade head` and ensures the seeded admin user with token `dev-token` exists, keeping local environments consistent.

## Troubleshooting

- **Python executable not found** – set `SA_CMS_PYTHON` to the interpreter the Electron shell should use or rebuild the bundled runtime via `npm run bundle:python`.
- **Different API port** – set `DATABASE_URL` and restart the backend; adjust the Electron/Vite proxy target with `VITE_PROXY_TARGET` when needed.
- **Existing backend already running** – the Electron shell detects the service via `/healthz` before spawning a new one, so you can keep custom API instances alive during testing.

For more context on historical work, see `SUMMARY.md` and `PROGRESS.md`.
