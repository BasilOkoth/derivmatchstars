from datetime import datetime

from .engine import MultiUserEngine
from .models import TradingSession


if not getattr(MultiUserEngine, "_dms_invalid_proposal_retry_v9", False):

    _previous_execute_demo_buy_v9 = MultiUserEngine._execute_demo_buy
    _MAX_EXPLICIT_INVALID_RETRIES_V9 = 3

    @staticmethod
    def _is_explicit_invalid_proposal_v9(exc):
        text = str(exc or "").lower()
        return (
            "invalidcontractproposal" in text
            or "unknown contract proposal" in text
        )

    async def _execute_demo_buy_invalid_retry_v9(
        self,
        db,
        s,
        client,
        payload,
        *,
        prearmed: bool,
    ):
        try:
            return await _previous_execute_demo_buy_v9(
                self,
                db,
                s,
                client,
                payload,
                prearmed=prearmed,
            )

        except RuntimeError as first_exc:
            if (
                not self._is_explicit_invalid_proposal_v9(first_exc)
                or str(getattr(s, "account_mode", "")).upper() != "DEMO"
            ):
                raise

            last_exc = first_exc
            sid = int(s.id)
            base_payload = dict(payload)

            for attempt in range(
                1,
                _MAX_EXPLICIT_INVALID_RETRIES_V9 + 1,
            ):
                row = (
                    db.query(TradingSession)
                    .filter(TradingSession.id == sid)
                    .with_for_update()
                    .one_or_none()
                )

                if not row:
                    raise last_exc

                if row.open_contract_id:
                    raise last_exc

                expected_trade_no = int(row.current_trade or 0) + 1
                wanted_trade_no = int(
                    base_payload.get("trade_no") or 0
                )

                if expected_trade_no != wanted_trade_no:
                    raise last_exc

                if row.candidate_digit is None:
                    raise last_exc

                wanted_digit = int(base_payload.get("digit"))
                if int(row.candidate_digit) != wanted_digit:
                    raise last_exc

                wanted_stake = float(
                    base_payload.get("stake") or 0
                )

                if abs(
                    float(row.current_stake or 0) - wanted_stake
                ) > 0.005:
                    raise last_exc

                # Explicit InvalidContractProposal means Deriv rejected the
                # proposal ID and no contract was created for that request.
                row.pending_trade_json = None
                row.running = True
                row.paused = False
                row.phase = (
                    f"REFRESHING_INVALID_PROPOSAL_V9_{attempt}"
                )
                row.last_error = None
                row.updated_at = datetime.utcnow()
                db.commit()

                fresh_client = await self._client(
                    row.user_id,
                    row.account_id,
                )

                currency = str(
                    base_payload.get("currency")
                    or await self._currency_for(db, row)
                )

                fresh_payload = (
                    await self._request_proposal_payload(
                        fresh_client,
                        symbol=str(row.symbol),
                        digit=wanted_digit,
                        stake=wanted_stake,
                        trade_no=wanted_trade_no,
                        currency=currency,
                    )
                )

                fresh_payload[
                    "_invalid_proposal_retry_count"
                ] = (
                    int(
                        base_payload.get(
                            "_invalid_proposal_retry_count",
                            0,
                        )
                        or 0
                    )
                    + attempt
                )

                fresh_payload["proposal_recovery_v9"] = True
                fresh_payload["replaces_proposal_id"] = (
                    base_payload.get("proposal_id")
                )

                row = db.get(TradingSession, sid)

                if row:
                    row.phase = (
                        f"RETRYING_FRESH_PROPOSAL_V9_{attempt}"
                    )
                    row.last_error = None
                    row.updated_at = datetime.utcnow()
                    db.commit()

                try:
                    return await _previous_execute_demo_buy_v9(
                        self,
                        db,
                        row,
                        fresh_client,
                        fresh_payload,
                        prearmed=False,
                    )

                except RuntimeError as exc:
                    if not self._is_explicit_invalid_proposal_v9(
                        exc
                    ):
                        raise

                    last_exc = exc
                    base_payload = fresh_payload

            raise last_exc

    MultiUserEngine._is_explicit_invalid_proposal_v9 = (
        _is_explicit_invalid_proposal_v9
    )
    MultiUserEngine._execute_demo_buy = (
        _execute_demo_buy_invalid_retry_v9
    )
    MultiUserEngine._dms_invalid_proposal_retry_v9 = True
