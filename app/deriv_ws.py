import asyncio
import json
from collections import defaultdict
from typing import Awaitable, Callable, Optional

import websockets


MessageCallback = Callable[[dict], Awaitable[None]]


class DerivWS:
    """
    Read/sync-oriented Deriv WebSocket client.

    This version adds:
      - request/response correlation
      - subscription routing
      - tick subscriptions
      - proposal_open_contract subscriptions
      - forget/unsubscribe support
      - connection cleanup

    It intentionally does NOT implement live-money purchase execution.
    """

    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.req_id = 0
        self.pending = {}
        self.reader_task = None

        # subscription_id -> set(callbacks)
        self.subscriptions = defaultdict(set)

        # request req_id -> callback to attach when subscription ack arrives
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

        callbacks = list(self.subscriptions.get(sub_id, ()))
        for callback in callbacks:
            try:
                await callback(data)
            except Exception:
                # Subscriber failures must not kill the shared reader loop.
                pass

    async def _reader(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                req_id = data.get("req_id")

                # Resolve ordinary request/response futures first.
                if req_id in self.pending:
                    future = self.pending.pop(req_id)

                    if not future.done():
                        future.set_result(data)

                # If this is the acknowledgement for a requested subscription,
                # bind the returned subscription id to the callback.
                if req_id in self.pending_subscription_callbacks:
                    callback = self.pending_subscription_callbacks.pop(req_id)
                    sub = data.get("subscription") or {}
                    sub_id = sub.get("id")

                    if sub_id:
                        self.subscriptions[sub_id].add(callback)

                # Route all subsequent subscription messages.
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
        """
        Read-only proposal quote for DIGITMATCH.
        """
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

    async def buy(self, proposal_id: str, price: float):
        raise RuntimeError(
            "Live purchase execution is intentionally disabled in this sync client."
        )

    async def contract_status(self, contract_id: str):
        """
        One-off authoritative contract status request.
        """
        return await self.request(
            {
                "proposal_open_contract": 1,
                "contract_id": contract_id,
            }
        )

    async def subscribe_contract(
        self,
        contract_id: str,
        callback: MessageCallback,
    ) -> str:
        """
        Subscribe to authoritative updates for one contract.

        Returns the Deriv subscription id.
        """
        data = await self.request(
            {
                "proposal_open_contract": 1,
                "contract_id": str(contract_id),
                "subscribe": 1,
            },
            subscription_callback=callback,
        )

        sub = data.get("subscription") or {}
        sub_id = sub.get("id")

        if not sub_id:
            raise RuntimeError(
                "Deriv did not return a subscription id for contract updates"
            )

        return str(sub_id)

    async def subscribe_ticks(
        self,
        symbol: str,
        callback: MessageCallback,
    ) -> str:
        """
        Subscribe to public ticks for diagnostics/research/display.

        Public ticks should not be treated as authoritative paid-contract
        settlement unless independently reconciled to the contract's own data.
        """
        data = await self.request(
            {
                "ticks": str(symbol),
                "subscribe": 1,
            },
            subscription_callback=callback,
        )

        sub = data.get("subscription") or {}
        sub_id = sub.get("id")

        if not sub_id:
            raise RuntimeError(
                f"Deriv did not return a subscription id for {symbol} ticks"
            )

        return str(sub_id)

    async def forget(self, subscription_id: str):
        """
        Stop one Deriv subscription and remove local callbacks.
        """
        result = await self.request(
            {
                "forget": str(subscription_id),
            }
        )

        self.subscriptions.pop(str(subscription_id), None)
        return result

    async def forget_all(self, stream_type: str):
        """
        Forget all subscriptions of a Deriv stream type, e.g.
        'ticks' or 'proposal_open_contract'.
        """
        result = await self.request(
            {
                "forget_all": str(stream_type),
            }
        )

        # Deriv forget_all does not provide enough local detail to selectively
        # prune by type, so clear the local routing table.
        self.subscriptions.clear()
        return result
