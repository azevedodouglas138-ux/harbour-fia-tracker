# RESEARCH Fase 3 — Q&A + Sugestão Automática de Tese

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar Q&A em linguagem natural (por empresa e global) e sugestão automática de atualização de tese à aba RESEARCH do harbour-fia-tracker.

**Architecture:** Nova tabela `qa_messages` armazena histórico de Q&A single-turn com contexto RAG (FTS5 + tese ativa + valuation). Ao aprovar filing/notícia com `update_thesis=True`, Claude gera rascunho de tese automaticamente. Frontend adiciona painel lateral por empresa e item global no sidebar.

**Tech Stack:** Python 3 / Flask, SQLite 3 + FTS5, Anthropic SDK (`claude-sonnet-4-6`), vanilla JS/CSS, pytest + monkeypatch.

**Spec:** `docs/superpowers/specs/2026-04-10-research-fase3-design.md`

---

## Mapa de Arquivos

| Arquivo | O que muda |
|---------|-----------|
| `research_db.py` | + tabela `qa_messages`; + colunas `auto_generated/trigger_type/trigger_id` em `theses`; + colunas `update_thesis/update_reason` em `filings` e `news_items`; + funções `fts_search_context`, `build_rag_context`, `get_qa_messages`, `save_qa_message`, `get_filing`, `get_news_item`; atualizar `create_thesis`, `create_filing`, `create_news` |
| `research_claude.py` | + `answer_question`, + `suggest_thesis_update` |
| `research_pipeline.py` | Atualizar chamadas de `create_filing` e `create_news` para passar `update_thesis` e `update_reason` |
| `app.py` | + rotas `GET/POST /api/research/qa`; + rota `POST /api/research/theses/<id>/dismiss`; adicionar trigger de sugestão em `api_research_filing_review` e `api_research_news_review` |
| `templates/index.html` | Botão "PERGUNTAR" na header de empresa; item "✦ Q&A GLOBAL" no sidebar; div do painel lateral; div do painel global |
| `static/app.js` | Funções: `openQAPanel`, `closeQAPanel`, `loadQAHistory`, `submitQAQuestion`, `renderQAMessages`, `loadGlobalQA`, `submitGlobalQA`, `checkThesisBanner`, `renderThesisBanner`, `dismissThesisDraft` |
| `static/style.css` | Estilos: `.qa-panel`, `.qa-message`, `.qa-citation`, `.qa-global-item`, `.thesis-banner` |
| `tests/test_research_phase3.py` | Novo — testes unitários para DB + Claude (mocked) + rotas Flask |

---

## Task 1: Schema — nova tabela `qa_messages` + migração de colunas

**Files:**
- Modify: `research_db.py`
- Test: `tests/test_research_phase3.py`

- [ ] **Criar `tests/test_research_phase3.py` com fixture de DB em memória**

```python
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
```

- [ ] **Rodar o teste (fixture deve funcionar sem erros)**

```
pytest tests/test_research_phase3.py -v
```

Esperado: 0 erros de coleta, sem testes ainda.

- [ ] **Escrever testes que verificam que as novas tabelas/colunas existem após `init_db()`**

```python
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
```

- [ ] **Rodar — deve falhar (colunas não existem ainda)**

```
pytest tests/test_research_phase3.py -v
```

Esperado: 4 FAILED

- [ ] **Atualizar `SCHEMA_SQL` em `research_db.py` para incluir a nova tabela e colunas**

No final de `SCHEMA_SQL` (antes das aspas de fechamento `"""`), adicionar:

```python
CREATE TABLE IF NOT EXISTS qa_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT,
    role        TEXT CHECK(role IN ('user','assistant')) NOT NULL,
    content     TEXT NOT NULL,
    sources     TEXT,
    created_by  TEXT NOT NULL DEFAULT 'admin',
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
```

Nas definições das tabelas `theses`, `filings` e `news_items` em `SCHEMA_SQL`, adicionar as novas colunas (para fresh installs). Localizar cada `CREATE TABLE IF NOT EXISTS` e adicionar antes do `)`:

Em `theses`:
```sql
    auto_generated INTEGER DEFAULT 0,
    trigger_type   TEXT,
    trigger_id     INTEGER
```

Em `filings`:
```sql
    update_thesis  INTEGER DEFAULT 0,
    update_reason  TEXT
```

Em `news_items`:
```sql
    update_thesis  INTEGER DEFAULT 0,
    update_reason  TEXT
```

- [ ] **Adicionar função `run_migrations` e chamá-la em `init_db`**

Logo após a constante `SCHEMA_SQL`, adicionar:

```python
_MIGRATIONS = [
    "ALTER TABLE theses ADD COLUMN auto_generated INTEGER DEFAULT 0",
    "ALTER TABLE theses ADD COLUMN trigger_type TEXT",
    "ALTER TABLE theses ADD COLUMN trigger_id INTEGER",
    "ALTER TABLE filings ADD COLUMN update_thesis INTEGER DEFAULT 0",
    "ALTER TABLE filings ADD COLUMN update_reason TEXT",
    "ALTER TABLE news_items ADD COLUMN update_thesis INTEGER DEFAULT 0",
    "ALTER TABLE news_items ADD COLUMN update_reason TEXT",
]


def _run_migrations(conn):
    """Apply ALTER TABLE migrations safely — ignores 'duplicate column' errors."""
    for sql in _MIGRATIONS:
        try:
            conn.execute(sql)
        except Exception:
            pass  # column already exists (fresh install or re-run)
```

Atualizar `init_db`:

```python
def init_db():
    """Create tables if they don't exist and run migrations."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)
```

- [ ] **Rodar os testes — devem passar**

```
pytest tests/test_research_phase3.py -v
```

Esperado: 4 PASSED

- [ ] **Commit**

```bash
git add research_db.py tests/test_research_phase3.py
git commit -m "feat: schema migration para Fase 3 (qa_messages + colunas update_thesis/auto_generated)"
```

---

## Task 2: DB — funções de Q&A e RAG

**Files:**
- Modify: `research_db.py`
- Test: `tests/test_research_phase3.py`

- [ ] **Escrever os testes**

```python
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
```

- [ ] **Rodar — deve falhar**

```
pytest tests/test_research_phase3.py::test_save_and_get_qa_messages_by_ticker -v
```

Esperado: FAILED com `AttributeError: module 'research_db' has no attribute 'save_qa_message'`

- [ ] **Implementar as funções em `research_db.py`** — adicionar após a seção `# Audit log queries`:

```python
# ---------------------------------------------------------------------------
# Q&A messages
# ---------------------------------------------------------------------------

def get_qa_messages(ticker=None, limit=50):
    """Return Q&A history. ticker=None returns global messages."""
    with get_conn() as conn:
        if ticker is None:
            rows = conn.execute(
                "SELECT * FROM qa_messages WHERE ticker IS NULL "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM qa_messages WHERE ticker=? "
                "ORDER BY created_at ASC LIMIT ?",
                (ticker, limit)
            ).fetchall()
    return [dict(r) for r in rows]


def save_qa_message(ticker, role, content, sources, user):
    """Persist one Q&A message. Returns new id."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO qa_messages (ticker, role, content, sources, created_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticker, role, content,
             json.dumps(sources, ensure_ascii=False) if sources is not None else None,
             user)
        )
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# ---------------------------------------------------------------------------
# RAG context builder
# ---------------------------------------------------------------------------

def fts_search_context(query, ticker=None, limit=5):
    """FTS5 search returning full text for RAG context."""
    try:
        with get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT ticker, content_type, content_id, text, "
                    "snippet(research_fts,3,'','','…',40) AS snippet "
                    "FROM research_fts WHERE research_fts MATCH ? AND ticker=? "
                    "ORDER BY rank LIMIT ?",
                    (query, ticker, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ticker, content_type, content_id, text, "
                    "snippet(research_fts,3,'','','…',40) AS snippet "
                    "FROM research_fts WHERE research_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (query, limit)
                ).fetchall()
        return [
            {"type": r["content_type"], "id": r["content_id"],
             "ticker": r["ticker"], "snippet": r["snippet"], "text": r["text"]}
            for r in rows
        ]
    except Exception:
        return []


def build_rag_context(question, ticker=None):
    """
    Build RAG context chunks for a Q&A question.

    Returns list of dicts: {type, id, ticker, snippet, text}
    """
    chunks = []

    # 1. FTS5 full-text search
    chunks.extend(fts_search_context(question, ticker=ticker, limit=5))

    if ticker:
        # 2. Active thesis
        thesis = get_active_thesis(ticker)
        if thesis:
            chunks.append({
                "type": "thesis",
                "id": thesis["id"],
                "ticker": ticker,
                "snippet": thesis["content"][:200],
                "text": thesis["content"],
            })

        # 3. Latest valuation
        vals = get_valuations(ticker)
        if vals:
            v = vals[0]
            text = (
                f"Preço alvo: R${v.get('target_price')} | "
                f"Metodologia: {v.get('methodology')} | "
                f"Upside: {v.get('upside_pct')}%"
            )
            if v.get("notes"):
                text += f"\n{v['notes']}"
            chunks.append({
                "type": "valuation",
                "id": v["id"],
                "ticker": ticker,
                "snippet": text[:200],
                "text": text,
            })

    return chunks
```

- [ ] **Rodar todos os testes novos**

```
pytest tests/test_research_phase3.py -v
```

Esperado: todos PASSED

- [ ] **Commit**

```bash
git add research_db.py tests/test_research_phase3.py
git commit -m "feat: funções de Q&A e RAG (get_qa_messages, save_qa_message, build_rag_context)"
```

---

## Task 3: DB — atualizar `create_thesis`, `create_filing`, `create_news` e adicionar `get_filing`/`get_news_item`

**Files:**
- Modify: `research_db.py`
- Test: `tests/test_research_phase3.py`

- [ ] **Escrever os testes**

```python
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
```

- [ ] **Rodar — deve falhar**

```
pytest tests/test_research_phase3.py::test_create_thesis_auto_generated -v
```

Esperado: FAILED com `TypeError: create_thesis() got an unexpected keyword argument 'auto_generated'`

- [ ] **Atualizar `create_thesis` em `research_db.py`**

Substituir a assinatura e o INSERT:

```python
def create_thesis(ticker, content, user="admin",
                  auto_generated=0, trigger_type=None, trigger_id=None):
    """Creates a new RASCUNHO thesis. Returns new id."""
    with get_conn() as conn:
        last = conn.execute(
            "SELECT COALESCE(MAX(version),0) AS v FROM theses WHERE ticker=?", (ticker,)
        ).fetchone()["v"]
        version = last + 1
        conn.execute(
            "INSERT INTO theses (ticker, content, version, status, created_by, "
            "auto_generated, trigger_type, trigger_id) "
            "VALUES (?, ?, ?, 'RASCUNHO', ?, ?, ?, ?)",
            (ticker, content, version, user, auto_generated, trigger_type, trigger_id)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "content": content, "version": version,
               "status": "RASCUNHO", "created_by": user,
               "auto_generated": auto_generated, "trigger_type": trigger_type,
               "trigger_id": trigger_id}
        audit(conn, "thesis", new_id, ticker, "CREATE", user, None, new)
        _fts_upsert(conn, ticker, "thesis", new_id, content)
    return new_id
```

- [ ] **Atualizar `create_filing` em `research_db.py`**

```python
def create_filing(ticker, source, type_, title, filing_date=None, raw_url=None,
                  summary=None, key_points=None, sentiment=None,
                  update_thesis=False, update_reason=None, user="admin"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO filings (ticker, source, type, title, filing_date, raw_url, "
            "summary, key_points, sentiment, update_thesis, update_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, source, type_, title, filing_date, raw_url, summary,
             json.dumps(key_points, ensure_ascii=False) if key_points else None,
             sentiment, 1 if update_thesis else 0, update_reason)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "source": source, "type": type_,
               "title": title, "filing_date": filing_date, "summary": summary,
               "sentiment": sentiment, "review_status": "PENDENTE",
               "update_thesis": update_thesis, "update_reason": update_reason}
        audit(conn, "filing", new_id, ticker, "CREATE", user, None, new)
    return new_id
```

- [ ] **Adicionar `get_filing` e atualizar `create_news` e adicionar `get_news_item`**

```python
def get_filing(filing_id):
    """Return a single filing by id, or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM filings WHERE id=?", (filing_id,)).fetchone()
    return dict(row) if row else None


def get_news_item(news_id):
    """Return a single news_item by id, or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM news_items WHERE id=?", (news_id,)).fetchone()
    return dict(row) if row else None
```

Atualizar `create_news` para aceitar os novos parâmetros:

```python
def create_news(ticker, title, source=None, url=None, published_at=None,
                summary=None, sentiment=None, relevance=0, sector=None,
                update_thesis=False, update_reason=None, user="admin"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO news_items (ticker, sector, title, source, url, published_at, "
            "summary, sentiment, relevance, update_thesis, update_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, sector, title, source, url, published_at, summary, sentiment,
             relevance, 1 if update_thesis else 0, update_reason)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "title": title, "source": source,
               "review_status": "PENDENTE", "update_thesis": update_thesis}
        audit(conn, "news", new_id, ticker, "CREATE", user, None, new)
    return new_id
```

- [ ] **Rodar todos os testes**

```
pytest tests/test_research_phase3.py -v
```

Esperado: todos PASSED

- [ ] **Commit**

```bash
git add research_db.py tests/test_research_phase3.py
git commit -m "feat: create_thesis/filing/news aceitam update_thesis e auto_generated; get_filing e get_news_item"
```

---

## Task 4: Claude — `answer_question`

**Files:**
- Modify: `research_claude.py`
- Test: `tests/test_research_phase3.py`

- [ ] **Escrever o teste com Claude mockado**

```python
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
```

- [ ] **Rodar — deve falhar**

```
pytest tests/test_research_phase3.py::test_answer_question_returns_answer_and_sources -v
```

Esperado: FAILED com `AttributeError: module 'research_claude' has no attribute 'answer_question'`

- [ ] **Adicionar prompts e função em `research_claude.py`**

Adicionar após os prompts existentes (`_MANUAL_USER`):

```python
_QA_SYSTEM = """\
Você é um analista de research financeiro com acesso à base de conhecimento de um fundo de ações. \
Responda perguntas sobre empresas com base exclusivamente nas informações fornecidas, \
citando explicitamente as fontes que embasaram sua resposta."""

_QA_USER = """\
Base de conhecimento disponível:

{context}

---
Pergunta: {question}

Instruções:
- Responda em português de forma direta e objetiva
- Use apenas as informações fornecidas acima
- Ao usar uma informação, cite a fonte entre colchetes — exemplos: [Tese #3], [Filing #7: ITR Q3/25], [Nota #2]
- Se a base não contiver informação suficiente, diga explicitamente
- Não invente informações nem extrapole além do que está na base

Responda APENAS com o texto da resposta, sem prefácio."""

_THESIS_SUGGEST_SYSTEM = """\
Você é um analista de research financeiro sênior. \
Com base em um evento novo (filing ou notícia) e na tese de investimento atual, \
gere um rascunho atualizado da tese incorporando as novas informações."""

_THESIS_SUGGEST_USER = """\
TESE ATUAL:
{current_thesis}

EVENTO NOVO ({trigger_type}):
{trigger_summary}

Gere um rascunho atualizado da tese de investimento que:
- Mantenha a estrutura e o estilo da tese atual
- Incorpore as informações relevantes do evento novo
- Sinalize o que mudou com o marcador [ATUALIZADO] inline
- Seja objetivo e direto

Responda APENAS com o texto da nova tese, sem comentários adicionais."""
```

Adicionar após `process_manual`:

```python
def answer_question(question, ticker, context_chunks):
    """
    Answer a natural language question using RAG context.

    context_chunks: list of dicts with keys: type, id, ticker, snippet, text
    Returns dict {answer, sources} or None on error.
    """
    try:
        # Build context string
        parts = []
        for c in context_chunks:
            label = {"thesis": "Tese", "filing": "Filing", "news": "Notícia",
                     "note": "Nota", "valuation": "Valuation"}.get(c["type"], c["type"])
            ticker_prefix = f"[{c['ticker']}] " if c.get("ticker") else ""
            parts.append(f"[{ticker_prefix}{label} #{c['id']}]\n{c.get('text', c.get('snippet', ''))}")
        context = "\n\n---\n\n".join(parts) if parts else "Nenhuma informação encontrada na base."

        prompt = _QA_USER.format(question=question, context=context)
        answer = _call(_QA_SYSTEM, prompt, max_tokens=1024)

        sources = [
            {"type": c["type"], "id": c["id"],
             "ticker": c.get("ticker"), "snippet": c.get("snippet", "")}
            for c in context_chunks
        ]
        return {"answer": answer, "sources": sources}
    except Exception as e:
        logger.error("answer_question error [%s]: %s", ticker, e)
        return None
```

- [ ] **Rodar os testes de Claude**

```
pytest tests/test_research_phase3.py::test_answer_question_returns_answer_and_sources tests/test_research_phase3.py::test_answer_question_returns_none_on_error -v
```

Esperado: 2 PASSED

- [ ] **Commit**

```bash
git add research_claude.py tests/test_research_phase3.py
git commit -m "feat: answer_question no research_claude com RAG e citações"
```

---

## Task 5: Claude — `suggest_thesis_update`

**Files:**
- Modify: `research_claude.py`
- Test: `tests/test_research_phase3.py`

- [ ] **Escrever o teste**

```python
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
```

- [ ] **Rodar — deve falhar**

```
pytest tests/test_research_phase3.py::test_suggest_thesis_update_returns_string -v
```

Esperado: FAILED com `AttributeError`

- [ ] **Implementar `suggest_thesis_update` em `research_claude.py`** — adicionar após `answer_question`:

```python
def suggest_thesis_update(current_thesis, trigger_summary, trigger_type="filing"):
    """
    Generate a draft thesis update based on current thesis + triggering event.

    Returns str (draft thesis text) or None on error.
    """
    try:
        prompt = _THESIS_SUGGEST_USER.format(
            current_thesis=_truncate(current_thesis or "Nenhuma tese ativa.", 6000),
            trigger_type=trigger_type.upper(),
            trigger_summary=trigger_summary or "Sem resumo disponível.",
        )
        return _call(_THESIS_SUGGEST_SYSTEM, prompt, max_tokens=2048).strip()
    except Exception as e:
        logger.error("suggest_thesis_update error: %s", e)
        return None
```

- [ ] **Rodar os testes**

```
pytest tests/test_research_phase3.py -v
```

Esperado: todos PASSED

- [ ] **Commit**

```bash
git add research_claude.py tests/test_research_phase3.py
git commit -m "feat: suggest_thesis_update no research_claude"
```

---

## Task 6: Flask — rotas Q&A (`GET` e `POST /api/research/qa`)

**Files:**
- Modify: `app.py`
- Test: `tests/test_research_phase3.py`

- [ ] **Escrever os testes** — testar a lógica de orquestração da rota diretamente (sem importar o app completo para evitar conflito com `init_db()` no nível de módulo)

```python
def test_qa_route_logic_saves_messages(db, monkeypatch):
    """Testa a lógica central da rota POST /api/research/qa sem Flask."""
    import research_claude
    monkeypatch.setattr(research_claude, "_call",
                        lambda *a, **k: "Resposta mockada. [Tese #1]")

    research_db.upsert_company("PRIO3", name="PetroRio", user="test")

    # Simula o que a rota faz internamente
    question = "Qual o risco da PRIO3?"
    ticker = "PRIO3"
    context = research_db.build_rag_context(question, ticker=ticker)
    research_db.save_qa_message(ticker, "user", question, None, "admin")
    result = research_claude.answer_question(question, ticker, context)
    assert result is not None
    research_db.save_qa_message(ticker, "assistant", result["answer"], result.get("sources"), "claude")

    msgs = research_db.get_qa_messages(ticker="PRIO3")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert "Resposta mockada" in msgs[1]["content"]


def test_qa_global_saves_without_ticker(db, monkeypatch):
    import research_claude
    monkeypatch.setattr(research_claude, "_call",
                        lambda *a, **k: "Resposta global. [PRIO3/Tese #1]")

    context = research_db.build_rag_context("qual empresa tem maior upside", ticker=None)
    research_db.save_qa_message(None, "user", "qual empresa tem maior upside", None, "admin")
    result = research_claude.answer_question("qual empresa tem maior upside", None, context)
    research_db.save_qa_message(None, "assistant", result["answer"], result.get("sources"), "claude")

    global_msgs = research_db.get_qa_messages(ticker=None)
    assert len(global_msgs) == 2
    # Mensagens globais não aparecem em busca por ticker
    prio_msgs = research_db.get_qa_messages(ticker="PRIO3")
    assert len(prio_msgs) == 0
```

- [ ] **Rodar — deve falhar**

```
pytest tests/test_research_phase3.py::test_qa_route_logic_saves_messages -v
```

Esperado: FAILED (funções não existem ainda)

- [ ] **Adicionar as rotas em `app.py`** — adicionar após a seção de search (`/api/research/search`):

```python
# ── Q&A ────────────────────────────────────────────────────────────────────

@app.route("/api/research/qa", methods=["GET"])
def api_research_qa_get():
    ticker = (request.args.get("ticker") or "").strip().upper() or None
    messages = _rdb.get_qa_messages(ticker=ticker)
    return jsonify({"messages": messages})


@app.route("/api/research/qa", methods=["POST"])
def api_research_qa_post():
    data    = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    ticker   = (data.get("ticker") or "").strip().upper() or None
    if not question:
        return jsonify({"error": "question required"}), 400

    user = _research_user()
    context_chunks = _rdb.build_rag_context(question, ticker=ticker)
    _rdb.save_qa_message(ticker, "user", question, None, user)

    result = _claude.answer_question(question, ticker, context_chunks)
    if result is None:
        return jsonify({"error": "Claude API error"}), 500

    _rdb.save_qa_message(ticker, "assistant", result["answer"], result.get("sources"), "claude")
    return jsonify(result)
```

- [ ] **Rodar os testes**

```
pytest tests/test_research_phase3.py::test_qa_get_empty tests/test_research_phase3.py::test_qa_post_returns_answer -v
```

Esperado: 2 PASSED

- [ ] **Commit**

```bash
git add app.py tests/test_research_phase3.py
git commit -m "feat: rotas GET e POST /api/research/qa"
```

---

## Task 7: Flask — trigger de sugestão de tese + rota `dismiss`

**Files:**
- Modify: `app.py`
- Test: `tests/test_research_phase3.py`

- [ ] **Escrever os testes** — testar `_trigger_thesis_suggestion` e a lógica de dismiss diretamente

```python
def test_trigger_thesis_suggestion_creates_rascunho(db, monkeypatch):
    """Testa a função auxiliar _trigger_thesis_suggestion diretamente."""
    import research_claude
    monkeypatch.setattr(research_claude, "_call",
                        lambda *a, **k: "Tese atualizada [ATUALIZADO].")

    research_db.upsert_company("PRIO3", name="PetroRio", user="test")
    tid = research_db.create_thesis("PRIO3", "Tese original.", user="test")
    research_db.approve_thesis(tid, user="test")
    fid = research_db.create_filing(
        "PRIO3", "CVM", "FATO_RELEVANTE", "Produção recorde",
        summary="Produção cresceu 8% QoQ.", update_thesis=True
    )

    # Simula o que a rota faz ao aprovação com update_thesis=True
    filing = research_db.get_filing(fid)
    active = research_db.get_active_thesis("PRIO3")
    current_content = active["content"] if active else ""
    draft = research_claude.suggest_thesis_update(current_content, filing["summary"], "filing")
    assert draft is not None
    new_id = research_db.create_thesis(
        "PRIO3", draft, user="claude",
        auto_generated=1, trigger_type="filing", trigger_id=fid
    )

    theses = research_db.get_theses("PRIO3")
    auto = [t for t in theses if t["auto_generated"] == 1 and t["status"] == "RASCUNHO"]
    assert len(auto) == 1
    assert auto[0]["trigger_id"] == fid
    assert "[ATUALIZADO]" in auto[0]["content"]


def test_dismiss_archives_rascunho(db):
    """Testa que arquivar um rascunho muda o status para ARQUIVADA."""
    research_db.upsert_company("PRIO3", name="PetroRio", user="test")
    tid = research_db.create_thesis("PRIO3", "Rascunho auto.", user="claude",
                                    auto_generated=1)
    # Simula o que a rota dismiss faz
    with research_db.get_conn() as conn:
        old = dict(conn.execute("SELECT * FROM theses WHERE id=?", (tid,)).fetchone())
        conn.execute("UPDATE theses SET status='ARQUIVADA' WHERE id=?", (tid,))
        research_db.audit(conn, "thesis", tid, "PRIO3", "UPDATE", "admin",
                          old, {**old, "status": "ARQUIVADA"})

    with research_db.get_conn() as conn:
        row = conn.execute("SELECT status FROM theses WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "ARQUIVADA"
```

- [ ] **Rodar — deve falhar**

```
pytest tests/test_research_phase3.py::test_trigger_thesis_suggestion_creates_rascunho -v
```

Esperado: FAILED com `AttributeError` (funções de Claude ainda não apontam para os prompts novos, ou `suggest_thesis_update` não existe)

- [ ] **Adicionar trigger na rota `api_research_filing_review` em `app.py`**

Substituir a função existente:

```python
@app.route("/api/research/filings/<int:filing_id>/review", methods=["POST"])
@require_admin
def api_research_filing_review(filing_id):
    payload = request.json or {}
    action  = payload.get("action", "").upper()
    if action not in ("APPROVE", "REJECT"):
        return jsonify({"error": "action must be APPROVE or REJECT"}), 400
    ok = _rdb.review_filing(filing_id, action, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404

    if action == "APPROVE":
        filing = _rdb.get_filing(filing_id)
        if filing and filing.get("update_thesis") and filing.get("ticker"):
            _trigger_thesis_suggestion(
                filing["ticker"], filing.get("summary", ""), "filing", filing_id
            )

    return jsonify({"ok": True})
```

- [ ] **Adicionar trigger na rota `api_research_news_review` em `app.py`**

Substituir a função existente:

```python
@app.route("/api/research/news/<int:news_id>/review", methods=["POST"])
@require_admin
def api_research_news_review(news_id):
    payload = request.json or {}
    action  = payload.get("action", "").upper()
    if action not in ("APPROVE", "REJECT"):
        return jsonify({"error": "action must be APPROVE or REJECT"}), 400
    ok = _rdb.review_news(news_id, action, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404

    if action == "APPROVE":
        news = _rdb.get_news_item(news_id)
        if news and news.get("update_thesis") and news.get("ticker"):
            _trigger_thesis_suggestion(
                news["ticker"], news.get("summary", ""), "news", news_id
            )

    return jsonify({"ok": True})
```

- [ ] **Adicionar função auxiliar `_trigger_thesis_suggestion` em `app.py`** — logo antes de `api_research_filing_review`:

```python
def _trigger_thesis_suggestion(ticker, trigger_summary, trigger_type, trigger_id):
    """Background helper: gera rascunho de tese via Claude e salva como RASCUNHO auto_generated."""
    try:
        active = _rdb.get_active_thesis(ticker)
        current_content = active["content"] if active else ""
        draft = _claude.suggest_thesis_update(current_content, trigger_summary, trigger_type)
        if draft:
            _rdb.create_thesis(
                ticker, draft, user="claude",
                auto_generated=1, trigger_type=trigger_type, trigger_id=trigger_id
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("_trigger_thesis_suggestion [%s]: %s", ticker, e)
```

- [ ] **Adicionar rota `dismiss` em `app.py`** — após a rota `approve`:

```python
@app.route("/api/research/theses/<int:thesis_id>/dismiss", methods=["POST"])
@require_admin
def api_research_thesis_dismiss(thesis_id):
    """Archive an auto-generated draft thesis (user ignored the suggestion)."""
    with _rdb.get_conn() as conn:
        row = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        old = dict(row)
        conn.execute("UPDATE theses SET status='ARQUIVADA' WHERE id=?", (thesis_id,))
        _rdb.audit(conn, "thesis", thesis_id, old["ticker"], "UPDATE",
                   _research_user(), old, {**old, "status": "ARQUIVADA"})
    return jsonify({"ok": True})
```

- [ ] **Rodar todos os testes**

```
pytest tests/test_research_phase3.py -v
```

Esperado: todos PASSED

- [ ] **Commit**

```bash
git add app.py tests/test_research_phase3.py
git commit -m "feat: trigger de sugestão de tese ao aprovar filing/notícia + rota dismiss"
```

---

## Task 8: Pipeline — propagar `update_thesis` ao criar filings/news

**Files:**
- Modify: `research_pipeline.py`

> Esta task não tem testes automatizados — verificação é manual (ver Task 12).

- [ ] **Localizar em `research_pipeline.py` onde `_rdb.create_filing` é chamado**

```
grep -n "create_filing\|create_news" research_pipeline.py
```

- [ ] **Para cada chamada de `_rdb.create_filing(...)` no pipeline, adicionar os novos parâmetros**

O padrão atual é chamado logo após `_claude.process_filing(...)`. Atualizar para:

```python
# Antes (exemplo):
_rdb.create_filing(ticker, source, doc_type, title,
                   filing_date=date_str, raw_url=url,
                   summary=result["summary"],
                   key_points=result["key_points"],
                   sentiment=result["sentiment"])

# Depois:
_rdb.create_filing(ticker, source, doc_type, title,
                   filing_date=date_str, raw_url=url,
                   summary=result["summary"],
                   key_points=result["key_points"],
                   sentiment=result["sentiment"],
                   update_thesis=result.get("update_thesis", False),
                   update_reason=result.get("update_reason"))
```

- [ ] **Para cada chamada de `_rdb.create_news(...)` no pipeline, adicionar os novos parâmetros**

```python
# Antes:
_rdb.create_news(ticker, title, source=source, url=url,
                 published_at=pub_at, summary=result["summary"],
                 sentiment=result["sentiment"],
                 relevance=result.get("relevance", 0))

# Depois:
_rdb.create_news(ticker, title, source=source, url=url,
                 published_at=pub_at, summary=result["summary"],
                 sentiment=result["sentiment"],
                 relevance=result.get("relevance", 0),
                 update_thesis=result.get("update_thesis", False),
                 update_reason=result.get("update_reason"))
```

- [ ] **Commit**

```bash
git add research_pipeline.py
git commit -m "feat: pipeline propaga update_thesis/update_reason ao criar filings e news"
```

---

## Task 9: Frontend HTML — botão PERGUNTAR, sidebar global, painel lateral

**Files:**
- Modify: `templates/index.html`

- [ ] **Adicionar o item "Q&A GLOBAL" no sidebar**

Localizar em `index.html` o bloco do sidebar da aba Research (deve ter a lista de empresas com classes como `research-sidebar` ou `company-list`). Adicionar antes da lista de empresas:

```html
<div class="qa-global-item" id="qaGlobalItem" onclick="openGlobalQA()">
  <span class="qa-global-icon">✦</span> Q&amp;A GLOBAL
</div>
```

- [ ] **Adicionar o botão "PERGUNTAR" na header de empresa**

Localizar o elemento de header da empresa no Research (onde ficam o nome da empresa e o botão "EXPORTAR MD"). Adicionar ao lado:

```html
<button class="btn-qa-company" id="btnQACompany" onclick="openQAPanel(currentResearchTicker)" style="display:none">
  ✦ PERGUNTAR
</button>
```

- [ ] **Adicionar o div do painel lateral Q&A por empresa**

Adicionar antes do fechamento do `</body>` (ou dentro do container da aba Research):

```html
<!-- Q&A per-company sliding panel -->
<div id="qaPanel" class="qa-panel" style="display:none">
  <div class="qa-panel-header">
    <span id="qaPanelTitle">✦ Q&A — <span id="qaPanelTicker"></span></span>
    <button onclick="closeQAPanel()" class="qa-panel-close">✕</button>
  </div>
  <div id="qaMessages" class="qa-messages"></div>
  <div class="qa-panel-input">
    <textarea id="qaInput" placeholder="Faça uma pergunta sobre a empresa..." rows="2"></textarea>
    <button onclick="submitQAQuestion()" id="qaSubmitBtn">PERGUNTAR</button>
  </div>
</div>
<div id="qaOverlay" class="qa-overlay" onclick="closeQAPanel()" style="display:none"></div>
```

- [ ] **Adicionar o div do painel global Q&A** — no container principal de conteúdo da aba Research, como uma "view" alternativa à empresa selecionada:

```html
<div id="qaGlobalPanel" class="qa-global-panel" style="display:none">
  <div class="qa-global-header">✦ Q&A — BASE COMPLETA</div>
  <div id="qaGlobalMessages" class="qa-messages"></div>
  <div class="qa-panel-input">
    <textarea id="qaGlobalInput" placeholder="Pergunte sobre qualquer empresa da base..." rows="2"></textarea>
    <button onclick="submitGlobalQA()" id="qaGlobalSubmitBtn">PERGUNTAR</button>
  </div>
</div>
```

- [ ] **Commit**

```bash
git add templates/index.html
git commit -m "feat: HTML para Q&A panel, botão PERGUNTAR e sidebar global"
```

---

## Task 10: Frontend JS — Q&A por empresa (painel lateral)

**Files:**
- Modify: `static/app.js`

- [ ] **Adicionar variável de estado e funções do painel no `app.js`**

Adicionar junto às variáveis de estado da aba Research (onde `currentResearchTicker` está definido):

```javascript
let currentQATicker = null;

function openQAPanel(ticker) {
  currentQATicker = ticker;
  document.getElementById('qaPanelTicker').textContent = ticker;
  document.getElementById('qaPanel').style.display = 'flex';
  document.getElementById('qaOverlay').style.display = 'block';
  loadQAHistory(ticker);
}

function closeQAPanel() {
  document.getElementById('qaPanel').style.display = 'none';
  document.getElementById('qaOverlay').style.display = 'none';
  currentQATicker = null;
}

async function loadQAHistory(ticker) {
  const res = await fetch(`/api/research/qa?ticker=${encodeURIComponent(ticker)}`);
  const data = await res.json();
  renderQAMessages('qaMessages', data.messages || []);
}

async function submitQAQuestion() {
  const input = document.getElementById('qaInput');
  const question = input.value.trim();
  if (!question || !currentQATicker) return;

  input.value = '';
  const btn = document.getElementById('qaSubmitBtn');
  btn.disabled = true;
  btn.textContent = '...';

  // Render user message immediately
  const container = document.getElementById('qaMessages');
  container.innerHTML += renderQAMessage({role: 'user', content: question, created_at: new Date().toISOString()});
  container.scrollTop = container.scrollHeight;

  try {
    const res = await fetch('/api/research/qa', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question, ticker: currentQATicker})
    });
    const data = await res.json();
    if (data.answer) {
      container.innerHTML += renderQAMessage({
        role: 'assistant', content: data.answer,
        sources: data.sources || [], created_at: new Date().toISOString()
      });
      container.scrollTop = container.scrollHeight;
    }
  } catch (e) {
    console.error('Q&A error:', e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'PERGUNTAR';
  }
}

function renderQAMessages(containerId, messages) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = messages.map(renderQAMessage).join('');
  el.scrollTop = el.scrollHeight;
}

function renderQAMessage(msg) {
  const isUser = msg.role === 'user';
  const sources = msg.sources ? (typeof msg.sources === 'string' ? JSON.parse(msg.sources) : msg.sources) : [];
  const sourcesHtml = sources.length
    ? `<div class="qa-sources">Fontes: ${sources.map(s =>
        `<span class="qa-citation">[${s.ticker ? s.ticker + '/' : ''}${s.type} #${s.id}]</span>`
      ).join(' ')}</div>`
    : '';
  const timeStr = msg.created_at ? msg.created_at.slice(11, 16) : '';
  return `
    <div class="qa-message qa-message-${isUser ? 'user' : 'assistant'}">
      <div class="qa-message-role">${isUser ? 'Você' : '✦ Claude'} <span class="qa-time">${timeStr}</span></div>
      <div class="qa-message-content">${escapeHtml(msg.content)}</div>
      ${sourcesHtml}
    </div>`;
}

function escapeHtml(text) {
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
```

- [ ] **Mostrar o botão "PERGUNTAR" ao selecionar uma empresa**

Localizar a função que renderiza/abre a página de empresa (ex: `selectCompany` ou `openCompanyPage`). Adicionar:

```javascript
document.getElementById('btnQACompany').style.display = 'inline-flex';
```

Ao fechar/desselecionar uma empresa:

```javascript
document.getElementById('btnQACompany').style.display = 'none';
closeQAPanel();
```

- [ ] **Verificar manualmente no browser**

```
python app.py
```

1. Abrir a aba Research, selecionar uma empresa
2. Botão "✦ PERGUNTAR" aparece na header
3. Clicar → painel lateral abre
4. Digitar uma pergunta e enviar → resposta com citações aparece
5. Recarregar página → histórico persiste

- [ ] **Commit**

```bash
git add static/app.js
git commit -m "feat: painel lateral Q&A por empresa (openQAPanel, loadQAHistory, renderQAMessages)"
```

---

## Task 11: Frontend JS — Q&A global + banner de sugestão de tese

**Files:**
- Modify: `static/app.js`

- [ ] **Adicionar funções do Q&A global**

```javascript
async function openGlobalQA() {
  // Deselect any company
  document.getElementById('qaGlobalPanel').style.display = 'flex';
  // Hide company content panel if applicable
  const companyPanel = document.getElementById('researchCompanyPanel'); // adjust ID to actual
  if (companyPanel) companyPanel.style.display = 'none';

  // Mark sidebar item as active
  document.querySelectorAll('.qa-global-item').forEach(el => el.classList.add('active'));

  loadGlobalQAHistory();
}

async function loadGlobalQAHistory() {
  const res = await fetch('/api/research/qa');
  const data = await res.json();
  renderQAMessages('qaGlobalMessages', data.messages || []);
}

async function submitGlobalQA() {
  const input = document.getElementById('qaGlobalInput');
  const question = input.value.trim();
  if (!question) return;

  input.value = '';
  const btn = document.getElementById('qaGlobalSubmitBtn');
  btn.disabled = true;
  btn.textContent = '...';

  const container = document.getElementById('qaGlobalMessages');
  container.innerHTML += renderQAMessage({role: 'user', content: question, created_at: new Date().toISOString()});
  container.scrollTop = container.scrollHeight;

  try {
    const res = await fetch('/api/research/qa', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question})  // no ticker = global
    });
    const data = await res.json();
    if (data.answer) {
      container.innerHTML += renderQAMessage({
        role: 'assistant', content: data.answer,
        sources: data.sources || [], created_at: new Date().toISOString()
      });
      container.scrollTop = container.scrollHeight;
    }
  } catch (e) {
    console.error('Global Q&A error:', e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'PERGUNTAR';
  }
}
```

- [ ] **Adicionar detecção e renderização do banner de sugestão de tese**

Na função que carrega a sub-aba TESE de uma empresa (ex: `loadThesisTab(ticker)`), adicionar no início:

```javascript
async function checkThesisBanner(ticker) {
  const res = await fetch(`/api/research/theses/${ticker}`);
  const data = await res.json();
  const theses = data.theses || [];
  const autoDraft = theses.find(t => t.auto_generated === 1 && t.status === 'RASCUNHO');
  const activeTesis = theses.find(t => t.status === 'ATIVA');

  const bannerEl = document.getElementById('thesisBanner');
  if (!bannerEl) return;

  if (autoDraft) {
    bannerEl.style.display = 'block';
    bannerEl.innerHTML = `
      <div class="thesis-banner">
        <div class="thesis-banner-icon">⚡</div>
        <div class="thesis-banner-text">
          <strong>Claude detectou mudança relevante na tese</strong>
          <span>Com base em ${autoDraft.trigger_type === 'filing' ? 'filing' : 'notícia'} aprovado, Claude gerou um rascunho de atualização.</span>
        </div>
        <div class="thesis-banner-actions">
          <button onclick="viewThesisDraft(${autoDraft.id}, ${activeTesis ? activeTesis.id : 'null'})" class="btn-view-draft">VER RASCUNHO</button>
          <button onclick="dismissThesisDraft(${autoDraft.id})" class="btn-dismiss-draft">IGNORAR</button>
        </div>
      </div>`;
  } else {
    bannerEl.style.display = 'none';
  }
}

async function dismissThesisDraft(draftId) {
  await fetch(`/api/research/theses/${draftId}/dismiss`, {method: 'POST'});
  document.getElementById('thesisBanner').style.display = 'none';
}

async function viewThesisDraft(draftId, activeId) {
  // Fetch both thesis contents
  const [draftRes, activeRes] = await Promise.all([
    fetch(`/api/research/theses/${currentResearchTicker}`),
    activeId ? fetch(`/api/research/theses/${currentResearchTicker}`) : Promise.resolve(null)
  ]);
  const data = await draftRes.json();
  const theses = data.theses || [];
  const draft = theses.find(t => t.id === draftId);
  const active = theses.find(t => t.id === activeId);

  // Render side-by-side editor in the thesis content area
  const contentEl = document.getElementById('thesisContent'); // adjust to actual ID
  if (!contentEl || !draft) return;

  contentEl.innerHTML = `
    <div class="thesis-diff">
      <div class="thesis-diff-side">
        <div class="thesis-diff-label">TESE ATUAL</div>
        <pre class="thesis-diff-text">${escapeHtml(active ? active.content : '(nenhuma tese ativa)')}</pre>
      </div>
      <div class="thesis-diff-side">
        <div class="thesis-diff-label">RASCUNHO CLAUDE</div>
        <textarea id="draftEditor" class="thesis-diff-editor">${escapeHtml(draft.content)}</textarea>
        <div class="thesis-diff-actions">
          <button onclick="approveDraft(${draftId})">APROVAR RASCUNHO</button>
          <button onclick="dismissThesisDraft(${draftId})">DESCARTAR</button>
        </div>
      </div>
    </div>`;
}

async function approveDraft(draftId) {
  const content = document.getElementById('draftEditor').value;
  // Update content first if edited
  await fetch(`/api/research/theses/${draftId}`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content})
  });
  // Then approve
  await fetch(`/api/research/theses/${draftId}/approve`, {method: 'POST'});
  // Reload thesis tab
  loadThesisTab(currentResearchTicker);
}
```

- [ ] **Chamar `checkThesisBanner(ticker)` ao abrir a sub-aba TESE**

Na função `loadThesisTab(ticker)` existente, adicionar ao final:

```javascript
checkThesisBanner(ticker);
```

- [ ] **Adicionar div `thesisBanner` no HTML da sub-aba TESE** (se ainda não existir)

Em `templates/index.html`, dentro do container da sub-aba TESE:

```html
<div id="thesisBanner" style="display:none"></div>
```

- [ ] **Verificar manualmente no browser**

1. Aprovar um filing com `update_thesis=True` (pode criar um via `POST /api/research/ingest`)
2. Abrir a empresa → sub-aba TESE → banner ⚡ aparece
3. Clicar "VER RASCUNHO" → editor lado a lado aparece
4. Editar o rascunho e clicar "APROVAR RASCUNHO" → tese ativa atualiza
5. Clicar "IGNORAR" → banner desaparece, rascunho arquivado

- [ ] **Commit**

```bash
git add static/app.js templates/index.html
git commit -m "feat: Q&A global + banner de sugestão automática de tese"
```

---

## Task 12: CSS — estilos do painel Q&A e banner

**Files:**
- Modify: `static/style.css`

- [ ] **Adicionar os estilos no final de `style.css`**

```css
/* ── Q&A Panel (per-company sliding) ─────────────────────────────────── */
.qa-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 300px;
  height: 100vh;
  background: #0d0d1a;
  border-left: 1px solid #2a2a4a;
  display: flex;
  flex-direction: column;
  z-index: 1000;
  box-shadow: -4px 0 20px rgba(0,0,0,0.5);
}

.qa-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.3);
  z-index: 999;
}

.qa-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #2a2a4a;
  font-size: 12px;
  font-weight: 700;
  color: #4fc3f7;
}

.qa-panel-close {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  font-size: 14px;
}

.qa-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.qa-message {
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
}

.qa-message-user {
  background: #1a2a3a;
  border: 1px solid #2a3a5a;
  align-self: flex-end;
  max-width: 90%;
}

.qa-message-assistant {
  background: #111;
  border: 1px solid #2a2a4a;
  align-self: flex-start;
  max-width: 100%;
}

.qa-message-role {
  font-size: 10px;
  font-weight: 700;
  margin-bottom: 4px;
  color: #4fc3f7;
}

.qa-message-assistant .qa-message-role {
  color: #81c784;
}

.qa-message-content {
  color: #ccc;
  white-space: pre-wrap;
  word-break: break-word;
}

.qa-time {
  font-weight: 400;
  color: #555;
  margin-left: 6px;
}

.qa-sources {
  margin-top: 6px;
  font-size: 10px;
  color: #666;
}

.qa-citation {
  color: #4fc3f7;
  cursor: pointer;
  margin-right: 4px;
}

.qa-citation:hover {
  text-decoration: underline;
}

.qa-panel-input {
  padding: 10px;
  border-top: 1px solid #2a2a4a;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.qa-panel-input textarea {
  background: #111;
  border: 1px solid #333;
  border-radius: 4px;
  color: #ccc;
  font-size: 11px;
  padding: 6px 8px;
  resize: none;
  font-family: inherit;
}

.qa-panel-input button {
  background: #1a3a5a;
  border: 1px solid #4fc3f7;
  color: #4fc3f7;
  border-radius: 4px;
  padding: 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 0.05em;
}

.qa-panel-input button:hover {
  background: #4fc3f7;
  color: #000;
}

/* ── Q&A Global item in sidebar ──────────────────────────────────────── */
.qa-global-item {
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 700;
  color: #4fc3f7;
  border: 1px solid #2a3a5a;
  border-radius: 4px;
  margin-bottom: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.05em;
}

.qa-global-item:hover,
.qa-global-item.active {
  background: #1a2a3a;
}

.qa-global-icon {
  font-size: 10px;
}

/* ── Q&A Global panel ────────────────────────────────────────────────── */
.qa-global-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.qa-global-header {
  padding: 14px 16px;
  font-size: 13px;
  font-weight: 700;
  color: #4fc3f7;
  border-bottom: 1px solid #2a2a4a;
}

/* ── Thesis suggestion banner ────────────────────────────────────────── */
.thesis-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: #1a1500;
  border: 1px solid #f0a500;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 14px;
}

.thesis-banner-icon {
  font-size: 18px;
  line-height: 1;
  flex-shrink: 0;
}

.thesis-banner-text {
  flex: 1;
  font-size: 12px;
}

.thesis-banner-text strong {
  display: block;
  color: #f0a500;
  margin-bottom: 3px;
}

.thesis-banner-text span {
  color: #aaa;
}

.thesis-banner-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  align-items: center;
}

.btn-view-draft {
  background: #2e7d32;
  border: none;
  color: #fff;
  border-radius: 3px;
  padding: 5px 12px;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 0.05em;
}

.btn-dismiss-draft {
  background: #333;
  border: 1px solid #555;
  color: #aaa;
  border-radius: 3px;
  padding: 5px 12px;
  font-size: 10px;
  cursor: pointer;
}

/* ── Thesis diff side-by-side ────────────────────────────────────────── */
.thesis-diff {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  height: 100%;
}

.thesis-diff-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.thesis-diff-label {
  font-size: 10px;
  font-weight: 700;
  color: #888;
  letter-spacing: 0.08em;
}

.thesis-diff-text {
  flex: 1;
  background: #111;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  color: #aaa;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
  font-family: inherit;
}

.thesis-diff-editor {
  flex: 1;
  background: #111;
  border: 1px solid #4fc3f7;
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  color: #ccc;
  resize: none;
  font-family: inherit;
  line-height: 1.5;
}

.thesis-diff-actions {
  display: flex;
  gap: 8px;
}

.thesis-diff-actions button:first-child {
  background: #1a3a5a;
  border: 1px solid #4fc3f7;
  color: #4fc3f7;
  border-radius: 4px;
  padding: 6px 14px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.thesis-diff-actions button:last-child {
  background: #333;
  border: 1px solid #555;
  color: #aaa;
  border-radius: 4px;
  padding: 6px 14px;
  font-size: 11px;
  cursor: pointer;
}

/* ── Button: PERGUNTAR on company header ─────────────────────────────── */
.btn-qa-company {
  background: transparent;
  border: 1px solid #4fc3f7;
  color: #4fc3f7;
  border-radius: 3px;
  padding: 4px 10px;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 0.05em;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.btn-qa-company:hover {
  background: #4fc3f7;
  color: #000;
}
```

- [ ] **Verificar visual completo no browser**

```
python app.py
```

Checklist visual:
- Painel lateral abre suavemente ao clicar "✦ PERGUNTAR"
- Mensagens do usuário ficam à direita (estilo diferente)
- Respostas do Claude ficam à esquerda com citações em azul
- Item "✦ Q&A GLOBAL" está no topo do sidebar
- Banner de tese aparece em âmbar com ícone ⚡
- Editor lado a lado está alinhado e usável

- [ ] **Rodar suite de testes completa**

```
pytest tests/test_research_phase3.py -v
```

Esperado: todos PASSED

- [ ] **Commit final**

```bash
git add static/style.css
git commit -m "feat: CSS do Q&A panel, sidebar global e banner de sugestão de tese"
```

---

## Verificação End-to-End

Após todas as tasks:

```
python app.py
```

1. Abrir aba Research como admin → selecionar empresa → botão "✦ PERGUNTAR" aparece
2. Abrir painel → digitar pergunta → resposta com citações `[Tese #1]` aparece
3. Recarregar → histórico persiste
4. Clicar "✦ Q&A GLOBAL" no sidebar → interface global carrega
5. Perguntar sem ticker → resposta cita múltiplas empresas
6. Via Postman ou `curl`, criar filing com `update_thesis=True` e aprovado → verificar banner na sub-aba TESE
7. Clicar "VER RASCUNHO" → editor lado a lado funciona
8. Aprovar rascunho → tese ativa atualiza, HISTÓRICO registra
9. Repetir com "IGNORAR" → banner desaparece, rascunho ARQUIVADO no banco
10. Rodar `pytest tests/test_research_phase3.py -v` → todos PASSED
