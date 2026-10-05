from datetime import datetime, timedelta, timezone
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

def issue_platform_jwt(user_id: str) -> str:
    if not settings.platform_jwt_secret:
        raise RuntimeError("PLATFORM_JWT_SECRET is required")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.platform_jwt_hours)).timestamp()),
        "iss": "digitmatchstar-api",
        "aud": "digitmatchstar-web",
    }
    return jwt.encode(payload, settings.platform_jwt_secret, algorithm=settings.platform_jwt_algorithm)

def current_user_id(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "DigitMatchStar login required")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token,
            settings.platform_jwt_secret,
            algorithms=[settings.platform_jwt_algorithm],
            audience="digitmatchstar-web",
            issuer="digitmatchstar-api",
        )
        return str(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired DigitMatchStar session")
