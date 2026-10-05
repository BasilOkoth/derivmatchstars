# DigitMatchStar Production OAuth Backend V2

This replaces the earlier single-user/global-token prototype.

## What changed

- No global `DERIV_DEMO_TOKEN`
- No global `DERIV_REAL_TOKEN`
- Deriv OAuth 2.0 Authorization Code + PKCE per user
- Tokens encrypted at rest with Fernet
- User-scoped Deriv accounts
- User-scoped trading sessions
- Current Deriv REST -> OTP -> authenticated WebSocket flow
- Postgres-ready on Render
- DEMO worker can continue after dashboard closure
- REAL worker state/reconciliation is server-side, but each new real-money purchase
  requires explicit confirmation

## Required Render variables

- `DATABASE_URL`
- `DERIV_CLIENT_ID`
- `DERIV_REDIRECT_URI`
- `TOKEN_ENCRYPTION_KEY`
- `PLATFORM_JWT_SECRET`
- `FRONTEND_URL`

Optional:
- `DERIV_LEGACY_APP_ID` if you maintain a legacy Deriv API app
- `DERIV_SCOPE=trade`
- `ALLOW_REAL_MODE=false` initially

## Generate TOKEN_ENCRYPTION_KEY

Run locally once:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Platform authentication contract

The backend expects your existing platform to send:

```http
Authorization: Bearer <your-platform-JWT>
```

The JWT must contain a stable user id in `sub` and be signed using
`PLATFORM_JWT_SECRET`.

If your current platform authentication is not JWT-based yet, adapt this middleware
to your existing authenticated session before production. Do NOT expose
`TRUST_PLATFORM_USER_HEADER=true` to public traffic unless a trusted reverse proxy
guarantees and strips/sets that header.

## Deriv OAuth flow

1. Authenticated platform user calls `GET /auth/deriv/start`
2. Backend returns `authorization_url`
3. Browser redirects to Deriv
4. Deriv returns to `DERIV_REDIRECT_URI`, e.g.
   `https://digitmatchstar-api.onrender.com/auth/deriv/callback`
5. Backend validates state, exchanges the code with PKCE, encrypts the access token,
   fetches the user's demo/real Options accounts and stores them.
6. `GET /auth/deriv/accounts` returns only that user's accounts.
7. When a session needs a WebSocket, backend requests an OTP for the selected account
   and connects to the returned authenticated WebSocket URL.

## Important OAuth lifetime note

Deriv's public OAuth guide documents an `access_token` and `expires_in`. This package
does not invent a refresh-token flow that the cited guide does not document. If the
access token has expired when a new OTP is needed, the user is asked to reconnect Deriv.
An already-open authenticated WebSocket may remain usable until it disconnects, but a
new OTP requires a valid bearer token.

## Core API

- `GET /health`
- `GET /auth/deriv/start`
- `GET /auth/deriv/callback`
- `GET /auth/deriv/accounts`
- `GET /sessions`
- `POST /sessions`
- `POST /sessions/{id}/candidate`
- `POST /sessions/{id}/start`
- `POST /sessions/{id}/pause`
- `POST /sessions/{id}/stop`
- `POST /sessions/{id}/real/confirm`

## Production warning

Do not deploy the previous V1/V1.1 global-token backend for multiple users. This V2
is structured for per-user authorization, but you still need to wire its
`current_user_id()` dependency to your platform's actual login/session mechanism.
