import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./digitmatchstar.db")
    deriv_client_id: str = os.getenv("DERIV_CLIENT_ID", "")
    deriv_redirect_uri: str = os.getenv(
        "DERIV_REDIRECT_URI",
        "https://digitmatchstar-api.onrender.com/auth/deriv/callback",
    )
    deriv_scope: str = os.getenv("DERIV_SCOPE", "trade account_manage")
    token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    platform_jwt_secret: str = os.getenv("PLATFORM_JWT_SECRET", "")
    platform_jwt_algorithm: str = os.getenv("PLATFORM_JWT_ALGORITHM", "HS256")
    platform_jwt_hours: int = int(os.getenv("PLATFORM_JWT_HOURS", "12"))
    frontend_url: str = os.getenv("FRONTEND_URL", "https://www.digitmatchstar.com")
    allow_real_mode: bool = os.getenv("ALLOW_REAL_MODE", "false").lower() == "true"

settings = Settings()
