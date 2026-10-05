import asyncio, json
from datetime import datetime
from .db import SessionLocal
from .models import SessionState, TradeLog
from .config import settings
from .deriv import DerivClient

class TradingEngine:
    """
    DEMO: may auto-execute while the dashboard is closed.
    REAL: can run server-side, but each purchase must be explicitly confirmed
          through /real/confirm before the worker sends a buy request.
    """
    def __init__(self):
        self.task = None
        self.clients = {}

    def _token_for_mode(self, mode: str):
        if mode == "DEMO":
            return settings.deriv_demo_token
        if mode == "REAL":
            if not settings.allow_real_mode:
                raise RuntimeError("REAL mode disabled. Set ALLOW_REAL_MODE=true deliberately.")
            return settings.deriv_real_token
        raise RuntimeError("Unknown account mode")

    async def _client(self, mode: str):
        if mode not in self.clients:
            token = self._token_for_mode(mode)
            if not token:
                raise RuntimeError(f"Missing token for {mode}")
            c = DerivClient(settings.deriv_app_id, token)
            await c.connect_if_needed()
            self.clients[mode] = c
        return self.clients[mode]

    def ensure_session(self):
        db = SessionLocal()
        try:
            s = db.get(SessionState, 1)
            if not s:
                s = SessionState(id=1)
                db.add(s)
                db.commit()
                db.refresh(s)
            return s
        finally:
            db.close()

    async def start(self):
        self.ensure_session()
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_forever())

    async def reconcile_open_contract(self):
        db = SessionLocal()
        try:
            s = db.get(SessionState, 1)
            if not s or not s.open_contract_id:
                return
            c = await self._client(s.account_mode)
            data = await c.contract_status(s.open_contract_id)
            poc = data.get("proposal_open_contract", {})
            if poc.get("is_sold"):
                profit = float(poc.get("profit") or 0)
                s.pnl += profit
                s.open_contract_id = None
                s.phase = "SETTLED"
                s.pending_real_confirmation = False
                s.pending_trade_json = None
                s.current_trade = 0 if profit > 0 else s.current_trade
                s.current_stake = s.base_stake if profit > 0 else s.current_stake
                s.updated_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    async def run_forever(self):
        while True:
            try:
                await self.reconcile_open_contract()
                await self._step()
            except Exception as e:
                db = SessionLocal()
                try:
                    s = db.get(SessionState, 1)
                    if s:
                        s.last_error = str(e)
                        s.phase = "ERROR"
                        s.updated_at = datetime.utcnow()
                        db.commit()
                finally:
                    db.close()
                await asyncio.sleep(2)
            await asyncio.sleep(0.4)

    async def _step(self):
        db = SessionLocal()
        try:
            s = db.get(SessionState, 1)
            if not s or not s.running or s.paused:
                return
            if s.open_contract_id:
                s.phase = "WAITING_SETTLEMENT"
                db.commit()
                return
            if s.pending_real_confirmation:
                s.phase = "WAITING_REAL_CONFIRMATION"
                db.commit()
                return
            if s.current_trade >= s.max_trades:
                s.running = False
                s.phase = "STOP10"
                db.commit()
                return
            if s.candidate_digit is None:
                # Candidate selection stays outside this minimal execution engine.
                # The dashboard/research module can set candidate_digit.
                s.phase = "WAITING_CANDIDATE"
                db.commit()
                return

            c = await self._client(s.account_mode)
            s.phase = "PROPOSING"
            s.updated_at = datetime.utcnow()
            db.commit()

            proposal = await c.proposal_digitmatch(
                s.symbol, s.candidate_digit, s.current_stake, duration=1
            )
            p = proposal["proposal"]
            trade_payload = {
                "proposal_id": p["id"],
                "ask_price": float(p["ask_price"]),
                "payout": float(p.get("payout") or 0),
                "digit": s.candidate_digit,
                "stake": s.current_stake,
                "trade_no": s.current_trade + 1,
            }

            if s.account_mode == "REAL":
                # Server stays alive, but real-money purchase requires explicit confirmation.
                s.pending_trade_json = json.dumps(trade_payload)
                s.pending_real_confirmation = True
                s.phase = "WAITING_REAL_CONFIRMATION"
                db.commit()
                return

            await self._execute_buy(db, s, c, trade_payload)
        finally:
            db.close()

    async def _execute_buy(self, db, s, c, trade_payload):
        log = TradeLog(
            session_id=s.id,
            trade_no=trade_payload["trade_no"],
            account_mode=s.account_mode,
            symbol=s.symbol,
            digit=trade_payload["digit"],
            stake=trade_payload["stake"],
            payout=trade_payload["payout"],
            status="BUY_SENT",
            proposal_sent_at=datetime.utcnow(),
            buy_sent_at=datetime.utcnow()
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        result = await c.buy(trade_payload["proposal_id"], trade_payload["ask_price"])
        buy = result["buy"]
        contract_id = str(buy["contract_id"])
        log.contract_id = contract_id
        log.buy_price = float(buy.get("buy_price") or trade_payload["ask_price"])
        log.status = "OPEN"
        log.buy_confirmed_at = datetime.utcnow()

        s.open_contract_id = contract_id
        s.phase = "WAITING_SETTLEMENT"
        s.current_trade += 1
        s.pending_real_confirmation = False
        s.pending_trade_json = None
        s.updated_at = datetime.utcnow()
        db.commit()

    async def confirm_real_trade(self):
        db = SessionLocal()
        try:
            s = db.get(SessionState, 1)
            if not s or s.account_mode != "REAL":
                raise RuntimeError("Session is not in REAL mode")
            if not s.pending_real_confirmation or not s.pending_trade_json:
                raise RuntimeError("No pending real trade to confirm")
            c = await self._client("REAL")
            payload = json.loads(s.pending_trade_json)
            await self._execute_buy(db, s, c, payload)
        finally:
            db.close()

engine = TradingEngine()
