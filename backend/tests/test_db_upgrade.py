"""An app.db created before the past-paper bank existed is upgraded in place, keeping its data."""
from sqlalchemy import create_engine, inspect

from app import models  # noqa: F401 — registers tables on Base.metadata
from app.db import Base, upgrade_sqlite_schema

OLD_SCHEMA = [
    """CREATE TABLE patterns (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, subject VARCHAR(100) NOT NULL,
       grade VARCHAR(50) NOT NULL, config_json JSON NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)""",
    """CREATE TABLE question_sets (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL,
       pattern_id INTEGER NOT NULL REFERENCES patterns(id), subject VARCHAR(100) NOT NULL, grade VARCHAR(50) NOT NULL,
       status VARCHAR(20) NOT NULL, error_message TEXT NOT NULL, generated_at DATETIME NOT NULL)""",
    """CREATE TABLE questions (id INTEGER PRIMARY KEY, question_set_id INTEGER NOT NULL REFERENCES question_sets(id),
       section VARCHAR(20) NOT NULL, order_index INTEGER NOT NULL, question_type VARCHAR(30) NOT NULL, text TEXT NOT NULL,
       options JSON, marks FLOAT NOT NULL, difficulty VARCHAR(20) NOT NULL, expected_answer TEXT NOT NULL,
       rubric TEXT NOT NULL)""",
    "INSERT INTO patterns VALUES (1, 'P', '', '', '{}', '2025-01-01', '2025-01-01')",
    "INSERT INTO question_sets VALUES (7, 'Old set', 1, 'Science', '10', 'ready', '', '2025-01-01')",
    "INSERT INTO questions VALUES (3, 7, 'A', 0, 'MCQ', 'Q?', NULL, 1, 'easy', 'ans', 'rub')",
]


def test_old_database_is_upgraded_in_place(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        for stmt in OLD_SCHEMA:
            conn.exec_driver_sql(stmt)

    Base.metadata.create_all(bind=engine)
    upgrade_sqlite_schema(engine)
    upgrade_sqlite_schema(engine)  # idempotent

    insp = inspect(engine)
    qs_cols = {c["name"]: c for c in insp.get_columns("question_sets")}
    assert qs_cols["pattern_id"]["nullable"] is True
    assert "source" in qs_cols
    assert "bank_question_id" in {c["name"] for c in insp.get_columns("questions")}
    assert {"past_papers", "bank_questions"} <= set(insp.get_table_names())

    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT name, source, pattern_id FROM question_sets").all() == [("Old set", "ai", 1)]
        assert conn.exec_driver_sql("SELECT question_set_id, bank_question_id FROM questions").all() == [(7, None)]
        conn.exec_driver_sql(
            "INSERT INTO question_sets (name, pattern_id, source, subject, grade, status, error_message, generated_at) "
            "VALUES ('Bank set', NULL, 'bank', '', '', 'ready', '', '2025-01-02')"
        )
