"""Idempotent patch for BasilOkoth/derivmatchstars current code.
Does not change order execution, REAL permissions, or ranking algorithm.
"""
from pathlib import Path
import ast

main = Path('app/main.py')
init = Path('app/__init__.py')
if not (main.exists() and init.exists()):
    raise SystemExit('Run in repository root (app/main.py and app/__init__.py required)')
a, b = main.read_text(), init.read_text()
start = a.find('def digit_score_for_session(session_id: int):')
end = a.find('\n@app.', start)
if start < 0 or end < 0:
    raise SystemExit('Could not identify complete digit_score_for_session section. No changes made.')
replacement = '''def digit_score_for_session(session_id: int):
    """Read-only status view of the latest canonical tick ranking.

    Never score during an API GET: re-scoring overwrote rank_epoch / canonical_tick,
    and could display a stale selected digit from a different snapshot.
    """
    sid = int(session_id)
    snapshot = dict((getattr(engine, "digit_score_snapshots", {}) or {}).get(sid) or {})
    if not snapshot:
        return {
            "ready": False, "ranking": [], "selected_digit": None,
            "target_eligible": False, "history_count": len(engine._digit_history(sid)),
            "minimum_history": int(engine.digit_scorer.min_history),
            "rank_epoch": None, "canonical_tick": None,
            "feed_state": "WAITING_FOR_SERVER_RANK",
        }
    ranked = snapshot.get("ranking") or []
    top = ranked[0] if ranked else None
    try:
        score = float(top["score"]) if top else None
        digit = int(top["digit"]) if top else None
    except (ValueError, TypeError, KeyError):
        score, digit = None, None
    threshold = float(snapshot.get("target_min_score", 9.0))
    eligible = bool(snapshot.get("ready") and score is not None and
                    score >= threshold and digit is not None)
    snapshot["raw_selected_digit"] = digit
    snapshot["raw_top_score"] = score
    snapshot["target_eligible"] = eligible
    snapshot["selected_digit"] = digit if eligible else None
    snapshot["feed_state"] = ("LIVE_RANK" if snapshot.get("rank_epoch") else
                              "RANK_MISSING_EPOCH")
    return snapshot

'''
a = a[:start] + replacement + a[end:]
# Status views must not expose outdated live_next_target when gate says no.
a = a.replace('"live_next_target": engine.live_next_target.get(s.id),',
              '"live_next_target": digit_score_for_session(s.id).get("selected_digit"),')
# Ensure the canonical tick callback decorates the authoritative in-memory snapshot,
# once the original tick handler has computed it. No further ranking work done here.
old = '''        return await _original_handle_tick_v5(
            self,
            sid=int(sid),
            user_id=user_id,
            account_id=account_id,
            symbol=symbol,
            data=data,
        )'''
new = '''        result = await _original_handle_tick_v5(
            self,
            sid=int(sid),
            user_id=user_id,
            account_id=account_id,
            symbol=symbol,
            data=data,
        )
        tick = (data or {}).get("tick") or {}
        epoch = int(tick.get("epoch") or 0)
        snap = (getattr(self, "digit_score_snapshots", {}) or {}).get(int(sid))
        if snap is not None and epoch and int(getattr(self, "_last_scored_epoch", {}).get(int(sid), 0)) == epoch:
            snap["rank_epoch"] = epoch
            snap["canonical_tick"] = {
                "epoch": epoch,
                "digit": self._tick_last_digit(tick),
                "quote": tick.get("quote"),
                "pip_size": tick.get("pip_size"),
                "symbol": str(symbol),
            }
        return result'''
if new not in b:
    if b.count(old) != 1:
        raise SystemExit('Canonical tick wrapper differs from expected code; no changes made.')
    b = b.replace(old,new)
ast.parse(a); ast.parse(b)
main.write_text(a)
init.write_text(b)
print('Updated app/main.py and app/__init__.py; tick ranking is read-only in GET responses.')
