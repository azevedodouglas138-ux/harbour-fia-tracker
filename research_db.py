"""
research_db.py — Camada de acesso ao SQLite para a aba RESEARCH (212).

Schema: companies, theses, filings, news_items, notes, valuations, audit_log, research_fts (FTS5).
"""

import json
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.environ.get(
    "RESEARCH_DB_PATH",
    os.path.join(BASE_DIR, "data", "research.db")
)

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS companies (
    ticker      TEXT PRIMARY KEY,
    name        TEXT,
    market      TEXT CHECK(market IN ('BR','US')) DEFAULT 'BR',
    status      TEXT CHECK(status IN ('INVESTIDO','WATCHLIST','UNIVERSO')) DEFAULT 'UNIVERSO',
    sector      TEXT,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS theses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker         TEXT NOT NULL REFERENCES companies(ticker),
    content        TEXT NOT NULL DEFAULT '',
    version        INTEGER NOT NULL DEFAULT 1,
    status         TEXT CHECK(status IN ('ATIVA','RASCUNHO','ARQUIVADA')) DEFAULT 'RASCUNHO',
    created_by     TEXT NOT NULL DEFAULT 'admin',
    created_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    auto_generated INTEGER DEFAULT 0,
    trigger_type   TEXT,
    trigger_id     INTEGER
);

CREATE TABLE IF NOT EXISTS filings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL REFERENCES companies(ticker),
    source        TEXT CHECK(source IN ('CVM','SEC')) DEFAULT 'CVM',
    type          TEXT,
    title         TEXT,
    filing_date   TEXT,
    raw_url       TEXT,
    summary       TEXT,
    key_points    TEXT,   -- JSON array
    sentiment     TEXT CHECK(sentiment IN ('POSITIVO','NEUTRO','NEGATIVO')),
    review_status TEXT CHECK(review_status IN ('PENDENTE','APROVADO','REJEITADO')) DEFAULT 'PENDENTE',
    reviewed_by   TEXT,
    reviewed_at   TEXT,
    processed_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    update_thesis  INTEGER DEFAULT 0,
    update_reason  TEXT
);

CREATE TABLE IF NOT EXISTS news_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT,
    sector        TEXT,
    title         TEXT NOT NULL,
    source        TEXT,
    url           TEXT,
    published_at  TEXT,
    summary       TEXT,
    sentiment     TEXT CHECK(sentiment IN ('POSITIVO','NEUTRO','NEGATIVO')),
    relevance     REAL DEFAULT 0,
    review_status TEXT CHECK(review_status IN ('PENDENTE','APROVADO','REJEITADO')) DEFAULT 'PENDENTE',
    reviewed_by   TEXT,
    reviewed_at   TEXT,
    update_thesis  INTEGER DEFAULT 0,
    update_reason  TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL REFERENCES companies(ticker),
    content     TEXT NOT NULL DEFAULT '',
    note_type   TEXT CHECK(note_type IN ('OBSERVACAO','REUNIAO','CALL','ALERTA','IDEIA')) DEFAULT 'OBSERVACAO',
    created_by  TEXT NOT NULL DEFAULT 'admin',
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS valuations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL REFERENCES companies(ticker),
    target_price REAL,
    methodology  TEXT CHECK(methodology IN ('DCF','EV/EBITDA','P/L','DDM','SOMA_PARTES')),
    upside_pct   REAL,
    assumptions  TEXT,   -- JSON
    notes        TEXT,
    created_by   TEXT NOT NULL DEFAULT 'admin',
    created_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   TEXT,
    ticker      TEXT,
    action      TEXT CHECK(action IN ('CREATE','UPDATE','DELETE','APPROVE','REJECT')) NOT NULL,
    user        TEXT NOT NULL DEFAULT 'admin',
    old_value   TEXT,   -- JSON
    new_value   TEXT,   -- JSON
    timestamp   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS research_fts USING fts5(
    ticker,
    content_type,
    content_id UNINDEXED,
    text,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS qa_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT REFERENCES companies(ticker),
    role        TEXT CHECK(role IN ('user','assistant')) NOT NULL,
    content     TEXT NOT NULL,
    sources     TEXT,
    created_by  TEXT NOT NULL DEFAULT 'admin',
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

-- Portfólio Global: tese versionada do fundo (espelha 'theses' por empresa)
CREATE TABLE IF NOT EXISTS portfolio_thesis (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL DEFAULT '',
    body_md      TEXT NOT NULL DEFAULT '',
    version      INTEGER NOT NULL DEFAULT 1,
    status       TEXT CHECK(status IN ('ATIVA','RASCUNHO','ARQUIVADA')) DEFAULT 'RASCUNHO',
    created_by   TEXT NOT NULL DEFAULT 'admin',
    created_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    published_at TEXT
);

-- Portfólio Global: log de decisões de alocação (append-only, arquivável)
CREATE TABLE IF NOT EXISTS portfolio_decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    tipo          TEXT CHECK(tipo IN ('DECISAO','REGRA','NOTA')) NOT NULL DEFAULT 'DECISAO',
    subtipo       TEXT,                  -- COMPRA|VENDA|AUMENTO|REDUCAO|MANUTENCAO (livre quando tipo!=DECISAO)
    titulo        TEXT NOT NULL,
    rationale_md  TEXT NOT NULL DEFAULT '',
    tickers_json  TEXT,                  -- JSON array
    peso_antes    REAL,
    peso_depois   REAL,
    snapshot_json TEXT,                  -- JSON: preços/pesos/Ibov no momento
    author        TEXT NOT NULL DEFAULT 'admin',
    created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now')),
    status        TEXT CHECK(status IN ('ativa','arquivada')) DEFAULT 'ativa'
);

CREATE INDEX IF NOT EXISTS idx_pdecisions_date   ON portfolio_decisions(date DESC);
CREATE INDEX IF NOT EXISTS idx_pdecisions_status ON portfolio_decisions(status);
"""

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
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise


def init_db():
    """Create tables if they don't exist and run migrations."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)


# ---------------------------------------------------------------------------
# Audit log helper
# ---------------------------------------------------------------------------

def audit(conn, entity_type, entity_id, ticker, action, user, old_value=None, new_value=None):
    conn.execute(
        "INSERT INTO audit_log (entity_type, entity_id, ticker, action, user, old_value, new_value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entity_type, str(entity_id) if entity_id is not None else None, ticker, action, user,
         json.dumps(old_value, ensure_ascii=False) if old_value is not None else None,
         json.dumps(new_value, ensure_ascii=False) if new_value is not None else None)
    )


# ---------------------------------------------------------------------------
# FTS5 helpers
# ---------------------------------------------------------------------------

def _fts_upsert(conn, ticker, content_type, content_id, text):
    conn.execute(
        "DELETE FROM research_fts WHERE content_type=? AND content_id=?",
        (content_type, str(content_id))
    )
    conn.execute(
        "INSERT INTO research_fts (ticker, content_type, content_id, text) VALUES (?, ?, ?, ?)",
        (ticker, content_type, str(content_id), text or "")
    )

def _fts_delete(conn, content_type, content_id):
    conn.execute(
        "DELETE FROM research_fts WHERE content_type=? AND content_id=?",
        (content_type, str(content_id))
    )


def fts_search(query, limit=50):
    """Full-text search across the research base. Returns list of dicts."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ticker, content_type, content_id, snippet(research_fts,3,'<b>','</b>','…',20) AS snippet "
            "FROM research_fts WHERE research_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def get_companies():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM companies ORDER BY status, ticker"
        ).fetchall()
    return [dict(r) for r in rows]


def get_company(ticker):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM companies WHERE ticker=?", (ticker,)).fetchone()
    return dict(row) if row else None


def upsert_company(ticker, name=None, market="BR", status="UNIVERSO", sector=None, user="admin"):
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM companies WHERE ticker=?", (ticker,)).fetchone()
        if existing:
            old = dict(existing)
            conn.execute(
                "UPDATE companies SET name=COALESCE(?,name), market=?, status=?, "
                "sector=COALESCE(?,sector), updated_at=? WHERE ticker=?",
                (name, market, status, sector, now, ticker)
            )
            new = dict(conn.execute("SELECT * FROM companies WHERE ticker=?", (ticker,)).fetchone())
            audit(conn, "company", ticker, ticker, "UPDATE", user, old, new)
        else:
            conn.execute(
                "INSERT INTO companies (ticker, name, market, status, sector, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, name, market, status, sector, now, now)
            )
            new = {"ticker": ticker, "name": name, "market": market, "status": status,
                   "sector": sector, "created_at": now, "updated_at": now}
            audit(conn, "company", ticker, ticker, "CREATE", user, None, new)


def delete_company(ticker, user="admin"):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM companies WHERE ticker=?", (ticker,)).fetchone()
        if not existing:
            return False
        old = dict(existing)
        conn.execute("DELETE FROM companies WHERE ticker=?", (ticker,))
        audit(conn, "company", ticker, ticker, "DELETE", user, old, None)
    return True


# ---------------------------------------------------------------------------
# Theses
# ---------------------------------------------------------------------------

def get_theses(ticker):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM theses WHERE ticker=? ORDER BY version DESC",
            (ticker,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_thesis(ticker):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM theses WHERE ticker=? AND status='ATIVA' ORDER BY version DESC LIMIT 1",
            (ticker,)
        ).fetchone()
    return dict(row) if row else None


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


def approve_thesis(thesis_id, user="admin"):
    """Approves a thesis: archives current ATIVA, activates this one."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
        if not row:
            return False
        old = dict(row)
        ticker = old["ticker"]
        # Archive current active
        conn.execute(
            "UPDATE theses SET status='ARQUIVADA' WHERE ticker=? AND status='ATIVA'",
            (ticker,)
        )
        # Activate this one
        conn.execute(
            "UPDATE theses SET status='ATIVA' WHERE id=?",
            (thesis_id,)
        )
        new = {**old, "status": "ATIVA"}
        audit(conn, "thesis", thesis_id, ticker, "APPROVE", user, old, new)
    return True


def update_thesis_content(thesis_id, content, user="admin"):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
        if not row:
            return False
        old = dict(row)
        conn.execute("UPDATE theses SET content=? WHERE id=?", (content, thesis_id))
        new = {**old, "content": content}
        audit(conn, "thesis", thesis_id, old["ticker"], "UPDATE", user, old, new)
        _fts_upsert(conn, old["ticker"], "thesis", thesis_id, content)
    return True


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def get_notes(ticker):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE ticker=? ORDER BY created_at DESC",
            (ticker,)
        ).fetchall()
    return [dict(r) for r in rows]


def create_note(ticker, content, note_type="OBSERVACAO", user="admin"):
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO notes (ticker, content, note_type, created_by, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker, content, note_type, user, now, now)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "content": content,
               "note_type": note_type, "created_by": user, "created_at": now}
        audit(conn, "note", new_id, ticker, "CREATE", user, None, new)
        _fts_upsert(conn, ticker, "note", new_id, content)
    return new_id


def update_note(note_id, content, note_type=None, user="admin"):
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            return False
        old = dict(row)
        nt = note_type or old["note_type"]
        conn.execute(
            "UPDATE notes SET content=?, note_type=?, updated_at=? WHERE id=?",
            (content, nt, now, note_id)
        )
        new = {**old, "content": content, "note_type": nt, "updated_at": now}
        audit(conn, "note", note_id, old["ticker"], "UPDATE", user, old, new)
        _fts_upsert(conn, old["ticker"], "note", note_id, content)
    return True


def delete_note(note_id, user="admin"):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            return False
        old = dict(row)
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
        audit(conn, "note", note_id, old["ticker"], "DELETE", user, old, None)
        _fts_delete(conn, "note", note_id)
    return True


# ---------------------------------------------------------------------------
# Valuations
# ---------------------------------------------------------------------------

def get_valuations(ticker):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM valuations WHERE ticker=? ORDER BY created_at DESC",
            (ticker,)
        ).fetchall()
    return [dict(r) for r in rows]


def create_valuation(ticker, target_price, methodology, upside_pct=None,
                     assumptions=None, notes=None, user="admin"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO valuations (ticker, target_price, methodology, upside_pct, assumptions, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, target_price, methodology, upside_pct,
             json.dumps(assumptions, ensure_ascii=False) if assumptions else None,
             notes, user)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "target_price": target_price,
               "methodology": methodology, "upside_pct": upside_pct,
               "assumptions": assumptions, "notes": notes, "created_by": user}
        audit(conn, "valuation", new_id, ticker, "CREATE", user, None, new)
    return new_id


def delete_valuation(valuation_id, user="admin"):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM valuations WHERE id=?", (valuation_id,)).fetchone()
        if not row:
            return False
        old = dict(row)
        conn.execute("DELETE FROM valuations WHERE id=?", (valuation_id,))
        audit(conn, "valuation", valuation_id, old["ticker"], "DELETE", user, old, None)
    return True


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------

def get_filings(ticker=None, review_status=None, limit=100):
    wheres = []
    params = []
    if ticker:
        wheres.append("ticker=?")
        params.append(ticker)
    if review_status:
        wheres.append("review_status=?")
        params.append(review_status)
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM filings {where_sql} ORDER BY filing_date DESC, processed_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]


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


def review_filing(filing_id, action, user="admin"):
    """action: APPROVE or REJECT"""
    status_map = {"APPROVE": "APROVADO", "REJECT": "REJEITADO"}
    new_status = status_map.get(action)
    if not new_status:
        return False
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM filings WHERE id=?", (filing_id,)).fetchone()
        if not row:
            return False
        old = dict(row)
        conn.execute(
            "UPDATE filings SET review_status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
            (new_status, user, now, filing_id)
        )
        new = {**old, "review_status": new_status, "reviewed_by": user, "reviewed_at": now}
        audit(conn, "filing", filing_id, old["ticker"], action, user, old, new)
        if new_status == "APROVADO":
            text = f"{old.get('title','')} {old.get('summary','')}"
            _fts_upsert(conn, old["ticker"], "filing", filing_id, text)
    return True


# ---------------------------------------------------------------------------
# News items
# ---------------------------------------------------------------------------

def get_news(ticker=None, review_status=None, limit=100):
    wheres = []
    params = []
    if ticker:
        wheres.append("ticker=?")
        params.append(ticker)
    if review_status:
        wheres.append("review_status=?")
        params.append(review_status)
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM news_items {where_sql} ORDER BY published_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]


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


def review_news(news_id, action, user="admin"):
    """action: APPROVE or REJECT"""
    status_map = {"APPROVE": "APROVADO", "REJECT": "REJEITADO"}
    new_status = status_map.get(action)
    if not new_status:
        return False
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM news_items WHERE id=?", (news_id,)).fetchone()
        if not row:
            return False
        old = dict(row)
        conn.execute(
            "UPDATE news_items SET review_status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
            (new_status, user, now, news_id)
        )
        new = {**old, "review_status": new_status, "reviewed_by": user, "reviewed_at": now}
        audit(conn, "news", news_id, old["ticker"], action, user, old, new)
        if new_status == "APROVADO":
            text = f"{old.get('title','')} {old.get('summary','')}"
            _fts_upsert(conn, old.get("ticker",""), "news", news_id, text)
    return True


# ---------------------------------------------------------------------------
# Audit log queries
# ---------------------------------------------------------------------------

def get_audit_log(ticker=None, entity_type=None, limit=200):
    wheres = []
    params = []
    if ticker:
        wheres.append("ticker=?")
        params.append(ticker)
    if entity_type:
        wheres.append("entity_type=?")
        params.append(entity_type)
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM audit_log {where_sql} ORDER BY timestamp DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]


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

def _sanitize_fts_query(query):
    """Sanitize a natural language query for FTS5 MATCH.

    FTS5 treats *, ", (, ), ^, - as operators. Natural language questions
    also contain ?, °, º and other chars that break the query parser.
    We extract only alphanumeric tokens (unicode-aware) of length >= 3.
    """
    clean = re.sub(r'[^\w\s]', ' ', query, flags=re.UNICODE)
    tokens = [t for t in clean.split() if len(t) >= 3]
    return ' '.join(tokens) if tokens else 'a'


def fts_search_context(query, ticker=None, limit=5):
    """FTS5 search returning full text for RAG context."""
    fts_query = _sanitize_fts_query(query)
    try:
        with get_conn() as conn:
            if ticker:
                rows = conn.execute(
                    "SELECT ticker, content_type, content_id, text, "
                    "snippet(research_fts,3,'','','…',40) AS snippet "
                    "FROM research_fts WHERE research_fts MATCH ? AND ticker=? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, ticker, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ticker, content_type, content_id, text, "
                    "snippet(research_fts,3,'','','…',40) AS snippet "
                    "FROM research_fts WHERE research_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, limit)
                ).fetchall()
        return [
            {"type": r["content_type"], "id": r["content_id"],
             "ticker": r["ticker"], "snippet": r["snippet"], "text": r["text"]}
            for r in rows
        ]
    except sqlite3.OperationalError as exc:
        logger.warning("fts_search_context error (query=%r): %s", fts_query, exc)
        return []


def build_rag_context(question, ticker=None):
    """
    Build RAG context chunks for a Q&A question.

    Returns list of dicts: {type, id, ticker, snippet, text}
    """
    seen = set()
    chunks = []

    def _add(chunk):
        key = (chunk["type"], str(chunk["id"]))
        if key not in seen:
            seen.add(key)
            chunks.append(chunk)

    # 1. FTS5 full-text search
    for c in fts_search_context(question, ticker=ticker, limit=5):
        _add(c)

    if ticker:
        # 2. Active thesis
        thesis = get_active_thesis(ticker)
        if thesis:
            _add({
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
            _add({
                "type": "valuation",
                "id": v["id"],
                "ticker": ticker,
                "snippet": text[:200],
                "text": text,
            })

        # 4. Recent approved filings (always included — FTS may miss keyword mismatches)
        for f in get_filings(ticker=ticker, review_status="APROVADO")[:4]:
            _add({
                "type": "filing",
                "id": f["id"],
                "ticker": ticker,
                "snippet": (f.get("title") or "")[:200],
                "text": f"{f.get('title', '')} {f.get('summary') or ''}".strip(),
            })

        # 5. Recent approved news
        for n in get_news(ticker=ticker, review_status="APROVADO")[:3]:
            _add({
                "type": "news",
                "id": n["id"],
                "ticker": ticker,
                "snippet": (n.get("title") or "")[:200],
                "text": f"{n.get('title', '')} {n.get('summary') or ''}".strip(),
            })

    return chunks


# ---------------------------------------------------------------------------
# Pending counts
# ---------------------------------------------------------------------------

def get_pending_counts():
    with get_conn() as conn:
        filings_pending = conn.execute(
            "SELECT COUNT(*) AS n FROM filings WHERE review_status='PENDENTE'"
        ).fetchone()["n"]
        news_pending = conn.execute(
            "SELECT COUNT(*) AS n FROM news_items WHERE review_status='PENDENTE'"
        ).fetchone()["n"]
        theses_pending = conn.execute(
            "SELECT COUNT(*) AS n FROM theses WHERE status='RASCUNHO'"
        ).fetchone()["n"]
    return {
        "filings": filings_pending,
        "news":    news_pending,
        "theses":  theses_pending,
        "total":   filings_pending + news_pending + theses_pending,
    }


def get_pending_by_ticker():
    """Returns {ticker: count} for companies with pending items."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ticker, COUNT(*) AS n FROM (
                SELECT ticker FROM filings WHERE review_status='PENDENTE'
                UNION ALL
                SELECT ticker FROM news_items WHERE review_status='PENDENTE' AND ticker IS NOT NULL
                UNION ALL
                SELECT ticker FROM theses WHERE status='RASCUNHO'
            ) GROUP BY ticker
        """).fetchall()
    return {r["ticker"]: r["n"] for r in rows}


def get_thesis_status_by_ticker():
    """Returns {ticker: {'has_active': bool, 'has_draft': bool}} for all companies."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ticker,
                   MAX(CASE WHEN status='ATIVA' THEN 1 ELSE 0 END) AS has_active,
                   MAX(CASE WHEN status='RASCUNHO' THEN 1 ELSE 0 END) AS has_draft
            FROM theses
            GROUP BY ticker
        """).fetchall()
    return {r["ticker"]: {"has_active": bool(r["has_active"]), "has_draft": bool(r["has_draft"])} for r in rows}


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------

def export_company_markdown(ticker):
    """Generate a full markdown document for a company's research knowledge base."""
    company = get_company(ticker)
    if not company:
        return None

    lines = []
    lines.append(f"# {ticker} — Research Knowledge Base")
    lines.append(f"**Empresa:** {company.get('name') or ticker}")
    lines.append(f"**Mercado:** {company.get('market', 'BR')}  |  "
                 f"**Status:** {company.get('status','—')}  |  "
                 f"**Setor:** {company.get('sector') or '—'}")
    lines.append(f"*Exportado em: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append("")

    # Active thesis
    thesis = get_active_thesis(ticker)
    lines.append("---")
    lines.append("## TESE DE INVESTIMENTO")
    if thesis:
        lines.append(f"*Versão {thesis['version']} · por {thesis['created_by']} · {thesis['created_at'][:10]}*")
        lines.append("")
        lines.append(thesis["content"])
    else:
        lines.append("*Nenhuma tese ativa.*")
    lines.append("")

    # Valuations
    vals = get_valuations(ticker)
    if vals:
        lines.append("---")
        lines.append("## VALUATION")
        for v in vals:
            lines.append(f"### {v.get('methodology','—')} — Preço Alvo: R${v.get('target_price','—')}")
            if v.get("upside_pct") is not None:
                lines.append(f"**Upside:** {v['upside_pct']:.1f}%")
            if v.get("notes"):
                lines.append(f"\n{v['notes']}")
            if v.get("assumptions"):
                try:
                    assump = json.loads(v["assumptions"])
                    if assump:
                        lines.append("\n**Premissas:**")
                        if isinstance(assump, dict):
                            for k, val in assump.items():
                                lines.append(f"- {k}: {val}")
                        else:
                            lines.append(str(assump))
                except Exception:
                    pass
            lines.append(f"*por {v['created_by']} · {v['created_at'][:10]}*")
            lines.append("")

    # Approved filings
    filings = get_filings(ticker=ticker, review_status="APROVADO", limit=50)
    if filings:
        lines.append("---")
        lines.append("## FILINGS APROVADOS")
        for f in filings:
            lines.append(f"### [{f.get('source','')}] {f.get('title','')}")
            lines.append(f"**Data:** {f.get('filing_date','—')}  |  **Sentiment:** {f.get('sentiment','—')}")
            if f.get("summary"):
                lines.append(f"\n{f['summary']}")
            if f.get("key_points"):
                try:
                    kp = json.loads(f["key_points"])
                    if kp:
                        lines.append("\n**Pontos-chave:**")
                        for point in kp:
                            lines.append(f"- {point}")
                except Exception:
                    pass
            lines.append("")

    # Approved news
    news = get_news(ticker=ticker, review_status="APROVADO", limit=50)
    if news:
        lines.append("---")
        lines.append("## NOTÍCIAS APROVADAS")
        for n in news:
            lines.append(f"### {n.get('title','')}")
            lines.append(f"**Fonte:** {n.get('source','—')}  |  "
                         f"**Data:** {n.get('published_at','—')[:10] if n.get('published_at') else '—'}  |  "
                         f"**Sentiment:** {n.get('sentiment','—')}")
            if n.get("summary"):
                lines.append(f"\n{n['summary']}")
            if n.get("url"):
                lines.append(f"\n[Link]({n['url']})")
            lines.append("")

    # Notes
    notes = get_notes(ticker)
    if notes:
        lines.append("---")
        lines.append("## NOTAS DA EQUIPE")
        for nt in notes:
            lines.append(f"### [{nt.get('note_type','—')}] {nt['created_at'][:10]} — {nt['created_by']}")
            lines.append(nt["content"])
            lines.append("")

    # Audit log
    audit_entries = get_audit_log(ticker=ticker, limit=100)
    if audit_entries:
        lines.append("---")
        lines.append("## HISTÓRICO DE AUDITORIA")
        for e in audit_entries:
            lines.append(f"- `{e['timestamp'][:16]}` **{e['action']}** {e['entity_type']} "
                         f"— por {e['user']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sync from portfolio/watchlist
# ---------------------------------------------------------------------------

def sync_from_portfolio(portfolio_path, watchlist_path, user="system"):
    """
    Populate/update companies table from portfolio.json and watchlist.json.
    Called at app startup and on demand.
    """
    import json as _json

    # Portfolio → INVESTIDO
    if os.path.exists(portfolio_path):
        with open(portfolio_path, "r", encoding="utf-8") as f:
            portfolio = _json.load(f)
        for pos in portfolio.get("positions", []):
            ticker = pos.get("ticker")
            if not ticker:
                continue
            yahoo = pos.get("yahoo_ticker", "")
            market = "US" if not yahoo.endswith(".SA") else "BR"
            upsert_company(ticker, name=None, market=market, status="INVESTIDO",
                           sector=pos.get("categoria"), user=user)

    # Watchlist → WATCHLIST
    if os.path.exists(watchlist_path):
        with open(watchlist_path, "r", encoding="utf-8") as f:
            watchlist = _json.load(f)
        for item in watchlist.get("items", []):
            ticker = item.get("ticker")
            if not ticker:
                continue
            yahoo = item.get("yahoo_ticker", "")
            market = "US" if not yahoo.endswith(".SA") else "BR"
            # Only set to WATCHLIST if not already INVESTIDO
            with get_conn() as conn:
                existing = conn.execute(
                    "SELECT status FROM companies WHERE ticker=?", (ticker,)
                ).fetchone()
            if existing and existing["status"] == "INVESTIDO":
                continue
            upsert_company(ticker, name=None, market=market, status="WATCHLIST",
                           sector=item.get("categoria"), user=user)


# ---------------------------------------------------------------------------
# Portfólio Global — Tese versionada
# ---------------------------------------------------------------------------

PORTFOLIO_THESIS_SEED = """## Posicionamento macro
_Visão atual do gestor sobre o cenário macro e como o portfólio está posicionado._

## Vieses atuais
_Inclinações setoriais, beta-alvo, % em caixa, tilts de fator (value/quality/size)._

## Regras de alocação
- Concentração máxima por posição: __%
- Concentração máxima por setor: __%
- Caixa-alvo: entre __% e __%

## Riscos monitorados
_Eventos macro/setoriais/idiossincráticos que estão sendo acompanhados._
"""


def get_portfolio_theses():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_thesis ORDER BY version DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_active_portfolio_thesis():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_thesis WHERE status='ATIVA' "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_portfolio_thesis(version_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_thesis WHERE id=?", (version_id,)
        ).fetchone()
    return dict(row) if row else None


def create_portfolio_thesis(title, body_md, user="admin"):
    """Cria nova versão (RASCUNHO). Retorna id."""
    with get_conn() as conn:
        last = conn.execute(
            "SELECT COALESCE(MAX(version),0) AS v FROM portfolio_thesis"
        ).fetchone()["v"]
        version = last + 1
        conn.execute(
            "INSERT INTO portfolio_thesis (title, body_md, version, status, created_by) "
            "VALUES (?, ?, ?, 'RASCUNHO', ?)",
            (title, body_md, version, user)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "title": title, "body_md": body_md,
               "version": version, "status": "RASCUNHO", "created_by": user}
        audit(conn, "portfolio_thesis", new_id, None, "CREATE", user, None, new)
    return new_id


def update_portfolio_thesis(version_id, title=None, body_md=None, user="admin"):
    """Atualiza conteúdo de uma versão (não cria nova). Para RASCUNHO."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_thesis WHERE id=?", (version_id,)
        ).fetchone()
        if not row:
            return False
        old = dict(row)
        new_title = title if title is not None else old["title"]
        new_body  = body_md if body_md is not None else old["body_md"]
        conn.execute(
            "UPDATE portfolio_thesis SET title=?, body_md=? WHERE id=?",
            (new_title, new_body, version_id)
        )
        new = {**old, "title": new_title, "body_md": new_body}
        audit(conn, "portfolio_thesis", version_id, None, "UPDATE", user, old, new)
    return True


def approve_portfolio_thesis(version_id, user="admin"):
    """Publica esta versão; arquiva a ATIVA atual."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_thesis WHERE id=?", (version_id,)
        ).fetchone()
        if not row:
            return False
        old = dict(row)
        conn.execute(
            "UPDATE portfolio_thesis SET status='ARQUIVADA' WHERE status='ATIVA'"
        )
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "UPDATE portfolio_thesis SET status='ATIVA', published_at=? WHERE id=?",
            (now, version_id)
        )
        new = {**old, "status": "ATIVA", "published_at": now}
        audit(conn, "portfolio_thesis", version_id, None, "APPROVE", user, old, new)
    return True


def ensure_portfolio_thesis_seed(user="system"):
    """Cria a versão 1 (publicada) com o template inicial se não existir nenhuma."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) AS c FROM portfolio_thesis"
        ).fetchone()["c"]
    if existing > 0:
        return None
    new_id = create_portfolio_thesis(
        "Tese de Portfólio — v1", PORTFOLIO_THESIS_SEED, user=user
    )
    approve_portfolio_thesis(new_id, user=user)
    return new_id


# ---------------------------------------------------------------------------
# Portfólio Global — Decisões (append-only)
# ---------------------------------------------------------------------------

_DECISION_TIPOS    = {"DECISAO", "REGRA", "NOTA"}
_DECISION_SUBTIPOS = {"COMPRA", "VENDA", "AUMENTO", "REDUCAO", "MANUTENCAO"}


def list_portfolio_decisions(ticker=None, tipo=None, date_from=None,
                             date_to=None, author=None, include_archived=False,
                             limit=200):
    wheres, params = [], []
    if not include_archived:
        wheres.append("status='ativa'")
    if ticker:
        # tickers_json é JSON array; busca substring com aspas para evitar match parcial
        wheres.append("tickers_json LIKE ?")
        params.append(f'%"{ticker.upper()}"%')
    if tipo:
        wheres.append("tipo=?")
        params.append(tipo.upper())
    if date_from:
        wheres.append("date>=?")
        params.append(date_from)
    if date_to:
        wheres.append("date<=?")
        params.append(date_to)
    if author:
        wheres.append("author=?")
        params.append(author)
    sql = "SELECT * FROM portfolio_decisions"
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("tickers_json"):
            try:    d["tickers"] = json.loads(d["tickers_json"])
            except Exception: d["tickers"] = []
        else:
            d["tickers"] = []
        if d.get("snapshot_json"):
            try:    d["snapshot"] = json.loads(d["snapshot_json"])
            except Exception: d["snapshot"] = None
        else:
            d["snapshot"] = None
        out.append(d)
    return out


def create_portfolio_decision(date, tipo, titulo, rationale_md,
                              subtipo=None, tickers=None, peso_antes=None,
                              peso_depois=None, snapshot=None, author="admin"):
    tipo = (tipo or "DECISAO").upper()
    if tipo not in _DECISION_TIPOS:
        raise ValueError(f"tipo inválido: {tipo}")
    if subtipo:
        subtipo = subtipo.upper()
        if subtipo not in _DECISION_SUBTIPOS:
            raise ValueError(f"subtipo inválido: {subtipo}")
    tickers_norm = [t.upper().strip() for t in (tickers or []) if t and t.strip()]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO portfolio_decisions "
            "(date, tipo, subtipo, titulo, rationale_md, tickers_json, "
            " peso_antes, peso_depois, snapshot_json, author) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date, tipo, subtipo, titulo, rationale_md or "",
             json.dumps(tickers_norm, ensure_ascii=False) if tickers_norm else None,
             peso_antes, peso_depois,
             json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
             author)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "date": date, "tipo": tipo, "subtipo": subtipo,
               "titulo": titulo, "tickers": tickers_norm,
               "peso_antes": peso_antes, "peso_depois": peso_depois,
               "author": author}
        audit(conn, "portfolio_decision", new_id, None, "CREATE", author, None, new)
    return new_id


def archive_portfolio_decision(decision_id, user="admin"):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_decisions WHERE id=?", (decision_id,)
        ).fetchone()
        if not row:
            return False
        old = dict(row)
        if old["status"] == "arquivada":
            return True
        conn.execute(
            "UPDATE portfolio_decisions SET status='arquivada' WHERE id=?",
            (decision_id,)
        )
        new = {**old, "status": "arquivada"}
        audit(conn, "portfolio_decision", decision_id, None, "UPDATE", user, old, new)
    return True


def get_portfolio_audit_log(limit=200):
    """Audit entries do portfólio global (tese + decisões)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log "
            "WHERE entity_type IN ('portfolio_thesis','portfolio_decision') "
            "ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def count_portfolio_decisions_year(year):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM portfolio_decisions "
            "WHERE status='ativa' AND substr(date,1,4)=?",
            (str(year),)
        ).fetchone()
    return row["c"] if row else 0


def count_portfolio_rules_active():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM portfolio_decisions "
            "WHERE status='ativa' AND tipo='REGRA'"
        ).fetchone()
    return row["c"] if row else 0
