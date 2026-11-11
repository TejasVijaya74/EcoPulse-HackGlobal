from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SimulationRecord(Base):
    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    scenario: Mapped[str] = mapped_column(String(40))
    parameters_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)


class ConfigurationRecord(Base):
    __tablename__ = "configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    values_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    simulation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    household_id: Mapped[str] = mapped_column(String(40), index=True)
    energy_kwh: Mapped[float] = mapped_column(Float)
    credits: Mapped[float] = mapped_column(Float)
    transaction_type: Mapped[str] = mapped_column(String(40))


class CommunityBankResetRecord(Base):
    __tablename__ = "community_bank_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    through_simulation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelTrainingRecord(Base):
    __tablename__ = "model_training"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    metrics_json: Mapped[str] = mapped_column(Text)
    samples: Mapped[int] = mapped_column(Integer)
