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


def test_save_and_get_qa_messages_by_ticker(db):
    research_db.upsert_company("PRIO3", name="PetroRio", user="test")
    research_db.save_qa_message("PRIO3", "user", "Qual o risco?", None, "analista")
    research_db.save_qa_message("PRIO3", "assistant", "O risco é X.", None, "claude")

    msgs = research_db.get_qa_messages(ticker="PRIO3")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[0]["ticker"] == "PRIO3"


def test_save_and_get_qa_messages_global(db):
    research_db.save_qa_message(None, "user", "Qual empresa tem maior upside?", None, "admin")
    research_db.save_qa_message(None, "assistant", "VALE3 tem...", None, "claude")

    msgs = research_db.get_qa_messages(ticker=None)
    assert len(msgs) == 2
    assert msgs[0]["ticker"] is None


def test_save_qa_message_stores_sources(db):
    research_db.upsert_company("PRIO3", name="PetroRio", user="test")
    sources = [{"type": "filing", "id": 1, "ticker": "PRIO3", "snippet": "..."}]
    research_db.save_qa_message("PRIO3", "assistant", "Resposta", sources, "claude")

    msgs = research_db.get_qa_messages(ticker="PRIO3")
    stored = json.loads(msgs[0]["sources"])
    assert stored[0]["type"] == "filing"


def test_build_rag_context_returns_thesis(db):
    research_db.upsert_company("VALE3", name="Vale", user="test")
    thesis_id = research_db.create_thesis("VALE3", "A tese da Vale é de longo prazo.", user="test")
    research_db.approve_thesis(thesis_id, user="test")

    chunks = research_db.build_rag_context("qual a tese", ticker="VALE3")
    types = [c["type"] for c in chunks]
    assert "thesis" in types


def test_build_rag_context_global_no_thesis(db):
    research_db.upsert_company("ITUB4", name="Itaú", user="test")
    research_db.create_thesis("ITUB4", "Tese do banco.", user="test")

    # Global search: no ticker, no thesis chunk expected
    chunks = research_db.build_rag_context("qual o banco", ticker=None)
    types = [c["type"] for c in chunks]
    assert "thesis" not in types


def test_create_thesis_auto_generated(db):
    research_db.upsert_company("GGBR4", name="Gerdau", user="test")
    tid = research_db.create_thesis(
        "GGBR4", "Rascunho gerado pelo Claude.",
        user="claude", auto_generated=1, trigger_type="filing", trigger_id=42
    )
    with research_db.get_conn() as conn:
        row = conn.execute("SELECT * FROM theses WHERE id=?", (tid,)).fetchone()
    assert row["auto_generated"] == 1
    assert row["trigger_type"] == "filing"
    assert row["trigger_id"] == 42


def test_create_filing_with_update_thesis(db):
    research_db.upsert_company("PRIO3", name="PetroRio", user="test")
    fid = research_db.create_filing(
        "PRIO3", "CVM", "FATO_RELEVANTE", "Produção recorde",
        update_thesis=True, update_reason="Produção +8% muda premissa de volumes"
    )
    f = research_db.get_filing(fid)
    assert f["update_thesis"] == 1
    assert "volumes" in f["update_reason"]


def test_get_filing_returns_none_for_unknown(db):
    assert research_db.get_filing(9999) is None


def test_create_news_with_update_thesis(db):
    research_db.upsert_company("VALE3", name="Vale", user="test")
    nid = research_db.create_news(
        "VALE3", "Minério sobe 15%",
        update_thesis=True, update_reason="Preço do minério impacta receita"
    )
    n = research_db.get_news_item(nid)
    assert n["update_thesis"] == 1


def test_answer_question_returns_answer_and_sources(monkeypatch):
    chunks = [
        {"type": "thesis", "id": 1, "ticker": "PRIO3",
         "snippet": "Exposição ao Brent é o risco principal",
         "text": "A tese da PRIO3 aponta exposição ao Brent como risco principal."}
    ]

    def mock_call(system, user_prompt, max_tokens=1024):
        return "O principal risco é a exposição ao Brent. [Tese #1: Exposição ao Brent]"

    import research_claude
    monkeypatch.setattr(research_claude, "_call", mock_call)

    result = research_claude.answer_question("Qual o risco?", "PRIO3", chunks)
    assert result is not None
    assert "Brent" in result["answer"]
    assert isinstance(result["sources"], list)
    assert result["sources"][0]["type"] == "thesis"


def test_answer_question_returns_none_on_error(monkeypatch):
    import research_claude
    monkeypatch.setattr(research_claude, "_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail")))

    result = research_claude.answer_question("Pergunta", "PRIO3", [])
    assert result is None


def test_suggest_thesis_update_returns_string(monkeypatch):
    def mock_call(system, user_prompt, max_tokens=2048):
        return "Nova tese atualizada: a empresa aumentou produção [ATUALIZADO]. Mantemos visão positiva."

    import research_claude
    monkeypatch.setattr(research_claude, "_call", mock_call)

    result = research_claude.suggest_thesis_update(
        "Tese atual: visão positiva de longo prazo.",
        "Produção cresceu 8% QoQ no ITR Q4/25.",
        "filing"
    )
    assert result is not None
    assert "[ATUALIZADO]" in result


def test_suggest_thesis_update_handles_empty_thesis(monkeypatch):
    import research_claude
    monkeypatch.setattr(research_claude, "_call", lambda *a, **k: "Tese iniciada com base no evento.")

    result = research_claude.suggest_thesis_update("", "Produção recorde.", "filing")
    assert result is not None
    assert len(result) > 0
