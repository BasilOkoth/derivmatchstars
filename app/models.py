from sqlalchemy import Boolean, Column, Float, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class SessionState(Base):
    __tablename__ = "session_state"
    id = Column(Integer, primary_key=True)
    account_mode = Column(String(10), nullable=False, default="DEMO")
    symbol = Column(String(32), nullable=False, default="R_10")
    running = Column(Boolean, nullable=False, default=False)
    paused = Column(Boolean, nullable=False, default=False)
    phase = Column(String(40), nullable=False, default="IDLE")
    base_stake = Column(Float, nullable=False, default=1.0)
    multiplier = Column(Float, nullable=False, default=1.15)
    max_trades = Column(Integer, nullable=False, default=10)
    current_trade = Column(Integer, nullable=False, default=0)
    current_stake = Column(Float, nullable=False, default=1.0)
    candidate_digit = Column(Integer, nullable=True)
    open_contract_id = Column(String(80), nullable=True)
    pending_real_confirmation = Column(Boolean, nullable=False, default=False)
    pending_trade_json = Column(Text, nullable=True)
    pnl = Column(Float, nullable=False, default=0.0)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class TradeLog(Base):
    __tablename__ = "trade_log"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, default=1)
    trade_no = Column(Integer, nullable=False)
    account_mode = Column(String(10), nullable=False)
    symbol = Column(String(32), nullable=False)
    digit = Column(Integer, nullable=False)
    stake = Column(Float, nullable=False)
    contract_id = Column(String(80), nullable=True)
    status = Column(String(30), nullable=False, default="PROPOSED")
    buy_price = Column(Float, nullable=True)
    payout = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)
    proposal_sent_at = Column(DateTime, nullable=True)
    buy_sent_at = Column(DateTime, nullable=True)
    buy_confirmed_at = Column(DateTime, nullable=True)
    settled_at = Column(DateTime, nullable=True)
    raw_json = Column(Text, nullable=True)
