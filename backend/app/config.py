"""Application configuration."""
from dataclasses import dataclass
import os


@dataclass
class Settings:
    app_name: str = "SA-CMS-Pro"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./sa_cms_pro.db")
    local_token: str = os.getenv("LOCAL_TOKEN", "dev-token")


settings = Settings()
