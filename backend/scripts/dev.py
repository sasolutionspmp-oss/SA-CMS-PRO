from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

def run_alembic_upgrade() -> None:
    """Apply the latest database migrations."""

    cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    subprocess.run(cmd, check=True, cwd=BACKEND_DIR)


def seed_dev_user() -> None:
    """Ensure a development admin user exists for API calls."""

    from app.db.session import SessionLocal
    from app.models import User

    session = SessionLocal()
    try:
        token = "dev-token"
        existing = session.query(User).filter(User.token == token).first()
        if existing:
            if not existing.is_active:
                existing.is_active = True
                session.add(existing)
                session.commit()
            return
        user = User(
            email="dev-admin@example.com",
            full_name="Development Admin",
            token=token,
            role="admin",
            is_active=True,
        )
        session.add(user)
        session.commit()
    finally:
        session.close()


def main() -> None:
    run_alembic_upgrade()
    seed_dev_user()


if __name__ == "__main__":
    main()
