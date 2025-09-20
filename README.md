# SA-CMS Pro

SA-CMS Pro is S&A Solutions' command-and-control platform that unifies project intake, estimation, compliance, and CRM workflows. The monorepo houses a FastAPI backend, a React/Vite operator console, background workers, and packaging scripts for the Windows desktop distribution.

## Stack Overview
- **Backend** – FastAPI (`apps/api`) with SQLAlchemy, Redis/RQ workers, and service modules under `packages/`.
- **Workers** – RQ-based job runners (`apps/workers`) that process ingest and parsing tasks.
- **Frontend** – React 18 + Vite + Tailwind (`frontend/`) delivering the operator dashboard.
- **Desktop Shell** – PySide6 client (`ui/`) packaged with PyInstaller + Inno Setup.
- **Automation** – PowerShell tooling under `install/`, `scripts/`, and `build/` to bootstrap, seed, and package the stack.

## Repository Layout
```
app/                  # Domain services shared by the legacy desktop client
apps/api/             # FastAPI application (routers, schemas, services)
apps/workers/         # Redis/RQ powered background workers
frontend/             # React/Vite operator console
packages/             # Shared Python packages (config, models, services)
install/, build/, scripts/  # Bootstrap, packaging, and automation scripts
config/               # YAML configuration and defaults
logs/, data/, output/ # Runtime artifacts (gitignored)
```

## Prerequisites
- Python 3.11+
- Node.js 18+ with `pnpm` (recommended) or `npm`
- Redis 6+ (for background jobs; falls back to in-process executor in dev)
- PowerShell 7+ on Windows (scripts target pwsh)
- Inno Setup (`iscc.exe`) for packaging the desktop installer (optional during dev)

## Quick Start
1. **Clone & enter the repo**
   ```powershell
   cd C:\Dev
   git clone https://github.com/sa-cms-pro/SA-CMS-PRO.git
   cd SA-CMS-PRO
   ```

2. **Create your environment file**
   ```powershell
   copy .env.example .env
   ```
   Adjust values as needed:
   ```env
   SA_CMS_PRO_DATABASE_URL=
   SA_CMS_PRO_REDIS_URL=redis://localhost:6379/0
   SA_CMS_PRO_DATA_ROOT=./data
   SA_CMS_PRO_LOGS_ROOT=./logs
   SA_CMS_PRO_JWT_SECRET_KEY=dev-secret-change-me
   SA_CMS_PRO_ACCESS_TOKEN_TTL_SECONDS=3600
   SA_CMS_PRO_REFRESH_TOKEN_TTL_SECONDS=1209600
   ```

3. **Bootstrap Python dependencies**
   ```powershell
   pwsh ./install/bootstrap.ps1 -IncludeDevDependencies
   # or do it manually:
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install -e .
   ```

4. **Run database seed data (optional but recommended)**
   ```powershell
   .\.venv\Scripts\python -m apps.api.seed
   ```

5. **Start the API**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
   ```
   - REST docs: http://127.0.0.1:8000/docs (Swagger UI)
   - Alternate docs: http://127.0.0.1:8000/redoc

6. **Run a background worker (separate shell)**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m apps.workers.worker
   ```

7. **Install frontend dependencies & start Vite**
   ```powershell
   cd frontend
   pnpm install  # or npm install
   pnpm run dev -- --host 127.0.0.1 --port 5173
   ```
   Visit http://127.0.0.1:5173 to access the operator console. The client reads `VITE_API_BASE` from `frontend/.env` when proxying to the API (defaults to http://127.0.0.1:8000).

## Scripts & Utilities
- `install/bootstrap.ps1` – Provision Python envs, install deps, optionally run tests.
- `scripts/environment-report.ps1` – Snapshot tool versions into `state/lane1.json` and archive to `output/ops/`.
- `scripts/heavy-run.ps1` – Full regression lane (bootstrap → pytest → UI self test → frontend lint/test → packaging).
- `build/codex-oneclick.ps1` – PyInstaller + Inno Setup packaging pipeline (emits `dist/SA_CMS_Pro.exe` and `output/SA-CMS-Pro-Setup.exe`).

## Testing
- **Backend**: `.\.venv\Scripts\python -m pytest`
- **Backend targeted**: `.\.venv\Scripts\python -m pytest tests/unit tests/integration`
- **Frontend**: `pnpm run lint`, `pnpm run test`
- **Desktop self-test**: `.\.venv\Scripts\python -m ui.cli --selftest`

## Packaging & Distribution
1. Run the desktop self-test to ensure PySide assets are valid.
2. Package: `pwsh ./build/codex-oneclick.ps1`
3. Installer output: `output/SA-CMS-Pro-Setup.exe`

## Observability & Logs
- API logs: `logs/api.log`
- Worker logs: `logs/worker/*.log`
- Desktop logs: `%APPDATA%/SA-CMS-Pro/logs`
- Operational digests: `output/ops/`

## Additional Documentation
- `docs/API_REFERENCE.md` – Overview of the primary FastAPI endpoints
- `docs/GETTING_STARTED.md` – Extended Windows setup notes
- `docs/UX_NOTES.md` – UX decisions, theming, and motion guidelines
- `docs/OPS_RUNBOOK.md` – Operational readiness and escalation paths

For questions or handoffs, update `PROGRESS.md` and `SUMMARY.md` with the latest context before exiting a session.
