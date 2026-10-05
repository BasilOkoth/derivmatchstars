import asyncio, json, websockets

class DerivWS:
    def __init__(self, url):
        self.url = url
        self.ws = None
        self.req_id = 0
        self.pending = {}
        self.reader_task = None

    async def connect(self):
        if self.ws and not self.ws.closed:
            return
        self.ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=20, close_timeout=5)
        self.reader_task = asyncio.create_task(self._reader())

    async def _reader(self):
        try:
            async for msg in self.ws:
                data = json.loads(msg)
                rid = data.get("req_id")
                fut = self.pending.pop(rid, None)
                if fut and not fut.done():
                    fut.set_result(data)
        except Exception as e:
            for fut in list(self.pending.values()):
                if not fut.done():
                    fut.set_exception(e)
            self.pending.clear()

    async def request(self, payload, timeout=15):
        await self.connect()
        self.req_id += 1
        rid = self.req_id
        body = dict(payload)
        body["req_id"] = rid
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending[rid] = fut
        await self.ws.send(json.dumps(body))
        data = await asyncio.wait_for(fut, timeout)
        if data.get("error"):
            raise RuntimeError(data["error"].get("message") or str(data["error"]))
        return data

    async def proposal_digitmatch(self, symbol, digit, amount, currency="USD"):
        return await self.request({
            "proposal": 1,
            "amount": round(float(amount), 2),
            "basis": "stake",
            "contract_type": "DIGITMATCH",
            "currency": currency or "USD",
            "duration": 1,
            "duration_unit": "t",
            "barrier": str(int(digit)),
            "symbol": symbol,
        })

    async def buy(self, proposal_id, price):
        return await self.request({"buy": proposal_id, "price": float(price)})

    async def contract_status(self, contract_id):
        return await self.request({"proposal_open_contract": 1, "contract_id": contract_id})
