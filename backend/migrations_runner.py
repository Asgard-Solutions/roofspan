import os
import logging

from alembic.config import Config
from alembic import command

logger = logging.getLogger("roofspan")


def run_migrations() -> None:
    """Bring the database schema to the latest Alembic revision.

    This is the single, authoritative schema path used at startup. It creates a fresh
    database from the full migration history and applies forward migrations non-destructively
    to an existing database. It fails loudly if a migration cannot be applied.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations applied (head)")
