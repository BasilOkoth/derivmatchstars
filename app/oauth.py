import base64, hashlib, secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from .config import settings
from .db import SessionLocal
from .models import OAuthPending, DerivCredential, DerivAccount
from .security import current_user_id, encrypt_token, decrypt_token
from .deriv_rest import exchange_code, get_accounts
import json

router = APIRouter(prefix="/auth/deriv", tags=["deriv-auth"])

def _pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge

@router.get("/start")
def start_deriv_oauth(user_id: str = Depends(current_user_id)):
    if not settings.deriv_client_id or not settings.deriv_redirect_uri:
        raise HTTPException(500, "DERIV_CLIENT_ID / DERIV_REDIRECT_URI missing")
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)

    db = SessionLocal()
    try:
        db.add(OAuthPending(state=state, user_id=user_id, code_verifier=verifier))
        db.commit()
    finally:
        db.close()

    params = {
        "response_type": "code",
        "client_id": settings.deriv_client_id,
        "redirect_uri": settings.deriv_redirect_uri,
        "scope": settings.deriv_scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if settings.deriv_legacy_app_id:
        params["app_id"] = settings.deriv_legacy_app_id

    return {"authorization_url": "https://auth.deriv.com/oauth2/auth?" + urlencode(params)}

@router.get("/callback")
async def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, f"Deriv authorization failed: {error}")
    if not code or not state:
        raise HTTPException(400, "Missing OAuth code/state")

    db = SessionLocal()
    try:
        pending = db.query(OAuthPending).filter(OAuthPending.state == state).first()
        if not pending:
            raise HTTPException(400, "Invalid or expired OAuth state")

        token_data = await exchange_code(code, pending.code_verifier)
        access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in")
        expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None

        cred = db.query(DerivCredential).filter(DerivCredential.user_id == pending.user_id).first()
        if not cred:
            cred = DerivCredential(
                user_id=pending.user_id,
                encrypted_access_token=encrypt_token(access_token),
            )
            db.add(cred)
        else:
            cred.encrypted_access_token = encrypt_token(access_token)
        cred.token_type = token_data.get("token_type", "Bearer")
        cred.expires_at = expires_at
        cred.updated_at = datetime.utcnow()

        accounts_payload = await get_accounts(access_token)
        accounts = accounts_payload.get("data", [])
        if isinstance(accounts, dict):
            accounts = [accounts]

        db.query(DerivAccount).filter(DerivAccount.user_id == pending.user_id).delete()
        for a in accounts:
            db.add(DerivAccount(
                user_id=pending.user_id,
                account_id=str(a.get("account_id")),
                account_type=str(a.get("account_type", "")).lower(),
                currency=a.get("currency"),
                status=a.get("status"),
                balance=float(a["balance"]) if a.get("balance") is not None else None,
                raw_json=json.dumps(a),
            ))
        db.delete(pending)
        db.commit()

        if settings.frontend_url:
            return RedirectResponse(settings.frontend_url.rstrip("/") + "/?deriv=connected")
        return {"ok": True, "user_id": pending.user_id, "accounts": accounts}
    finally:
        db.close()

@router.get("/accounts")
async def accounts(user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        rows = db.query(DerivAccount).filter(DerivAccount.user_id == user_id).all()
        return [
            {
                "account_id": x.account_id,
                "account_type": x.account_type,
                "currency": x.currency,
                "status": x.status,
                "balance": x.balance,
            } for x in rows
        ]
    finally:
        db.close()
