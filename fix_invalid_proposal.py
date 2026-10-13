"""Patch current GitHub app/__init__.py, preserving V5-V8 and REAL manual routes.

Fix: do not use a pre-armed proposal ID after it may have gone stale.
A fresh quote is requested on the active client's socket directly before DEMO buy.
The existing V7 explicit-rejection retry and engine's claim/uncertain stop remain intact.
"""
from pathlib import Path
import ast
import sys

source = Path("app/__init__.py")
if not source.exists():
    raise SystemExit("Run from repository root")
original = source.read_text(encoding="utf-8")
anchor = '    async def _execute_buy_retry_invalid_proposal(\n'
if original.count(anchor) != 1:
    raise SystemExit("Expected current V7 buy wrapper not found exactly once; no modifications")
marker = '        try:\n            return await _original_execute_buy_v7(\n'
if original.count(marker) != 1:
    raise SystemExit("V7 original-call anchor not unique; no modifications")

replacement = '        # Pre-armed DEMO quotes may expire/become invalid by the time a\n        # recovery buy is attempted. Fetch a NEW proposal on the same socket\n        # immediately before purchase, preserving the frozen digit and stake.\n        # REAL manual purchases are intentionally unaffected.\n        if prearmed and str(getattr(s, "account_mode", "")).upper() == "DEMO":\n            payload = dict(payload)\n            fresh = await self._request_proposal_payload(\n                client,\n                symbol=str(s.symbol),\n                digit=int(payload["digit"]),\n                stake=float(payload["stake"]),\n                trade_no=int(payload["trade_no"]),\n                currency=str(payload.get("currency") or await self._currency_for(db, s)),\n            )\n            payload.update(fresh)\n            payload["proposal_freshened_before_buy"] = True\n'
if "proposal_freshened_before_buy" in original:
    print("Already patched; no changes")
    sys.exit(0)
patched = original.replace(marker, replacement + marker, 1)
ast.parse(patched, filename=str(source))
source.write_text(patched, encoding="utf-8")
print("Patched V7 DEMO prearmed-proposal refresh without enabling REAL automation")
