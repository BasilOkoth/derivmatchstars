#!/usr/bin/env python3
"""Apply a guarded 3-TRADE fixed-target patch to an existing DigitMatchStar engine.py.
Run at repository root: python tools/apply_three_trade_lock.py
Creates engine.py.bak before write. Refuses unknown code shape.
"""
from pathlib import Path
import sys, shutil, ast
p = Path('app/engine.py')
if not p.exists():
    sys.exit('Missing app/engine.py. Run this script from the repo root.')
s = p.read_text(encoding='utf-8')
if 'DMS_THREE_TRADE_TARGET_LOCK_V10' in s:
    print('Already patched.'); sys.exit(0)

def once(old, new, label):
    global s
    n=s.count(old)
    if n!=1: sys.exit(f'SAFETY STOP: {label} must match exactly once (found {n}). No file changed.')
    s=s.replace(old,new,1)

# Lock to persisted s.candidate_digit, not an in-memory flag. current_trade counts buys made.
# At completed trade numbers 1 and 2, retain target; at 3, select V1 for trade 4.
# At 4 and 5 retain, at 6 reselect; etc.
helper='''    # DMS_THREE_TRADE_TARGET_LOCK_V10
    def _three_trade_locked_target(self, s):
        """Persisted target for trade blocks: 1-3, 4-6, ...

        current_trade is the count of trades already purchased in this cycle.
        If the current block has remaining attempts, use the purchased candidate.
        """
        n = int(s.current_trade or 0)
        if n > 0 and n % 3 != 0 and s.candidate_digit is not None:
            d = int(s.candidate_digit)
            if 0 <= d <= 9:
                return d
        return None

'''
needle='    def _choose_scored_digit(self, sid: int, exclude_digit=None, *, lock_target=False, prepared_snapshot=None):\n'
once(needle,helper+needle,'helper insertion')

# Immediate tick-owned recovery: keep the persisted prior digit when not at block boundary.
old='''                desired_next, current_snapshot = self._choose_scored_digit(
                    sid,
                    lock_target=True,
                    prepared_snapshot=prepared_for_this_tick,
                )
                if desired_next is None:
'''
new='''                # DMS_THREE_TRADE_TARGET_LOCK_V10: trades 1-3 share one barrier.
                desired_next = self._three_trade_locked_target(s)
                if desired_next is None:
                    desired_next, current_snapshot = self._choose_scored_digit(
                        sid,
                        lock_target=True,
                        prepared_snapshot=prepared_for_this_tick,
                    )
                if desired_next is None:
'''
once(old,new,'tick-owned recovery')

# Restart recovery (authoritative settled): apply exactly same persisted rule.
old='''                    fresh_digit, snapshot = self._choose_scored_digit(sid, lock_target=True)
                    if fresh_digit is None:
'''
new='''                    # DMS_THREE_TRADE_TARGET_LOCK_V10: restart-safe target persistence.
                    fresh_digit = self._three_trade_locked_target(s)
                    snapshot = {}
                    if fresh_digit is None:
                        fresh_digit, snapshot = self._choose_scored_digit(sid, lock_target=True)
                    if fresh_digit is None:
'''
once(old,new,'settlement/restart recovery')

# Last pre-buy reselection must never override locked candidate.
old='''                scored_digit, snapshot = self._choose_scored_digit(
                    s.id,
                    lock_target=True,
                )
                if scored_digit is None:
'''
new='''                # DMS_THREE_TRADE_TARGET_LOCK_V10: final pre-buy gate.
                scored_digit = self._three_trade_locked_target(s)
                snapshot = {}
                if scored_digit is None:
                    scored_digit, snapshot = self._choose_scored_digit(
                        s.id,
                        lock_target=True,
                    )
                if scored_digit is None:
'''
once(old,new,'final pre-buy reselection')

ast.parse(s)
shutil.copy2(p,p.with_suffix('.py.bak'))
p.write_text(s,encoding='utf-8')
print('Patched',p,'with persisted 3-trade digit lock; backup:',p.with_suffix('.py.bak'))
