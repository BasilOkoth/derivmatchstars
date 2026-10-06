import asyncio
import json
import time
from collections import defaultdict
from typing import Awaitable, Callable, Optional

import websockets


MessageCallback = Callable[[dict], Awaitable[None]]


class DerivWS:
    """
    Event-driven Deriv WebSocket client for DEMO execution + read-only subscriptions.

    Safety:
    - `buy(..., demo=True)` must be explicitly marked DEMO.
    - REAL purchase automation is not supported by this client.
    """

    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.req_id = 0
        self.pending = {}
        self.reader_task = None
        self.subscriptions = defaultdict(set)
        self.pending_subscription_callbacks = {}
        self._send_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._callback_tasks = set()

        # Proposal flow control.
        # Every proposal request on this account/socket is serialized here.
        self._proposal_lock = asyncio.Lock()
        self._last_proposal_at = 0.0

        # 350 ms was too aggressive once prefetch + fallback were both active.
        # 900 ms still allows a proposal to be prepared inside an R_10 2-second
        # tick window, while greatly reducing Deriv proposal bursts.
        self._proposal_min_interval = 0.90

        # Global cooldown shared by every proposal caller on this socket.
        self._proposal_cooldown_until = 0.0
        self._rate_limit_streak = 0

    def is_open(self) -> bool:
        if not self.ws:
            return False
        closed = getattr(self.ws, "closed", None)
        if isinstance(closed, bool):
            return not closed
        state = getattr(self.ws, "state", None)
        if state is not None:
            return str(state).upper().endswith("OPEN")
        return True

    def has_subscription(self, subscription_id: str) -> bool:
        """
        True only when this CURRENT WebSocket connection still owns the
        subscription id. close()/reconnect clears self.subscriptions, so stale
        engine-side ids are automatically detected.
        """
        if not subscription_id or not self.is_open():
            return False
        return str(subscription_id) in self.subscriptions

    async def connect(self):
        if self.is_open():
            return

        async with self._connect_lock:
            if self.is_open():
                return

            self.ws = await websockets.connect(
                self.url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                open_timeout=15,
                max_queue=None,
            )
            self.reader_task = asyncio.create_task(self._reader())

    async def close(self):
        if self.reader_task and not self.reader_task.done():
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass

        self.ws = None

        for future in list(self.pending.values()):
            if not future.done():
                future.cancel()

        self.pending.clear()
        self.pending_subscription_callbacks.clear()
        self.subscriptions.clear()

        for task in list(self._callback_tasks):
            if not task.done():
                task.cancel()
        self._callback_tasks.clear()

    async def _run_subscription_callback(self, callback, data: dict):
        try:
            await callback(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            # One subscriber must never kill the shared WebSocket reader.
            pass

    def _schedule_subscription_callback(self, callback, data: dict):
        task = asyncio.create_task(
            self._run_subscription_callback(callback, data)
        )
        self._callback_tasks.add(task)
        task.add_done_callback(self._callback_tasks.discard)

    def _dispatch_subscription(self, data: dict):
        sub = data.get("subscription") or {}
        sub_id = sub.get("id")
        if not sub_id:
            return

        # CRITICAL: never await strategy/settlement callbacks in _reader().
        # Those callbacks can immediately request the next proposal/buy, whose
        # response must be consumed by this same reader task.
        for callback in list(self.subscriptions.get(str(sub_id), ())):
            self._schedule_subscription_callback(callback, data)

    async def _reader(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                req_id = data.get("req_id")

                if req_id in self.pending:
                    future = self.pending.pop(req_id)
                    if not future.done():
                        future.set_result(data)

                if req_id in self.pending_subscription_callbacks:
                    # Deriv can answer a very short-lived contract request before
                    # assigning/returning a subscription id. Do not throw the
                    # callback away unless an id was actually returned.
                    callback = self.pending_subscription_callbacks[req_id]
                    sub = data.get("subscription") or {}
                    sub_id = sub.get("id")
                    if sub_id:
                        self.pending_subscription_callbacks.pop(req_id, None)
                        self.subscriptions[str(sub_id)].add(callback)

                if data.get("subscription"):
                    self._dispatch_subscription(data)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(exc)
            self.pending.clear()
            self.pending_subscription_callbacks.clear()

    async def request(
        self,
        payload: dict,
        timeout: float = 15,
        subscription_callback: Optional[MessageCallback] = None,
    ):
        await self.connect()

        self.req_id += 1
        req_id = self.req_id
        request_payload = dict(payload)
        request_payload["req_id"] = req_id

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending[req_id] = future

        if subscription_callback is not None:
            self.pending_subscription_callbacks[req_id] = subscription_callback

        try:
            async with self._send_lock:
                await self.ws.send(json.dumps(request_payload))
            data = await asyncio.wait_for(future, timeout)

        except asyncio.CancelledError:
            # Critical for proposal-prefetch cancellation: do not leave a dead
            # request future registered in the shared WebSocket client.
            self.pending.pop(req_id, None)
            self.pending_subscription_callbacks.pop(req_id, None)
            if not future.done():
                future.cancel()
            raise

        except asyncio.TimeoutError as exc:
            self.pending.pop(req_id, None)
            self.pending_subscription_callbacks.pop(req_id, None)
            raise RuntimeError(
                f"Deriv WebSocket request timed out after {timeout:.0f}s"
            ) from exc

        except Exception:
            self.pending.pop(req_id, None)
            self.pending_subscription_callbacks.pop(req_id, None)
            raise

        if "error" in data:
            self.pending_subscription_callbacks.pop(req_id, None)
            err = data["error"] or {}
            code = err.get("code")
            message = err.get("message") or str(err)
            if code:
                raise RuntimeError(f"{code}: {message}")
            raise RuntimeError(message)

        return data

    async def _reset_after_timeout(self):
        # Only used by idempotent/read-only requests such as proposal.
        # BUY is intentionally never auto-retried.
        try:
            await self.close()
        except Exception:
            self.ws = None
        await self.connect()

    async def proposal_digitmatch(
        self,
        symbol: str,
        digit: int,
        amount: float,
        duration: int = 1,
        currency: str = "USD",
    ):
        payload = {
            "proposal": 1,
            "amount": round(float(amount), 2),
            "basis": "stake",
            "contract_type": "DIGITMATCH",
            "currency": str(currency or "USD").upper(),
            "duration": int(duration),
            "duration_unit": "t",
            "barrier": str(int(digit)),
            "underlying_symbol": str(symbol),
        }

        # ONE proposal lane per account/socket.
        #
        # IMPORTANT:
        # This is deliberately BOUNDED. The previous build could remain inside
        # this method forever during sustained Deriv throttling, leaving the UI
        # stuck on REQUESTING_PROPOSAL.
        async with self._proposal_lock:
            timeout_retry_used = False
            max_rate_limit_attempts = 3

            for attempt in range(max_rate_limit_attempts):
                now = time.monotonic()

                spacing_wait = self._proposal_min_interval - (
                    now - self._last_proposal_at
                )
                cooldown_wait = self._proposal_cooldown_until - now
                delay = max(0.0, spacing_wait, cooldown_wait)

                if delay > 0:
                    await asyncio.sleep(delay)

                try:
                    self._last_proposal_at = time.monotonic()
                    data = await self.request(payload, timeout=5)

                    self._rate_limit_streak = 0
                    self._proposal_cooldown_until = 0.0
                    return data

                except RuntimeError as exc:
                    text = str(exc).lower()

                    if "timed out" in text and not timeout_retry_used:
                        timeout_retry_used = True
                        await self._reset_after_timeout()
                        continue

                    if "ratelimit" in text or "rate limit" in text:
                        self._rate_limit_streak = min(
                            self._rate_limit_streak + 1,
                            6,
                        )

                        # Short bounded backoff. If Deriv is still throttling
                        # after these attempts, return control to the engine so
                        # the UI shows RATE_LIMIT_BACKOFF rather than hanging.
                        backoff_table = (1.0, 2.0, 3.0)
                        backoff = backoff_table[attempt]
                        self._proposal_cooldown_until = (
                            time.monotonic() + backoff
                        )

                        if attempt >= max_rate_limit_attempts - 1:
                            raise RuntimeError(
                                "RateLimit: proposal API remains throttled "
                                "after bounded retry"
                            ) from exc

                        await asyncio.sleep(backoff)
                        continue

                    raise

            raise RuntimeError(
                "Proposal request failed after bounded retry"
            )

    async def buy(self, proposal_id: str, price: float, *, demo: bool = False):
        if not demo:
            raise RuntimeError(
                "Automated REAL-money purchase is disabled. "
                "This client only permits DEMO execution."
            )

        return await self.request(
            {
                "buy": proposal_id,
                "price": float(price),
            }
        )

    async def contract_status(self, contract_id: str):
        return await self.request(
            {
                "proposal_open_contract": 1,
                "contract_id": str(contract_id),
            }
        )

    async def subscribe_contract(
        self,
        contract_id: str,
        callback: MessageCallback,
    ) -> Optional[str]:
        data = await self.request(
            {
                "proposal_open_contract": 1,
                "contract_id": str(contract_id),
                "subscribe": 1,
            },
            subscription_callback=callback,
        )

        sub_id = (data.get("subscription") or {}).get("id")
        if sub_id:
            return str(sub_id)

        # A 1-tick contract can settle so quickly that Deriv returns the
        # proposal_open_contract payload without a subscription id. That is
        # still a valid contract response, not a fatal WebSocket error.
        req_id = data.get("req_id")
        if req_id is not None:
            self.pending_subscription_callbacks.pop(req_id, None)

        # Do not await this callback here. engine.step() can already own the
        # per-session lock, while the settlement callback also needs it.
        asyncio.create_task(callback(data))

        # None tells the engine to use the contract-status polling fallback.
        return None

    async def subscribe_ticks(self, symbol: str, callback: MessageCallback) -> str:
        data = await self.request(
            {
                "ticks": str(symbol),
                "subscribe": 1,
            },
            subscription_callback=callback,
        )

        sub_id = (data.get("subscription") or {}).get("id")
        if not sub_id:
            raise RuntimeError(
                f"Deriv returned no tick subscription id for {symbol}"
            )
        return str(sub_id)

    async def forget(self, subscription_id: str):
        result = await self.request({"forget": str(subscription_id)})
        self.subscriptions.pop(str(subscription_id), None)
        return result
