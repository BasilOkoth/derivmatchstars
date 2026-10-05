from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class OAuthPending(Base):
    __tablename__ = "oauth_pending"
    id = Column(Integer, primary_key=True)
    state = Column(String(200), unique=True, nullable=False, index=True)
    code_verifier = Column(Text, nullable=False)
    requested_mode = Column(String(10), nullable=False, default="DEMO")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class LoginTicket(Base):
    __tablename__ = "login_tickets"
    id = Column(Integer, primary_key=True)
    ticket_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(200), nullable=False, index=True)
    requested_mode = Column(String(10), nullable=False, default="DEMO")
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class DerivCredential(Base):
    __tablename__ = "deriv_credentials"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(200), unique=True, nullable=False, index=True)
    encrypted_access_token = Column(Text, nullable=False)
    token_type = Column(String(32), nullable=False, default="Bearer")
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class DerivAccount(Base):
    __tablename__ = "deriv_accounts"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(200), nullable=False, index=True)
    account_id = Column(String(120), nullable=False)
    account_type = Column(String(20), nullable=False)
    currency = Column(String(20), nullable=True)
    status = Column(String(40), nullable=True)
    balance = Column(Float, nullable=True)
    raw_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_user_deriv_account"),)

class TradingSession(Base):
    __tablename__ = "trading_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(200), nullable=False, index=True)
    account_id = Column(String(120), nullable=False)
    account_mode = Column(String(10), nullable=False)
    symbol = Column(String(40), nullable=False, default="R_10")
    running = Column(Boolean, nullable=False, default=False)
    paused = Column(Boolean, nullable=False, default=False)
    phase = Column(String(60), nullable=False, default="IDLE")
    base_stake = Column(Float, nullable=False, default=1.0)
    multiplier = Column(Float, nullable=False, default=1.15)
    max_trades = Column(Integer, nullable=False, default=10)
    current_trade = Column(Integer, nullable=False, default=0)
    current_stake = Column(Float, nullable=False, default=1.0)
    candidate_digit = Column(Integer, nullable=True)
    open_contract_id = Column(String(120), nullable=True)
    pnl = Column(Float, nullable=False, default=0.0)
    pending_real_confirmation = Column(Boolean, nullable=False, default=False)
    pending_trade_json = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_user_account_session"),)

class TradeLog(Base):
    __tablename__ = "trade_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(200), nullable=False, index=True)
    trading_session_id = Column(Integer, nullable=False)
    trade_no = Column(Integer, nullable=False)
    account_mode = Column(String(10), nullable=False)
    account_id = Column(String(120), nullable=False)
    symbol = Column(String(40), nullable=False)
    digit = Column(Integer, nullable=False)
    stake = Column(Float, nullable=False)
    contract_id = Column(String(120), nullable=True)
    status = Column(String(30), nullable=False, default="PROPOSED")
    buy_price = Column(Float, nullable=True)
    payout = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)
    raw_json = Column(Text, nullable=True)
