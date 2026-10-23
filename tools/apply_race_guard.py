#!/usr/bin/env python3
"""Guarded DEMO + REAL engine patch: settlement-first, single-open-contract, three-trade lock."""
from pathlib import Path
import ast, shutil, sys
p=Path('app/engine.py')
if not p.is_file(): sys.exit('Run from repo root: missing app/engine.py')
s=p.read_text(encoding='utf-8')
if 'DMS_RACE_GUARD_V11' in s: sys.exit('Race guard already installed')
def replace_once(old,new,label):
    global s
    count=s.count(old)
    if count!=1: sys.exit(f'SAFETY STOP {label}: expected exactly 1 location, got {count}. No changes made.')
    s=s.replace(old,new,1)

# shared DEMO + REAL selector, target stored on TradingSession row
if 'DMS_THREE_TRADE_TARGET_LOCK_V10' not in s:
    replace_once('    def _choose_scored_digit(self, sid: int, exclude_digit=None, *, lock_target=False, prepared_snapshot=None):', '''    # DMS_THREE_TRADE_TARGET_LOCK_V10\n    def _three_trade_locked_target(self, s):
        """Persisted digit for next BUY within a three-purchase block."""
        n = int(s.current_trade or 0)
        if n > 0 and n % 3 != 0 and s.candidate_digit is not None:
            d = int(s.candidate_digit)
            if 0 <= d <= 9: return d
        return None

    def _choose_scored_digit(self, sid: int, exclude_digit=None, *, lock_target=False, prepared_snapshot=None):''', 'target-lock helper')
    replace_once('''                desired_next, current_snapshot = self._choose_scored_digit(
                    sid,
                    lock_target=True,
                    prepared_snapshot=prepared_for_this_tick,
                )''','''                desired_next = self._three_trade_locked_target(s)
                if desired_next is None:
                    desired_next, current_snapshot = self._choose_scored_digit(
                        sid, lock_target=True, prepared_snapshot=prepared_for_this_tick,
                    )''','immediate recovery selector')
    replace_once('''                    fresh_digit, snapshot = self._choose_scored_digit(sid, lock_target=True)''','''                    fresh_digit = self._three_trade_locked_target(s)
                    snapshot = {}
                    if fresh_digit is None:
                        fresh_digit, snapshot = self._choose_scored_digit(sid, lock_target=True)''','settled recovery selector')
    replace_once('''                scored_digit, snapshot = self._choose_scored_digit(
                    s.id,
                    lock_target=True,
                )''','''                scored_digit = self._three_trade_locked_target(s)
                snapshot = {}
                if scored_digit is None:
                    scored_digit, snapshot = self._choose_scored_digit(
                        s.id, lock_target=True,
                    )''','pre-buy selector')

# Explicit BUY claim cannot be created while any other trade is still open/ambiguous.
replace_once('''        pending = self._pending_json(row.pending_trade_json)

        # Another process already owns this exact BUY.''','''        # DMS_RACE_GUARD_V11: shared DEMO/REAL authoritative BUY boundary.
        # Never send a fresh purchase while the previous contract is open or
        # before its official settled LOSS is committed to the DB.
        pending = self._pending_json(row.pending_trade_json)
        if row.open_contract_id or pending.get("kind") == "BUY_CLAIM":
            db.rollback()
            return None
        if int(row.current_trade or 0) > 0:
            previous = (
                db.query(TradeLog)
                .filter(TradeLog.trading_session_id == int(sid))
                .order_by(TradeLog.id.desc())
                .first()
            )
            if (
                previous is None
                or int(previous.trade_no or 0) != int(row.current_trade or 0)
                or str(previous.status or "").upper() != "SETTLED"
                or previous.profit is None
                or float(previous.profit) >= 0
            ):
                db.rollback()
                return None
            expected_locked = self._three_trade_locked_target(row)
            if expected_locked is not None and int(digit) != int(expected_locked):
                db.rollback()
                return None

        # Another process already owns this exact BUY.''','claim preconditions')

# Retained digit must pass official settled-loss and DB candidate checks, but
# does NOT require a fresh V1 snapshot, which would violate the lock.
replace_once('''        if not gate_ok:
            row.pending_trade_json = None''','''        # DMS_RACE_GUARD_V11: within a 3-trade block, authorize the
        # persisted purchased barrier rather than a newly rescored V1 top.
        expected_locked = self._three_trade_locked_target(row)
        if expected_locked is not None and int(digit) == int(expected_locked):
            gate_ok = True
            gate_top = int(expected_locked)
            fusion = {"source": "THREE_TRADE_PERSISTED_LOCK"}

        if not gate_ok:
            row.pending_trade_json = None''','locked gate')

# A local T+1 callback is useful for diagnostics, never purchase authorization.
# A settled WIN ends cycle, settled LOSS lets worker handle next trade.
replace_once('''                if is_win:
                    # MATCH: target == exact strategy tick last digit.''','''                # DMS_RACE_GUARD_V11: no fast/local-tick recovery purchases.
                # This callback is provisional. Deriv settlement is authoritative.
                s.phase = "WAITING_OFFICIAL_SETTLEMENT"
                s.last_error = None
                s.updated_at = datetime.utcnow()
                db.commit()
                return

                if is_win:
                    # MATCH: target == exact strategy tick last digit.''','disable fast recovery')

# A settled callback needs to stop an official win even if the local callback did
# not happen, and must release fast owner to allow settled-loss continuation.
replace_once('''                # Official settlement does NOT advance the strategy.
                # It only verifies the already-made fast decision.
                fast = self.fast_contracts.get(sid)''','''                # DMS_RACE_GUARD_V11: settled WIN closes the cycle; official
                # settled LOSS is consumed only by the normal worker step.
                if profit > 0 and s.phase not in (
                    "RECONCILE_MISMATCH", "RECONCILE_TICK_MISMATCH"
                ):
                    s.running = False
                    s.paused = False
                    s.phase = "OFFICIAL_WON"
                # Stop on any disagreement between provisional result and
                # official payout. Never continue an inconsistent cycle.
                previous_fast = self.fast_contracts.get(sid)
                if (
                    previous_fast
                    and str(previous_fast.get("contract_id")) == str(contract_id)
                    and previous_fast.get("fast_result")
                    and previous_fast.get("fast_result") != ("WIN" if profit > 0 else "LOSS")
                ):
                    s.running = False
                    s.phase = "RECONCILE_MISMATCH"
                    s.last_error = f"Local/official outcome disagreement on {contract_id}"
                # No active fast-owner may strand the worker once settlement
                # has been durably recorded. Retire only this contract owner.
                active_owner = self.fast_contracts.get(sid)
                if active_owner and str(active_owner.get("contract_id")) == str(contract_id):
                    self.fast_contracts.pop(sid, None)

                # Official settlement does NOT advance the strategy.
                # It only verifies the already-made fast decision.
                fast = self.fast_contracts.get(sid)''','settlement release')

# Terminal trade, stopping, and restart paths left unchanged.
ast.parse(s, filename=str(p))
backup=p.with_name('engine.py.pre_v11.bak')
shutil.copy2(p,backup)
p.write_text(s,encoding='utf-8')
print(f'Updated {p}; backup: {backup}. Test DEMO concurrency, restarts and settle callbacks before REAL.')
