"""
DigitMatchStar Rank Feed Reliability V10.

Loaded after app/__init__.py has applied the existing V5/V6/V7/V8 strategy
patches. It repairs passive DigitScore feed failures without changing the V1
ranking formula or target threshold.
"""

import asyncio
from time import monotonic

from .engine import MultiUserEngine
from .db import SessionLocal
from .models import TradingSession


if not getattr(
    MultiUserEngine,
    "_dms_rank_feed_reliability_v10",
    False,
):
    _previous_bootstrap_rank_history_v10 = (
        MultiUserEngine._bootstrap_rank_history
    )

    async def _bootstrap_rank_history_v10(
        self,
        sid: int,
        symbol: str,
        client,
    ):
        sid = int(sid)

        history = self._digit_history(sid)
        minimum = int(
            self.digit_scorer.min_history
        )

        snapshot = (
            (
                getattr(
                    self,
                    "digit_score_snapshots",
                    {},
                )
                or {}
            ).get(sid)
        )

        # Repair case:
        # history is already warm but the in-memory rank snapshot disappeared
        # after a process/reconnect transition.
        if (
            len(history) >= minimum
            and not (
                isinstance(snapshot, dict)
                and snapshot.get("ready")
                and snapshot.get("ranking")
            )
        ):
            snapshot = self._score_all_digits(
                sid
            )

            latest = (
                (
                    getattr(
                        self,
                        "latest_ticks",
                        {},
                    )
                    or {}
                ).get(sid)
                or {}
            )

            epoch = int(
                (
                    getattr(
                        self,
                        "latest_tick_epoch",
                        {},
                    )
                    or {}
                ).get(sid)
                or latest.get("epoch")
                or 0
            )

            snapshot["rank_epoch"] = (
                epoch or None
            )

            snapshot["canonical_tick"] = {
                "epoch": epoch or None,
                "digit": self._tick_last_digit(
                    latest
                ),
                "quote": latest.get("quote"),
                "pip_size": latest.get(
                    "pip_size"
                ),
                "symbol": str(symbol),
            }

            self.digit_score_snapshots[
                sid
            ] = snapshot

            if snapshot.get("ready"):
                selected = snapshot.get(
                    "selected_digit"
                )

                if selected is not None:
                    self._set_live_next_target(
                        sid,
                        int(selected),
                    )

            return snapshot

        # Rank exists but provenance was lost. Restore provenance without
        # recalculating the ranking.
        if (
            isinstance(snapshot, dict)
            and snapshot.get("ready")
            and snapshot.get("ranking")
            and not snapshot.get(
                "rank_epoch"
            )
        ):
            latest = (
                (
                    getattr(
                        self,
                        "latest_ticks",
                        {},
                    )
                    or {}
                ).get(sid)
                or {}
            )

            epoch = int(
                (
                    getattr(
                        self,
                        "latest_tick_epoch",
                        {},
                    )
                    or {}
                ).get(sid)
                or latest.get("epoch")
                or 0
            )

            if epoch:
                snapshot["rank_epoch"] = epoch
                snapshot[
                    "canonical_tick"
                ] = {
                    "epoch": epoch,
                    "digit":
                        self._tick_last_digit(
                            latest
                        ),
                    "quote":
                        latest.get("quote"),
                    "pip_size":
                        latest.get(
                            "pip_size"
                        ),
                    "symbol": str(symbol),
                }

            return snapshot

        return await (
            _previous_bootstrap_rank_history_v10(
                self,
                sid,
                symbol,
                client,
            )
        )

    async def _rank_feed_watchdog_v10(
        self,
    ):
        if not hasattr(
            self,
            "_dms_last_tick_monotonic",
        ):
            self._dms_last_tick_monotonic = {}

        if not hasattr(
            self,
            "_dms_rank_feed_first_seen",
        ):
            self._dms_rank_feed_first_seen = {}

        if not hasattr(
            self,
            "_dms_rank_feed_repairing",
        ):
            self._dms_rank_feed_repairing = set()

        async def repair(
            sid,
            user_id,
            account_id,
            symbol,
            *,
            force=False,
        ):
            sid = int(sid)

            if sid in (
                self._dms_rank_feed_repairing
            ):
                return

            self._dms_rank_feed_repairing.add(
                sid
            )

            try:
                await self._ensure_rank_feed(
                    sid,
                    user_id,
                    account_id,
                    symbol,
                    force=force,
                )
            finally:
                self._dms_rank_feed_repairing.discard(
                    sid
                )

        while True:
            try:
                db = SessionLocal()

                try:
                    rows = (
                        db.query(
                            TradingSession
                        )
                        .all()
                    )

                    sessions = [
                        (
                            int(row.id),
                            str(row.user_id),
                            str(row.account_id),
                            str(row.symbol),
                        )
                        for row in rows
                    ]
                finally:
                    db.close()

                now = monotonic()

                for (
                    sid,
                    user_id,
                    account_id,
                    symbol,
                ) in sessions:

                    existing = (
                        (
                            getattr(
                                self,
                                "tick_subscriptions",
                                {},
                            )
                            or {}
                        ).get(sid)
                    )

                    last_seen = (
                        (
                            getattr(
                                self,
                                "_dms_last_tick_monotonic",
                                {},
                            )
                            or {}
                        ).get(sid)
                    )

                    snapshot = (
                        (
                            getattr(
                                self,
                                "digit_score_snapshots",
                                {},
                            )
                            or {}
                        ).get(sid)
                    )

                    history_count = len(
                        self._digit_history(
                            sid
                        )
                    )

                    symbol_changed = bool(
                        existing
                        and str(
                            existing.get(
                                "symbol"
                            )
                        )
                        != str(symbol)
                    )

                    missing = (
                        not existing
                        or symbol_changed
                    )

                    stale = bool(
                        existing
                        and last_seen
                            is not None
                        and (
                            now
                            - last_seen
                        ) > 12.0
                    )

                    # Old watchdog bug:
                    # an existing subscription with ZERO received ticks had
                    # last_seen=None forever, so it was never considered stale.
                    never_started = False

                    if (
                        existing
                        and last_seen
                            is None
                    ):
                        first_seen = (
                            self
                            ._dms_rank_feed_first_seen
                            .setdefault(
                                sid,
                                now,
                            )
                        )

                        never_started = (
                            now
                            - first_seen
                        ) > 8.0

                    else:
                        self._dms_rank_feed_first_seen.pop(
                            sid,
                            None,
                        )

                    warm_without_rank = bool(
                        history_count
                        >= int(
                            self.digit_scorer
                            .min_history
                        )
                        and not (
                            isinstance(
                                snapshot,
                                dict,
                            )
                            and snapshot.get(
                                "ready"
                            )
                            and snapshot.get(
                                "ranking"
                            )
                        )
                    )

                    if (
                        missing
                        or stale
                        or never_started
                        or warm_without_rank
                    ):
                        asyncio.create_task(
                            repair(
                                sid,
                                user_id,
                                account_id,
                                symbol,
                                force=bool(
                                    stale
                                    or never_started
                                    or symbol_changed
                                ),
                            )
                        )

            except asyncio.CancelledError:
                raise

            except Exception:
                # Keep watchdog alive. Existing server status surfaces
                # authentication/OTP errors separately.
                pass

            await asyncio.sleep(2.0)

    MultiUserEngine._bootstrap_rank_history = (
        _bootstrap_rank_history_v10
    )

    MultiUserEngine._rank_feed_watchdog = (
        _rank_feed_watchdog_v10
    )

    MultiUserEngine._dms_rank_feed_reliability_v10 = (
        True
    )
