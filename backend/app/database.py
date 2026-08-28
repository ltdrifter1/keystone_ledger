from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# Ensure SQLite directory exists
if settings.database_url.startswith("sqlite"):
    db_path = settings.database_url.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    """Add newly introduced columns on existing SQLite files."""
    if not settings.database_url.startswith("sqlite"):
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(bank_accounts)")).fetchall()}
        if "budget_balance" not in cols:
            conn.execute(text("ALTER TABLE bank_accounts ADD COLUMN budget_balance NUMERIC(18, 2)"))

        wp_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(working_paper_documents)")).fetchall()
        }
        if wp_cols and "entity_id" not in wp_cols:
            conn.execute(text("ALTER TABLE working_paper_documents ADD COLUMN entity_id INTEGER"))
            conn.execute(
                text(
                    "UPDATE working_paper_documents SET entity_id = "
                    "(SELECT id FROM dim_entity WHERE code = 'CAN' LIMIT 1) "
                    "WHERE entity_id IS NULL"
                )
            )
        _rebuild_wp_docs_entity_unique(conn)

        rule_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(categorization_rules)")).fetchall()
        }
        ent_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(dim_entity)")).fetchall()}
        if ent_cols and "fiscal_year_end_month" not in ent_cols:
            conn.execute(text("ALTER TABLE dim_entity ADD COLUMN fiscal_year_end_month INTEGER DEFAULT 7"))
            conn.execute(text("UPDATE dim_entity SET fiscal_year_end_month = 7 WHERE fiscal_year_end_month IS NULL"))

        if rule_cols and "rule_kind" not in rule_cols:
            conn.execute(
                text("ALTER TABLE categorization_rules ADD COLUMN rule_kind VARCHAR(32) DEFAULT 'gl'")
            )
            conn.execute(
                text(
                    "UPDATE categorization_rules SET rule_kind = 'bank_transfer' "
                    "WHERE lower(name) LIKE 'transfer:%'"
                )
            )
            conn.execute(
                text(
                    "UPDATE categorization_rules SET rule_kind = 'intercompany' "
                    "WHERE lower(name) LIKE 'intercompany:%'"
                )
            )


def _rebuild_wp_docs_entity_unique(conn) -> None:
    """SQLite table UNIQUE(year, month, key) cannot be dropped — rebuild to include entity_id."""
    from sqlalchemy import text

    indexes = list(conn.execute(text("PRAGMA index_list(working_paper_documents)")).fetchall())
    if not indexes:
        return
    needs_rebuild = False
    for idx in indexes:
        unique = idx[2]
        name = idx[1]
        if not unique:
            continue
        cols = [r[2] for r in conn.execute(text(f'PRAGMA index_info("{name}")')).fetchall()]
        if cols == ["period_year", "period_month", "template_key"]:
            needs_rebuild = True
            break
    if not needs_rebuild:
        return
    conn.execute(
        text(
            "UPDATE working_paper_documents SET entity_id = "
            "(SELECT id FROM dim_entity WHERE code = 'CAN' LIMIT 1) "
            "WHERE entity_id IS NULL"
        )
    )
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(
        text(
            """
            CREATE TABLE working_paper_documents_v2 (
                id INTEGER NOT NULL PRIMARY KEY,
                period_year INTEGER NOT NULL,
                period_month INTEGER NOT NULL,
                template_key VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                checked_json TEXT,
                notes TEXT,
                preparer VARCHAR(64),
                preparer_at DATETIME,
                reviewer VARCHAR(64),
                reviewer_at DATETIME,
                updated_at DATETIME NOT NULL,
                updated_by VARCHAR(64) NOT NULL,
                entity_id INTEGER,
                CONSTRAINT uq_wp_doc_period_key_entity
                    UNIQUE (period_year, period_month, template_key, entity_id)
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO working_paper_documents_v2 (
                id, period_year, period_month, template_key, status, checked_json, notes,
                preparer, preparer_at, reviewer, reviewer_at, updated_at, updated_by, entity_id
            )
            SELECT id, period_year, period_month, template_key, status, checked_json, notes,
                   preparer, preparer_at, reviewer, reviewer_at, updated_at, updated_by, entity_id
            FROM working_paper_documents
            """
        )
    )
    conn.execute(text("DROP TABLE working_paper_documents"))
    conn.execute(text("ALTER TABLE working_paper_documents_v2 RENAME TO working_paper_documents"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_working_paper_documents_template_key ON working_paper_documents (template_key)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_working_paper_documents_status ON working_paper_documents (status)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_working_paper_documents_period_month ON working_paper_documents (period_month)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_working_paper_documents_period_year ON working_paper_documents (period_year)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_working_paper_documents_entity_id ON working_paper_documents (entity_id)"))
    conn.execute(text("PRAGMA foreign_keys=ON"))
