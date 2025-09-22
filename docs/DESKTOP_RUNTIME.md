# Desktop Runtime Packaging

This project ships the Electron shell together with an embedded Python **virtual
environment** so the packaged Windows executable can run the FastAPI backend
without depending on a machine-wide Python installation.

## Bundling approach

* Build a dedicated virtual environment with the same Python version you test
  with (e.g. Python 3.11) and install all of the dependencies declared in
  [`requirements.txt`](../requirements.txt).
* Copy the fully provisioned environment into `desktop/resources/python` before
  running your Electron packager (e.g. `electron-builder`, `electron-forge`, or
  `electron-packager`). The folder must travel alongside the final `app.asar`
  payload so it ends up under `<AppRoot>/resources/python` in the installed
  application.
* During packaging make sure the backend sources (`backend/**`) and the helper
  scripts (`backend/scripts/dev.py`) are marked as **asar-unpacked** (or copied
  verbatim) so CPython can execute them from the filesystem. Python cannot
  import modules directly from the compressed `app.asar` archive.

This layout mirrors how a normal virtual environment is structured:

```
resources/
├── app/                 # Electron bundle (frontend + main process code)
└── python/              # Embedded venv copied verbatim
    ├── Scripts/         # Windows entry points (python.exe, uvicorn.exe, ...)
    ├── bin/             # POSIX entry points (python3, uvicorn, ...)
    ├── Lib/             # stdlib + installed packages
    └── pyvenv.cfg
```

Only one of `Scripts/` (Windows) or `bin/` (POSIX) will be present depending on
where the venv was created.

## Runtime configuration

The Electron main process now resolves the backend interpreter like this:

1. Honour an explicit override via the `SA_CMS_PYTHON` environment variable.
2. If the app is packaged, prefer the interpreter that lives under
   `process.resourcesPath + "/python"`.
3. Fall back to the system `python`/`python3` command when running in
   development.

When the embedded interpreter is used, the launcher injects a `PATH` entry that
points at the virtual environment's `Scripts`/`bin` directory and exports
`VIRTUAL_ENV` so `sys.prefix` resolves to the bundled environment. This guarantees
that the following commands keep working inside the packaged build:

* `python backend/scripts/dev.py` – runs the Alembic migrations and creates the
  default admin user before the UI starts.
* `python -m uvicorn app.main:app` – starts the FastAPI server that powers the
  desktop shell.

## Environment variables

* `SA_CMS_PYTHON` – Optional override that forces the Electron shell to use a
  specific Python executable (useful for QA or custom test harnesses).
* `PYTHONUNBUFFERED` – Automatically injected so backend logs flush immediately
  to the Electron console. You do not need to set it manually.
* `VIRTUAL_ENV` – Automatically exported when the embedded interpreter is used.

With this setup the packaged `.exe` can be distributed as a self-contained
application: drop the `python` directory next to the Electron resources folder
and the main process will launch the backend using the vendored environment.
