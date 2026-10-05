import httpx
from .config import settings

AUTH_BASE = "https://auth.deriv.com/oauth2"
API_BASE = "https://api.derivws.com"

async def exchange_code(code: str, code_verifier: str):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{AUTH_BASE}/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": settings.deriv_client_id,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": settings.deriv_redirect_uri,
            },
        )
        r.raise_for_status()
        return r.json()

async def get_accounts(access_token: str):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{API_BASE}/trading/v1/options/accounts",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        return r.json()

async def get_ws_url(access_token: str, account_id: str):
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{API_BASE}/trading/v1/options/accounts/{account_id}/otp",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        url = data.get("url")
        if not url:
            raise RuntimeError("Deriv OTP response did not include a WebSocket URL")
        return url
