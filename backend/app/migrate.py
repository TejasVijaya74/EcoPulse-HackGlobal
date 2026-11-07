"""Run the application's additive database migrations before serving traffic."""

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.database import Base, engine
from app.models import ConfigurationRecord, CreditTransaction, ModelTrainingRecord, SimulationRecord  # noqa: F401

logger = logging.getLogger(__name__)
MIGRATION_FILE = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20261105_01_expand_credit_transaction_type.sql"
POSTGRES_MIGRATION_LOCK_ID = 2026110501


def apply_migrations(connection: Connection) -> None:
    """Create missing tables and apply serialized, idempotent PostgreSQL migrations."""
    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        # A transaction-scoped lock serializes startup/deploys across all service instances.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": POSTGRES_MIGRATION_LOCK_ID},
        )
    elif dialect_name != "sqlite":
        raise RuntimeError(f"Database migrations are not supported for {dialect_name!r}.")

    # create_all only creates missing tables; the SQL migration below alters existing schemas.
    Base.metadata.create_all(bind=connection)

    if dialect_name == "postgresql":
        migration_sql = MIGRATION_FILE.read_text(encoding="utf-8")
        connection.exec_driver_sql(migration_sql)


def run_migrations(target_engine: Engine = engine) -> None:
    """Run startup schema work in one transaction; exceptions fail the deployment start."""
    with target_engine.begin() as connection:
        apply_migrations(connection)
    logger.info("Database schema bootstrap and migrations completed.")


if __name__ == "__main__":
    run_migrations()
