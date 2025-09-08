"""Structured logging utilities."""
import json
import logging
import logging.handlers
import os
from pathlib import Path

LOG_DIR = Path(os.getenv("PROGRAMDATA", "/tmp")) / "SA-CMS-Pro"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def log_json(**kwargs) -> None:
    logging.getLogger().info(json.dumps(kwargs))
