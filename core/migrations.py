# core/migrations.py
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

def run_migrations(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem in applied:
            continue
        logger.info("Applying migration %s", path.stem)
        script = (
            "BEGIN;\n" + path.read_text() +
            f"\nINSERT INTO schema_migrations(version) VALUES ('{path.stem}');\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            logger.exception("Migration %s failed", path.stem)
            raise