import base64, hashlib, json, secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from .config import settings
from .db import SessionLocal
from .models import OAuthPending, LoginTicket, DerivCredential, DerivAccount
from .security import encrypt_token, issue_platform_jwt, current_user_id
from .deriv_rest import exchange_code, get_accounts

router = APIRouter(tags=["auth"])

def _pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge

def _ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()

def _stable_user_id(accounts: list[dict]) -> str:
    demos = sorted(str(a.get("account_id")) for a in accounts if str(a.get("account_type","")).lower() == "demo" and a.get("account_id"))
    all_ids = sorted(str(a.get("account_id")) for a in accounts if a.get("account_id"))
    anchor = demos[0] if demos else (all_ids[0] if all_ids else None)
    if not anchor:
        raise RuntimeError("No Deriv Options account was returned")
    return "deriv:" + anchor

@router.get("/auth/deriv/start")
def start_deriv_oauth(mode: str = "DEMO"):
    mode = mode.upper()
    if mode not in {"DEMO", "REAL"}:
        raise HTTPException(400, "mode must be DEMO or REAL")
    if not settings.deriv_client_id or not settings.deriv_redirect_uri:
        raise HTTPException(500, "Deriv OAuth is not configured")

    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        db.add(OAuthPending(state=state, code_verifier=verifier, requested_mode=mode))
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
    return {"authorization_url": "https://auth.deriv.com/oauth2/auth?" + urlencode(params)}

@router.get("/auth/deriv/callback")
async def callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(settings.frontend_url.rstrip("/") + "/?auth_error=" + quote(error))
    if not code or not state:
        raise HTTPException(400, "Missing OAuth code/state")

    db = SessionLocal()
    try:
        pending = db.query(OAuthPending).filter(OAuthPending.state == state).first()
        if not pending:
            raise HTTPException(400, "Invalid or expired OAuth state")

        token_data = await exchange_code(code, pending.code_verifier)
        access_token = token_data["access_token"]
        accounts_payload = await get_accounts(access_token)
        accounts = accounts_payload.get("data", [])
        if isinstance(accounts, dict):
            accounts = [accounts]
        user_id = _stable_user_id(accounts)

        expires_in = token_data.get("expires_in")
        expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
        cred = db.query(DerivCredential).filter(DerivCredential.user_id == user_id).first()
        if not cred:
            cred = DerivCredential(user_id=user_id, encrypted_access_token=encrypt_token(access_token))
            db.add(cred)
        else:
            cred.encrypted_access_token = encrypt_token(access_token)
        cred.token_type = token_data.get("token_type", "Bearer")
        cred.expires_at = expires_at
        cred.updated_at = datetime.utcnow()

        db.query(DerivAccount).filter(DerivAccount.user_id == user_id).delete()
        for a in accounts:
            if not a.get("account_id"):
                continue
            db.add(DerivAccount(
                user_id=user_id,
                account_id=str(a["account_id"]),
                account_type=str(a.get("account_type", "")).lower(),
                currency=a.get("currency"),
                status=a.get("status"),
                balance=float(a["balance"]) if a.get("balance") is not None else None,
                raw_json=json.dumps(a),
            ))

        ticket = secrets.token_urlsafe(48)
        db.add(LoginTicket(
            ticket_hash=_ticket_hash(ticket),
            user_id=user_id,
            requested_mode=pending.requested_mode,
            expires_at=datetime.utcnow() + timedelta(minutes=2),
        ))
        requested_mode = pending.requested_mode
        db.delete(pending)
        db.commit()
    finally:
        db.close()

    url = (
        settings.frontend_url.rstrip("/")
        + "/?dms_ticket=" + quote(ticket)
        + "&mode=" + quote(requested_mode)
    )
    return RedirectResponse(url)

class TicketExchange(BaseModel):
    ticket: str

@router.post("/auth/platform/exchange")
def exchange_ticket(body: TicketExchange):
    db = SessionLocal()
    try:
        row = db.query(LoginTicket).filter(LoginTicket.ticket_hash == _ticket_hash(body.ticket)).first()
        if not row or row.used or row.expires_at <= datetime.utcnow():
            raise HTTPException(401, "Invalid or expired login ticket")
        row.used = True
        token = issue_platform_jwt(row.user_id)
        accounts = db.query(DerivAccount).filter(DerivAccount.user_id == row.user_id).all()
        db.commit()
        return {
            "token": token,
            "requested_mode": row.requested_mode,
            "accounts": [
                {
                    "account_id": a.account_id,
                    "account_type": a.account_type,
                    "currency": a.currency,
                    "status": a.status,
                    "balance": a.balance,
                } for a in accounts
            ],
        }
    finally:
        db.close()

@router.get("/auth/platform/me")
def me(user_id: str = Depends(current_user_id)):
    db = SessionLocal()
    try:
        accounts = db.query(DerivAccount).filter(DerivAccount.user_id == user_id).all()
        return {
            "user_id": user_id,
            "accounts": [
                {
                    "account_id": a.account_id,
                    "account_type": a.account_type,
                    "currency": a.currency,
                    "status": a.status,
                    "balance": a.balance,
                } for a in accounts
            ],
        }
    finally:
        db.close()
