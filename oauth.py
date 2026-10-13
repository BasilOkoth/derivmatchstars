import base64
import hashlib
import json
import secrets

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote

import jwt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import settings
from .db import SessionLocal
from .models import OAuthPending, DerivCredential, DerivAccount
from .security import current_user_id, encrypt_token
from .deriv_rest import exchange_code, get_accounts


# No global prefix because this file now exposes:
# /auth/deriv/*
# /auth/platform/*
router = APIRouter(tags=["authentication"])


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

OAUTH_MODE_PREFIX = "__oauth_mode__:"
LOGIN_TICKET_PREFIX = "__login_ticket__:"
LOGIN_TICKET_TTL_MINUTES = 2
PLATFORM_SESSION_HOURS = 12


# ---------------------------------------------------------------------------
# REQUEST MODELS
# ---------------------------------------------------------------------------

class TicketExchangeRequest(BaseModel):
    ticket: str


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _pkce():
    """
    Generate PKCE verifier + S256 challenge.

    The verifier remains server-side in Postgres.
    It is never stored in the user's browser.
    """
    verifier = secrets.token_urlsafe(64)

    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        )
        .decode()
        .rstrip("=")
    )

    return verifier, challenge


def _ticket_db_key(ticket: str) -> str:
    """
    Store only a SHA256 representation of the temporary login ticket.
    """
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    return f"{LOGIN_TICKET_PREFIX}{digest}"


def _requested_mode_from_pending(pending: OAuthPending) -> str:
    value = str(pending.user_id or "")

    if value.startswith(OAUTH_MODE_PREFIX):
        mode = value[len(OAUTH_MODE_PREFIX):].upper()

        if mode in {"DEMO", "REAL"}:
            return mode

    return "DEMO"


def _stable_user_id(accounts):
    """
    Derive an internal DigitMatchStar user identifier from the connected
    Deriv Options accounts.

    We intentionally do not expose or use the OAuth access token as a user ID.
    """
    account_ids = sorted(
        str(account.get("account_id"))
        for account in accounts
        if account.get("account_id")
    )

    if not account_ids:
        raise HTTPException(
            status_code=400,
            detail="No Deriv Options trading account was returned.",
        )

    # Stable deterministic identifier without placing raw account IDs
    # directly into the JWT subject.
    source = "|".join(account_ids)

    digest = hashlib.sha256(source.encode()).hexdigest()

    return f"deriv:{digest}"


def _issue_platform_jwt(user_id: str) -> str:
    """
    Issue the JWT used by the DigitMatchStar frontend when communicating
    with the Render backend.

    This is NOT the Deriv OAuth access token.
    """
    if not settings.platform_jwt_secret:
        raise HTTPException(
            status_code=500,
            detail="PLATFORM_JWT_SECRET is not configured",
        )

    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(
            (
                now + timedelta(hours=PLATFORM_SESSION_HOURS)
            ).timestamp()
        ),
        "type": "digitmatchstar_session",
    }

    return jwt.encode(
        payload,
        settings.platform_jwt_secret,
        algorithm=settings.platform_jwt_algorithm,
    )


def _frontend_url():
    if not settings.frontend_url:
        raise HTTPException(
            status_code=500,
            detail="FRONTEND_URL is not configured",
        )

    return settings.frontend_url.rstrip("/")


# ---------------------------------------------------------------------------
# START DERIV OAUTH
# ---------------------------------------------------------------------------

@router.get("/auth/deriv/start")
def start_deriv_oauth(mode: str = "DEMO"):
    """
    PUBLIC endpoint.

    A user does NOT need a DigitMatchStar JWT yet.

    This fixes the previous circular-authentication problem where
    DigitMatchStar required a platform JWT before allowing the user
    to obtain one through Deriv OAuth.
    """

    mode = str(mode or "DEMO").upper()

    if mode not in {"DEMO", "REAL"}:
        raise HTTPException(
            status_code=400,
            detail="mode must be DEMO or REAL",
        )

    if not settings.deriv_client_id:
        raise HTTPException(
            status_code=500,
            detail="DERIV_CLIENT_ID is not configured",
        )

    if not settings.deriv_redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="DERIV_REDIRECT_URI is not configured",
        )

    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)

    db = SessionLocal()

    try:
        pending = OAuthPending(
            state=state,

            # Current database schema requires user_id.
            # Before authentication we use it only to remember
            # whether DEMO or REAL was requested.
            user_id=f"{OAUTH_MODE_PREFIX}{mode}",

            code_verifier=verifier,
            created_at=datetime.utcnow(),
        )

        db.add(pending)
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

    authorization_url = (
        "https://auth.deriv.com/oauth2/auth?"
        + urlencode(params)
    )

    return {
        "authorization_url": authorization_url,
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# DERIV CALLBACK
# ---------------------------------------------------------------------------

@router.get("/auth/deriv/callback")
async def deriv_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """
    Deriv redirects here after authorization.

    The backend:
    1. validates OAuth state
    2. exchanges code using server-held PKCE verifier
    3. retrieves Deriv Options accounts
    4. encrypts the Deriv access token
    5. stores accounts
    6. converts the OAuth pending record into a one-time login ticket
    7. redirects to the frontend
    """

    frontend = _frontend_url()

    if error:
        message = error_description or error

        return RedirectResponse(
            frontend
            + "/?auth_error="
            + quote(str(message))
        )

    if not code or not state:
        return RedirectResponse(
            frontend
            + "/?auth_error="
            + quote("Missing OAuth code or state")
        )

    db = SessionLocal()

    try:
        pending = (
            db.query(OAuthPending)
            .filter(OAuthPending.state == state)
            .first()
        )

        if not pending:
            return RedirectResponse(
                frontend
                + "/?auth_error="
                + quote("Invalid or expired OAuth state")
            )

        # Avoid allowing very old OAuth attempts to be completed.
        if pending.created_at:
            age = datetime.utcnow() - pending.created_at

            if age > timedelta(minutes=15):
                db.delete(pending)
                db.commit()

                return RedirectResponse(
                    frontend
                    + "/?auth_error="
                    + quote("OAuth session expired. Please connect again.")
                )

        requested_mode = _requested_mode_from_pending(pending)

        # Exchange authorization code for Deriv OAuth token.
        token_data = await exchange_code(
            code,
            pending.code_verifier,
        )

        access_token = token_data.get("access_token")

        if not access_token:
            raise HTTPException(
                status_code=400,
                detail="Deriv token exchange returned no access token",
            )

        # Load all available Options accounts.
        accounts_payload = await get_accounts(access_token)

        accounts = accounts_payload.get("data", [])

        if isinstance(accounts, dict):
            accounts = [accounts]

        if not isinstance(accounts, list):
            accounts = []

        accounts = [
            account
            for account in accounts
            if account and account.get("account_id")
        ]

        if not accounts:
            return RedirectResponse(
                frontend
                + "/?auth_error="
                + quote(
                    "No Deriv Options trading account was returned "
                    "for this login."
                )
            )

        # Validate requested account mode.
        requested_lower = requested_mode.lower()

        matching_accounts = [
            account
            for account in accounts
            if str(
                account.get("account_type", "")
            ).lower() == requested_lower
        ]

        if requested_mode == "REAL" and not matching_accounts:
            return RedirectResponse(
                frontend
                + "/?auth_error="
                + quote(
                    "No REAL Deriv Options account is available "
                    "for this login."
                )
            )

        # Generate deterministic internal user identifier.
        user_id = _stable_user_id(accounts)

        # ------------------------------------------------------------------
        # SAVE ENCRYPTED DERIV TOKEN
        # ------------------------------------------------------------------

        expires_in = token_data.get("expires_in")

        expires_at = None

        if expires_in:
            try:
                expires_at = (
                    datetime.utcnow()
                    + timedelta(seconds=int(expires_in))
                )
            except Exception:
                expires_at = None

        credential = (
            db.query(DerivCredential)
            .filter(
                DerivCredential.user_id == user_id
            )
            .first()
        )

        encrypted_access_token = encrypt_token(access_token)

        if not credential:
            credential = DerivCredential(
                user_id=user_id,
                encrypted_access_token=encrypted_access_token,
            )

            db.add(credential)

        else:
            credential.encrypted_access_token = (
                encrypted_access_token
            )

        credential.token_type = token_data.get(
            "token_type",
            "Bearer",
        )

        credential.expires_at = expires_at
        credential.updated_at = datetime.utcnow()

        # ------------------------------------------------------------------
        # SAVE DERIV ACCOUNTS
        # ------------------------------------------------------------------

        (
            db.query(DerivAccount)
            .filter(DerivAccount.user_id == user_id)
            .delete()
        )

        for account in accounts:
            account_id = str(account.get("account_id"))

            account_type = str(
                account.get(
                    "account_type",
                    "",
                )
            ).lower()

            balance = None

            if account.get("balance") is not None:
                try:
                    balance = float(account["balance"])
                except Exception:
                    balance = None

            db.add(
                DerivAccount(
                    user_id=user_id,
                    account_id=account_id,
                    account_type=account_type,
                    currency=account.get("currency"),
                    status=account.get("status"),
                    balance=balance,
                    raw_json=json.dumps(account),
                    updated_at=datetime.utcnow(),
                )
            )

        # ------------------------------------------------------------------
        # CONVERT OAUTH RECORD INTO ONE-TIME LOGIN TICKET
        # ------------------------------------------------------------------

        login_ticket = secrets.token_urlsafe(48)

        pending.state = _ticket_db_key(login_ticket)

        # Now that authentication is complete, user_id becomes
        # the real internal DigitMatchStar user ID.
        pending.user_id = user_id

        # OAuth verifier is no longer needed.
        # Reuse the existing text column to remember the requested mode
        # without requiring a database migration.
        pending.code_verifier = requested_mode

        # Reset timestamp so ticket TTL begins NOW.
        pending.created_at = datetime.utcnow()

        db.commit()

        # The browser receives ONLY this short-lived one-time ticket.
        # It does NOT receive the Deriv access token.
        redirect_query = urlencode(
            {
                "dms_ticket": login_ticket,
                "mode": requested_mode,
            }
        )

        return RedirectResponse(
            f"{frontend}/?{redirect_query}"
        )

    except HTTPException:
        raise

    except Exception as exc:
        db.rollback()

        return RedirectResponse(
            frontend
            + "/?auth_error="
            + quote(str(exc))
        )

    finally:
        db.close()


# ---------------------------------------------------------------------------
# EXCHANGE ONE-TIME LOGIN TICKET FOR PLATFORM JWT
# ---------------------------------------------------------------------------

@router.post("/auth/platform/exchange")
def exchange_login_ticket(
    body: TicketExchangeRequest,
):
    """
    Exchange the short-lived one-time OAuth completion ticket
    for the DigitMatchStar platform JWT.

    Ticket is deleted immediately after successful use.
    """

    ticket = str(body.ticket or "").strip()

    if not ticket:
        raise HTTPException(
            status_code=400,
            detail="Login ticket is required",
        )

    db = SessionLocal()

    try:
        ticket_key = _ticket_db_key(ticket)

        pending = (
            db.query(OAuthPending)
            .filter(
                OAuthPending.state == ticket_key
            )
            .first()
        )

        if not pending:
            raise HTTPException(
                status_code=401,
                detail="Invalid or already-used login ticket",
            )

        # Tickets are intentionally very short lived.
        if not pending.created_at:
            db.delete(pending)
            db.commit()

            raise HTTPException(
                status_code=401,
                detail="Invalid login ticket",
            )

        age = datetime.utcnow() - pending.created_at

        if age > timedelta(
            minutes=LOGIN_TICKET_TTL_MINUTES
        ):
            db.delete(pending)
            db.commit()

            raise HTTPException(
                status_code=401,
                detail="Login ticket expired. Connect through Deriv again.",
            )

        user_id = pending.user_id

        requested_mode = str(
            pending.code_verifier or "DEMO"
        ).upper()

        if requested_mode not in {"DEMO", "REAL"}:
            requested_mode = "DEMO"

        # Make ticket one-time BEFORE returning session.
        db.delete(pending)
        db.commit()

        platform_token = _issue_platform_jwt(
            user_id
        )

        accounts = (
            db.query(DerivAccount)
            .filter(
                DerivAccount.user_id == user_id
            )
            .all()
        )

        return {
            "token": platform_token,
            "token_type": "Bearer",
            "expires_in": PLATFORM_SESSION_HOURS * 3600,
            "requested_mode": requested_mode,
            "accounts": [
                {
                    "account_id": account.account_id,
                    "account_type": account.account_type,
                    "currency": account.currency,
                    "status": account.status,
                    "balance": account.balance,
                }
                for account in accounts
            ],
        }

    finally:
        db.close()


# ---------------------------------------------------------------------------
# PLATFORM AUTH STATUS
# ---------------------------------------------------------------------------

@router.get("/auth/platform/me")
def platform_me(
    user_id: str = Depends(current_user_id),
):
    """
    Verify DigitMatchStar platform JWT and return connected accounts.
    """

    db = SessionLocal()

    try:
        accounts = (
            db.query(DerivAccount)
            .filter(
                DerivAccount.user_id == user_id
            )
            .all()
        )

        return {
            "authenticated": True,
            "user_id": user_id,
            "accounts": [
                {
                    "account_id": account.account_id,
                    "account_type": account.account_type,
                    "currency": account.currency,
                    "status": account.status,
                    "balance": account.balance,
                }
                for account in accounts
            ],
        }

    finally:
        db.close()


# ---------------------------------------------------------------------------
# CONNECTED DERIV ACCOUNTS
# ---------------------------------------------------------------------------

@router.get("/auth/deriv/accounts")
def deriv_accounts(
    user_id: str = Depends(current_user_id),
):
    db = SessionLocal()

    try:
        rows = (
            db.query(DerivAccount)
            .filter(
                DerivAccount.user_id == user_id
            )
            .all()
        )

        return [
            {
                "account_id": row.account_id,
                "account_type": row.account_type,
                "currency": row.currency,
                "status": row.status,
                "balance": row.balance,
            }
            for row in rows
        ]

    finally:
        db.close()
