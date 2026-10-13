import httpx

from .config import settings


AUTH_BASE = "https://auth.deriv.com/oauth2"
API_BASE = "https://api.derivws.com"


def _http_error(prefix: str, response: httpx.Response) -> RuntimeError:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = (
                payload.get("message")
                or payload.get("error_description")
                or payload.get("error")
                or payload.get("detail")
                or str(payload)
            )
        else:
            detail = str(payload)
    except Exception:
        detail = (response.text or "").strip()

    if len(detail) > 500:
        detail = detail[:500] + "…"

    return RuntimeError(
        f"{prefix} HTTP {response.status_code}"
        + (f": {detail}" if detail else "")
    )


async def exchange_code(code: str, code_verifier: str):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{AUTH_BASE}/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "authorization_code",
                "client_id": settings.deriv_client_id,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": settings.deriv_redirect_uri,
            },
        )

        if response.is_error:
            raise _http_error("OAuth token exchange failed", response)

        return response.json()


async def get_accounts(access_token: str):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{API_BASE}/trading/v1/options/accounts",
            headers={
                "Authorization": f"Bearer {access_token}"
            },
        )

        if response.is_error:
            raise _http_error("Options accounts request failed", response)

        return response.json()


async def get_ws_url(access_token: str, account_id: str):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{API_BASE}/trading/v1/options/accounts/{account_id}/otp",
            headers={
                "Authorization": f"Bearer {access_token}"
            },
        )

        if response.is_error:
            raise _http_error("Options OTP request failed", response)

        payload = response.json()
        data = payload.get("data", payload)

        if not isinstance(data, dict):
            raise RuntimeError(
                "Deriv OTP response had an unexpected format"
            )

        url = (
            data.get("url")
            or data.get("ws_url")
            or data.get("websocket_url")
        )

        if not url:
            # Expose structure only; never expose the OAuth token.
            raise RuntimeError(
                "Deriv OTP response did not contain a WebSocket URL; "
                f"keys={list(data.keys())}"
            )

        return str(url)
