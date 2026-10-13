from fastapi import Header, HTTPException
from cryptography.fernet import Fernet
import jwt
from .config import settings

def _fernet():
    if not settings.token_encryption_key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required")
    return Fernet(settings.token_encryption_key.encode())

def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()

def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()

def current_user_id(
    authorization: str | None = Header(default=None),
    x_platform_user_id: str | None = Header(default=None),
):
    # Recommended production mode: your platform sends its signed JWT.
    if authorization and authorization.lower().startswith("bearer "):
        if not settings.platform_jwt_secret:
            raise HTTPException(500, "PLATFORM_JWT_SECRET is not configured")
        token = authorization.split(" ", 1)[1]
        try:
            payload = jwt.decode(
                token,
                settings.platform_jwt_secret,
                algorithms=[settings.platform_jwt_algorithm],
                options={"require": ["sub"]},
            )
            return str(payload["sub"])
        except Exception:
            raise HTTPException(401, "Invalid platform session token")

    # Integration escape hatch only for a trusted reverse proxy/backend.
    if settings.trust_platform_user_header and x_platform_user_id:
        return x_platform_user_id

    raise HTTPException(401, "Platform authentication required")
