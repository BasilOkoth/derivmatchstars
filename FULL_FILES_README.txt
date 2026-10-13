DigitMatchStar FULL FILES — DEMO proposal-socket correction

This ZIP contains a complete repository, not a patch.
The modified FULL files are:
  app/engine.py
  app/deriv_ws.py

app/__init__.py is included in full, unmodified; its V7 explicit InvalidContractProposal recovery is preserved.
Other application files have not been changed.

Upload app/engine.py and app/deriv_ws.py to their matching GitHub paths, or upload all repository files as appropriate. Do not move the files to the repository root.

Changes:
  * Tag every quote with its issuing WebSocket connection generation.
  * Detect a reconnect while requesting a quote.
  * Re-quote under the existing database BUY claim if the socket changed before buy.
  * Release the claim and STOP if re-quoting fails before any buy is sent.
  * Preserve V7 retry only for explicit invalid-proposal rejections; NEVER automatically retry uncertain transport outcomes.

Limitations: Connection changes are one possible cause, not a verified root cause.
A successful syntax test is not a live Deriv integration test. Test on DEMO.
Do not assume improved trading profitability or risk characteristics.
