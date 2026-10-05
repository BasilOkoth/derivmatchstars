import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    deriv_app_id: str = os.getenv("DERIV_APP_ID", "1089")
    deriv_demo_token: str = os.getenv("DERIV_DEMO_TOKEN", "")
    deriv_real_token: str = os.getenv("DERIV_REAL_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./digitmatchstar.db")
    allow_real_mode: bool = os.getenv("ALLOW_REAL_MODE", "false").lower() == "true"

settings = Settings()
