# tests/test_research_phase3.py
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import research_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(research_db, "DB_PATH", db_file)
    research_db.init_db()
    return db_file


def test_qa_messages_table_exists(db):
    with research_db.get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='qa_messages'"
        ).fetchone()
    assert row is not None


def test_theses_has_auto_generated_column(db):
    with research_db.get_conn() as conn:
        info = conn.execute("PRAGMA table_info(theses)").fetchall()
    cols = [r["name"] for r in info]
    assert "auto_generated" in cols
    assert "trigger_type" in cols
    assert "trigger_id" in cols


def test_filings_has_update_thesis_column(db):
    with research_db.get_conn() as conn:
        info = conn.execute("PRAGMA table_info(filings)").fetchall()
    cols = [r["name"] for r in info]
    assert "update_thesis" in cols
    assert "update_reason" in cols


def test_news_items_has_update_thesis_column(db):
    with research_db.get_conn() as conn:
        info = conn.execute("PRAGMA table_info(news_items)").fetchall()
    cols = [r["name"] for r in info]
    assert "update_thesis" in cols
    assert "update_reason" in cols
