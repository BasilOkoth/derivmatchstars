DigitMatchStar V35 — IDEMPOTENT SERVER START

Problem fixed
-------------
V34 can create a server-side TAE research session before START BOT.
The old START flow always POSTed /sessions again, so if the session had
already been started it could return:

    Session is already running

V35 makes the lifecycle idempotent.

Frontend
--------
START BOT now:
1. fetches existing /sessions first;
2. reuses the existing session ID when present;
3. if that session is already running, START becomes a successful no-op;
4. while Trade 0 has no open contract, the latest AI candidate may still sync;
5. it never changes the candidate during an active/open contract;
6. only creates/reconfigures a session when the existing one is idle.

Backend
-------
POST /sessions:
- if the account-scoped session is already running, returns its current state
  with already_running=true instead of HTTP 409.

POST /sessions/{sid}/start:
- repeated calls return ok=true and already_running=true.

TAE
---
Continuous V34 TAE research behavior remains unchanged.
Research can stay active while Trade 0 is idle.
Automated execution remains DEMO-only.
