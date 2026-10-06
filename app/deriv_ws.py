import asyncio
import json
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

    async def connect(self):
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

    async def _dispatch_subscription(self, data: dict):
        sub = data.get("subscription") or {}
        sub_id = sub.get("id")
        if not sub_id:
            return
        for callback in list(self.subscriptions.get(str(sub_id), ())):
            try:
                await callback(data)
            except Exception:
                # One subscriber must never kill the shared reader.
                pass

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
                    await self._dispatch_subscription(data)

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

    async def proposal_digitmatch(
        self,
        symbol: str,
        digit: int,
        amount: float,
        duration: int = 1,
        currency: str = "USD",
    ):
        return await self.request(
            {
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
        #
        # Remove the pending registration because there is no id to route
        # future subscription messages by, then process this response once.
        req_id = data.get("req_id")
        if req_id is not None:
            self.pending_subscription_callbacks.pop(req_id, None)

        await callback(data)

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
            raise RuntimeError(f"Deriv returned no tick subscription id for {symbol}")
        return str(sub_id)

    async def forget(self, subscription_id: str):
        result = await self.request({"forget": str(subscription_id)})
        self.subscriptions.pop(str(subscription_id), None)
        return result
