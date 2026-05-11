"""Database models for trading signals and orders."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Signal(Base):
    """Trading signal model."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(String(64), unique=True, nullable=False, index=True)
    agent_type = Column(String(32), nullable=False)  # forex, options, crypto
    instrument = Column(String(32), nullable=False, index=True)
    signal = Column(String(32), nullable=False)  # BUY, SELL, HOLD, etc.
    indicators = Column(JSON, nullable=True)
    chain_data = Column(JSON, nullable=True)
    receipt = Column(String(256), nullable=True)
    status = Column(String(16), nullable=False)  # PENDING, APPROVED, REJECTED
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "signal_id": self.signal_id,
            "agent_type": self.agent_type,
            "instrument": self.instrument,
            "signal": self.signal,
            "indicators": self.indicators or {},
            "chain_data": self.chain_data,
            "receipt": self.receipt,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": (self.expires_at.isoformat() if self.expires_at else None),
            "approved_at": (self.approved_at.isoformat() if self.approved_at else None),
        }


class Order(Base):
    """Trading order model."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False, index=True)
    signal_id = Column(String(64), nullable=True, index=True)
    instrument = Column(String(32), nullable=False, index=True)
    side = Column(String(32), nullable=False)  # BUY, SELL, HOLD, CALL_BUY, PUT_SELL
    qty = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    filled_qty = Column(Float, nullable=False, default=0.0)
    filled_price = Column(Float, nullable=False, default=0.0)
    commission = Column(Float, nullable=False, default=0.0)
    instrument_spec = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, index=True)  # OPEN, CLOSED, PENDING
    exit_price = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=True)
    approved_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    executed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    closed_at = Column(DateTime(timezone=True), nullable=True, index=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "order_id": self.order_id,
            "signal_id": self.signal_id,
            "instrument": self.instrument,
            "side": self.side,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "filled_qty": self.filled_qty,
            "filled_price": self.filled_price,
            "commission": self.commission,
            "instrument_spec": self.instrument_spec,
            "status": self.status,
            "exit_price": self.exit_price,
            "realized_pnl": self.realized_pnl,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class DatabaseManager:
    """Manages database connection and session factory."""

    def __init__(self, database_url: str = "sqlite:///./trading.db") -> None:
        self.database_url = database_url
        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
            echo=False,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def init_db(self) -> None:
        """Create all tables."""
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def close(self) -> None:
        """Close the database connection."""
        self.engine.dispose()
