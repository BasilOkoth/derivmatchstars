import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./digitmatchstar.db")
    deriv_client_id: str = os.getenv("DERIV_CLIENT_ID", "")
    deriv_redirect_uri: str = os.getenv("DERIV_REDIRECT_URI", "")
    deriv_legacy_app_id: str = os.getenv("DERIV_LEGACY_APP_ID", "")
    deriv_scope: str = os.getenv("DERIV_SCOPE", "trade")
    token_encryption_key: str = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    platform_jwt_secret: str = os.getenv("PLATFORM_JWT_SECRET", "")
    platform_jwt_algorithm: str = os.getenv("PLATFORM_JWT_ALGORITHM", "HS256")
    trust_platform_user_header: bool = os.getenv("TRUST_PLATFORM_USER_HEADER", "false").lower() == "true"
    frontend_url: str = os.getenv("FRONTEND_URL", "")
    allow_real_mode: bool = os.getenv("ALLOW_REAL_MODE", "false").lower() == "true"

settings = Settings()
