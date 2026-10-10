from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.resolved_database_url.startswith("sqlite") else {}
engine = create_engine(settings.resolved_database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models so they're registered on Base.metadata before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        upgrade_sqlite_schema(engine)


def upgrade_sqlite_schema(target_engine) -> None:
    """Bring a database created by an older version of the app up to date, keeping its data.

    create_all() only creates missing tables, so this adds missing (nullable/defaulted) columns,
    and rebuilds question_sets once to drop the old NOT NULL on pattern_id — SQLite can't
    ALTER a column's nullability in place.
    """
    with target_engine.begin() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(dialect=conn.dialect)}'
                if col.default is not None and col.default.is_scalar:
                    ddl += f" DEFAULT {_sql_literal(col.default.arg)}"
                conn.exec_driver_sql(ddl)

        pattern_col = next(c for c in inspect(conn).get_columns("question_sets") if c["name"] == "pattern_id")
        if not pattern_col["nullable"]:
            table = Base.metadata.tables["question_sets"]
            cols = ", ".join(f'"{c.name}"' for c in table.columns)
            scratch = MetaData()
            Base.metadata.tables["patterns"].to_metadata(scratch)  # so the copy's foreign key resolves
            table.to_metadata(scratch, name="question_sets__new").create(conn)
            conn.exec_driver_sql(f'INSERT INTO question_sets__new ({cols}) SELECT {cols} FROM question_sets')
            conn.exec_driver_sql("DROP TABLE question_sets")
            conn.exec_driver_sql("ALTER TABLE question_sets__new RENAME TO question_sets")


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"
