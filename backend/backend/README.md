# DigitMatchStar V2.1 Auth Integration

Production-oriented flow:

1. Browser asks API for `/auth/deriv/start?mode=DEMO|REAL`.
2. API owns PKCE verifier/state and redirects the user to Deriv.
3. Deriv returns to the Render callback.
4. API exchanges the code, stores the Deriv token encrypted in Postgres, and stores accounts.
5. API redirects the browser with a short-lived one-time login ticket.
6. Browser exchanges the ticket for a DigitMatchStar JWT.
7. The raw Deriv OAuth access token never needs to be stored in browser localStorage.
8. Server execution endpoints require the DigitMatchStar JWT.

Required Render values:
- DATABASE_URL
- DERIV_CLIENT_ID
- DERIV_REDIRECT_URI=https://digitmatchstar-api.onrender.com/auth/deriv/callback
- TOKEN_ENCRYPTION_KEY
- PLATFORM_JWT_SECRET
- FRONTEND_URL=https://www.digitmatchstar.com
- ALLOW_REAL_MODE=false initially
- PYTHON_VERSION=3.12.11

Execution:
- DEMO can continue a fixed-digit recovery cycle after the browser closes.
- The server stops the cycle after a confirmed win or at max trades.
- REAL mode is deliberately confirmation-based for every new purchase.
- AI/SAFE-TICK candidate selection is still browser-side research and is not yet migrated
  into the server worker. Therefore unattended server continuation currently applies to the
  already-selected digit/cycle, not autonomous AI reselection after the cycle ends.
