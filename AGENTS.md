# Agent guide: SA-CMS-PRO

This repository holds two independent projects. Know which one you are working on before you change anything.

| Path | Project | Stack | Start here |
|---|---|---|---|
| `apps/cipher/` | **Cipher**, S&A Solutions' project-controls and accounting prototype (synthetic data only) | Python 3.12+ standard library, SQLite; no packages | `apps/cipher/HANDOFF.md`, then `apps/cipher/AGENTS.md` |
| everything else (`app/`, `apps/api/`, `apps/workers/`, `apps/web/`, `frontend/`, `packages/`, `scripts/`) | SA-CMS Pro, the earlier intake and estimating platform | FastAPI, React/Vite, PySide6 | `README.md`, `TASKS.md`, `PROGRESS.md` |

Cipher imports nothing from the rest of the repository, and nothing else imports Cipher. Its tests run with `python -m apps.cipher test` from the repository root and need no installs.

## Repository-wide notes

- **Committed `node_modules`.** About 64,000 files under `apps/web/node_modules` are committed, so a full checkout is about 1.4 GB. For Cipher-only work in a tight container, use a sparse checkout: `git sparse-checkout set --cone apps/cipher`. Never create one full worktree per parallel agent: that filled a 7 GB disk during round 4.
- **Branches.** `main` carries both projects. Cipher work happened on `cipher/synthetic-prototype` (merged through PR #27). Older `codex/*` branches belong to SA-CMS Pro.
- **Spelling.** Write American English and US formats in code, comments, docs and messages.
