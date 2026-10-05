import asyncio
import json

import websockets


class DerivWS:
    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.req_id = 0
        self.pending = {}
        self.reader_task = None

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
        )

        self.reader_task = asyncio.create_task(self._reader())

    async def close(self):
        if self.reader_task and not self.reader_task.done():
            self.reader_task.cancel()

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass

        self.ws = None

    async def _reader(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                req_id = data.get("req_id")

                if req_id in self.pending:
                    future = self.pending.pop(req_id)

                    if not future.done():
                        future.set_result(data)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(exc)

            self.pending.clear()

    async def request(self, payload: dict, timeout: float = 15):
        await self.connect()

        self.req_id += 1
        req_id = self.req_id

        request_payload = dict(payload)
        request_payload["req_id"] = req_id

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending[req_id] = future

        try:
            await self.ws.send(json.dumps(request_payload))
            data = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            self.pending.pop(req_id, None)
            raise RuntimeError(
                f"Deriv WebSocket request timed out after {timeout:.0f}s"
            ) from exc
        except Exception:
            self.pending.pop(req_id, None)
            raise

        if "error" in data:
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
                "symbol": symbol,
            }
        )

    async def buy(self, proposal_id: str, price: float):
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
                "contract_id": contract_id,
            }
        )
