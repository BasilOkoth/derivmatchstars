import asyncio, json
from datetime import datetime
from .db import SessionLocal
from .models import TradingSession, DerivCredential, TradeLog
from .security import decrypt_token
from .deriv_rest import get_ws_url
from .deriv_ws import DerivWS
from .config import settings

class MultiUserEngine:
    def __init__(self):
        self.task = None
        self.clients = {}  # key=(user_id, account_id)

    async def start(self):
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_forever())

    async def _client(self, user_id: str, account_id: str):
        key = (user_id, account_id)
        c = self.clients.get(key)
        if c and c.ws and not c.ws.closed:
            return c

        db = SessionLocal()
        try:
            cred = db.query(DerivCredential).filter(DerivCredential.user_id == user_id).first()
            if not cred:
                raise RuntimeError("Deriv account not connected")
            if cred.expires_at and cred.expires_at <= datetime.utcnow():
                raise RuntimeError("Deriv OAuth access token expired; reconnect Deriv")
            token = decrypt_token(cred.encrypted_access_token)
        finally:
            db.close()

        url = await get_ws_url(token, account_id)
        c = DerivWS(url)
        await c.connect()
        self.clients[key] = c
        return c

    async def run_forever(self):
        while True:
            db = SessionLocal()
            try:
                ids = [x.id for x in db.query(TradingSession).filter(TradingSession.running == True).all()]
            finally:
                db.close()

            for sid in ids:
                try:
                    await self.step(sid)
                except Exception as e:
                    db = SessionLocal()
                    try:
                        s = db.get(TradingSession, sid)
                        if s:
                            s.last_error = str(e)
                            s.phase = "ERROR"
                            s.updated_at = datetime.utcnow()
                            db.commit()
                    finally:
                        db.close()
            await asyncio.sleep(0.5)

    async def step(self, sid: int):
        db = SessionLocal()
        try:
            s = db.get(TradingSession, sid)
            if not s or not s.running or s.paused:
                return

            c = await self._client(s.user_id, s.account_id)

            if s.open_contract_id:
                s.phase = "WAITING_SETTLEMENT"
                db.commit()
                data = await c.contract_status(s.open_contract_id)
                poc = data.get("proposal_open_contract", {})
                if poc.get("is_sold"):
                    profit = float(poc.get("profit") or 0)
                    s.pnl += profit
                    log = db.query(TradeLog).filter(
                        TradeLog.trading_session_id == s.id,
                        TradeLog.contract_id == s.open_contract_id
                    ).order_by(TradeLog.id.desc()).first()
                    if log:
                        log.status = "SETTLED"
                        log.profit = profit
                        log.settled_at = datetime.utcnow()

                    s.open_contract_id = None
                    s.phase = "SETTLED"
                    s.candidate_digit = None  # require next fresh candidate
                    s.pending_trade_json = None
                    s.pending_real_confirmation = False
                    if profit > 0:
                        s.current_trade = 0
                        s.current_stake = s.base_stake
                    else:
                        s.current_stake = round(s.current_stake * s.multiplier, 2)
                    s.updated_at = datetime.utcnow()
                    db.commit()
                return

            if s.pending_real_confirmation:
                s.phase = "WAITING_REAL_CONFIRMATION"
                db.commit()
                return

            if s.current_trade >= s.max_trades:
                s.running = False
                s.phase = "MAX_TRADES_REACHED"
                db.commit()
                return

            if s.candidate_digit is None:
                s.phase = "WAITING_CANDIDATE"
                db.commit()
                return

            proposal = await c.proposal_digitmatch(
                s.symbol, s.candidate_digit, s.current_stake, 1
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
                if not settings.allow_real_mode:
                    raise RuntimeError("REAL mode is disabled by server configuration")
                # Safety: keep real-money purchasing confirmation-based.
                s.pending_trade_json = json.dumps(trade_payload)
                s.pending_real_confirmation = True
                s.phase = "WAITING_REAL_CONFIRMATION"
                db.commit()
                return

            await self._execute_buy(db, s, c, trade_payload)
        finally:
            db.close()

    async def _execute_buy(self, db, s, c, payload):
        result = await c.buy(payload["proposal_id"], payload["ask_price"])
        buy = result["buy"]
        contract_id = str(buy["contract_id"])

        db.add(TradeLog(
            user_id=s.user_id,
            trading_session_id=s.id,
            trade_no=payload["trade_no"],
            account_mode=s.account_mode,
            account_id=s.account_id,
            symbol=s.symbol,
            digit=payload["digit"],
            stake=payload["stake"],
            contract_id=contract_id,
            status="OPEN",
            buy_price=float(buy.get("buy_price") or payload["ask_price"]),
            payout=payload["payout"],
            raw_json=json.dumps(result),
        ))
        s.open_contract_id = contract_id
        s.phase = "WAITING_SETTLEMENT"
        s.current_trade += 1
        s.pending_trade_json = None
        s.pending_real_confirmation = False
        s.updated_at = datetime.utcnow()
        db.commit()

    async def confirm_real(self, user_id: str, session_id: int):
        db = SessionLocal()
        try:
            s = db.get(TradingSession, session_id)
            if not s or s.user_id != user_id:
                raise RuntimeError("Session not found")
            if s.account_mode != "REAL":
                raise RuntimeError("Not a REAL session")
            if not s.pending_real_confirmation or not s.pending_trade_json:
                raise RuntimeError("No REAL trade awaiting confirmation")
            c = await self._client(s.user_id, s.account_id)
            payload = json.loads(s.pending_trade_json)
            await self._execute_buy(db, s, c, payload)
        finally:
            db.close()

engine = MultiUserEngine()
