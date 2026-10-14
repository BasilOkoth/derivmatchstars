DigitMatchStar complete server-feed recovery fix (V2)

Replace your GitHub files with the contents of this ZIP, preserving folder structure.
Changes: app/__init__.py, app/engine.py, app/deriv_ws.py.

- On a stale feed, replace the actual WebSocket rather than resubscribe on a dead/half-open one.
- Invalidate subscription records for sessions sharing that client.
- Track transport identity per subscription to prevent treating an old subscription ID as active after reconnect.
- Detect a completed WebSocket reader task even when the underlying TCP socket claims it is open.

Existing V1 score >= 9 and recovery rules are unchanged. Test DEMO, and check Render logs for feed recovery warnings.
The execution gap for pending trade 2 is a distinct problem; this release focuses on recurring ranking freezes.
Python syntax tested, live Deriv integration not tested.
