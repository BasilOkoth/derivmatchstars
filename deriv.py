import asyncio, json, websockets, time
from typing import Optional

class DerivClient:
    def __init__(self, app_id: str, token: str):
        self.app_id = app_id
        self.token = token
        self.ws = None
        self.req_id = 0
        self.pending = {}
        self.reader_task = None
        self.authorized = False

    async def connect(self):
        if self.ws and not self.ws.closed:
            return
        self.ws = await websockets.connect(
            f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}",
            ping_interval=20, ping_timeout=20, close_timeout=5
        )
        self.reader_task = asyncio.create_task(self._reader())
        await self.request({"authorize": self.token})
        self.authorized = True

    async def _reader(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                rid = data.get("req_id")
                if rid in self.pending:
                    fut = self.pending.pop(rid)
                    if not fut.done():
                        fut.set_result(data)
        except Exception as e:
            for fut in list(self.pending.values()):
                if not fut.done():
                    fut.set_exception(e)
            self.pending.clear()
            self.authorized = False

    async def request(self, payload: dict, timeout: float = 15):
        await self.connect_if_needed()
        self.req_id += 1
        rid = self.req_id
        payload = dict(payload)
        payload["req_id"] = rid
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending[rid] = fut
        await self.ws.send(json.dumps(payload))
        data = await asyncio.wait_for(fut, timeout)
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Deriv API error"))
        return data

    async def connect_if_needed(self):
        if not self.ws or self.ws.closed:
            self.ws = await websockets.connect(
                f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}",
                ping_interval=20, ping_timeout=20, close_timeout=5
            )
            self.reader_task = asyncio.create_task(self._reader())
            if self.token:
                self.req_id += 1
                rid = self.req_id
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                self.pending[rid] = fut
                await self.ws.send(json.dumps({"authorize": self.token, "req_id": rid}))
                data = await asyncio.wait_for(fut, 15)
                if "error" in data:
                    raise RuntimeError(data["error"].get("message", "Authorization failed"))
                self.authorized = True

    async def proposal_digitmatch(self, symbol: str, digit: int, amount: float, duration: int = 1):
        return await self.request({
            "proposal": 1,
            "amount": round(float(amount), 2),
            "basis": "stake",
            "contract_type": "DIGITMATCH",
            "currency": "USD",
            "duration": duration,
            "duration_unit": "t",
            "barrier": str(int(digit)),
            "symbol": symbol,
        })

    async def buy(self, proposal_id: str, price: float):
        return await self.request({"buy": proposal_id, "price": float(price)})

    async def contract_status(self, contract_id: str):
        return await self.request({"proposal_open_contract": 1, "contract_id": contract_id})
