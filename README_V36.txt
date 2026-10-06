DigitMatchStar V36 — DEDICATED TAE STREAM

Root problem addressed
----------------------
V34/V35 shared the same Deriv WebSocket client for:
- live TAE ticks
- proposal requests
- buys
- contract settlement/reconciliation

The dashboard could therefore show persisted History 100/100 while receiving
zero NEW server TAE ticks, leaving:
    Pending = 0
    Matured = 0/250

V36 separates research transport from execution transport.

Architecture
------------
Dedicated research WebSocket per DEMO session:
    Deriv ticks -> TAE only

Execution WebSocket:
    proposal / buy / settlement / strategy tick fallback

The two streams are deduplicated by Deriv epoch, so one market tick can enter
TAE only once.

Research watchdog
-----------------
The dedicated research task:
- remains alive while Trade 0 is idle
- verifies the subscription every 8 seconds
- reconnects if the socket/subscription disappears
- reconnects if no new epoch arrives for >8 seconds
- exposes actual errors in the dashboard instead of swallowing them

Dashboard diagnostics
---------------------
New fields:
- Server research stream: LIVE / RECONNECTING
- Server TAE ticks
- Last server tick epoch + digit
- Research stream error

Healthy behavior
----------------
After deployment you should see Server TAE ticks increasing every R_10 tick.

With history already 100/100:
- Pending rises 1,2,... to about 10
- after 10 new server ticks, Matured begins 1/250, 2/250, ...
- no paid trade is required

Target synchronization
----------------------
Research target now prefers the current AI recommendation directly rather than
requiring a possibly stale sessionState.mode flag.

Safety
------
Dedicated TAE socket is read-only.
Automated execution remains DEMO-only.
TAE does not control or alter Deriv RNG.
