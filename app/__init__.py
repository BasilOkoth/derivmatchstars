"""
DigitMatchStar canonical tick/rank provenance shim.

Research/display only:
- Does not place trades.
- Does not alter stakes.
- Does not alter the open contract target.
- Does not change DigitScore ranking mathematics.

It enriches MultiUserEngine._score_all_digits() with the exact server tick
and epoch provenance required by the browser synchronization panel.
"""

from .engine import MultiUserEngine


if not getattr(MultiUserEngine, "_dms_sync_provenance_v2_installed", False):
    _original_score_all_digits = MultiUserEngine._score_all_digits

    def _score_all_digits_with_provenance(self, sid: int, exclude_digit=None):
        snapshot = _original_score_all_digits(
            self,
            sid,
            exclude_digit=exclude_digit,
        )

        # The exact canonical tick most recently received by the SERVER.
        latest_tick = dict((getattr(self, "latest_ticks", {}) or {}).get(sid) or {})

        try:
            server_epoch = int(
                latest_tick.get("epoch")
                or (getattr(self, "latest_tick_epoch", {}) or {}).get(sid)
                or 0
            )
        except Exception:
            server_epoch = 0

        try:
            rank_epoch = int(
                (getattr(self, "_last_scored_epoch", {}) or {}).get(sid)
                or 0
            )
        except Exception:
            rank_epoch = 0

        # Compute the server tick digit with the same canonical formatter used
        # by the execution engine.
        try:
            server_digit = self._tick_last_digit(latest_tick)
        except Exception:
            server_digit = None

        snapshot["canonical_tick"] = {
            "epoch": server_epoch,
            "digit": server_digit,
            "quote": latest_tick.get("quote"),
            "pip_size": latest_tick.get("pip_size"),
            "symbol": latest_tick.get("symbol"),
        }

        # V1 and Trigger Fusion shadow are produced by the same rank() call,
        # therefore they intentionally share the same rank epoch.
        snapshot["rank_epoch"] = rank_epoch
        snapshot["shadow_epoch"] = rank_epoch

        shadow = snapshot.get("shadow")
        if isinstance(shadow, dict):
            shadow["rank_epoch"] = rank_epoch

        selected_digit = snapshot.get("selected_digit")
        live_next = (getattr(self, "live_next_target", {}) or {}).get(sid)

        try:
            same_target = (
                selected_digit is not None
                and live_next is not None
                and int(selected_digit) == int(live_next)
            )
        except Exception:
            same_target = False

        # NEXT target belongs to this rank epoch only when it is actually the
        # same digit as V1 #1. Otherwise we deliberately expose 0 so the UI
        # cannot falsely claim synchronization.
        target_epoch = rank_epoch if same_target and rank_epoch > 0 else 0
        snapshot["target_epoch"] = target_epoch
        snapshot["target_digit"] = int(live_next) if live_next is not None else None

        snapshot["sync_ready"] = bool(
            server_epoch > 0
            and rank_epoch > 0
            and target_epoch > 0
            and server_epoch == rank_epoch == target_epoch
        )

        # _original_score_all_digits stores this same dict object in
        # digit_score_snapshots, so the provenance is retained for diagnostics.
        return snapshot

    MultiUserEngine._score_all_digits = _score_all_digits_with_provenance
    MultiUserEngine._dms_sync_provenance_v2_installed = True
