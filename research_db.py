"""
research_db.py — Camada de acesso ao SQLite para a aba RESEARCH (212).

Schema: companies, theses, filings, news_items, notes, valuations, audit_log, research_fts (FTS5).
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "data", "research.db")

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


def create_thesis(ticker, content, user="admin"):
    """Creates a new RASCUNHO thesis. Returns new id."""
    with get_conn() as conn:
        # Next version number
        last = conn.execute(
            "SELECT COALESCE(MAX(version),0) AS v FROM theses WHERE ticker=?", (ticker,)
        ).fetchone()["v"]
        version = last + 1
        conn.execute(
            "INSERT INTO theses (ticker, content, version, status, created_by) VALUES (?, ?, ?, 'RASCUNHO', ?)",
            (ticker, content, version, user)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "content": content, "version": version,
               "status": "RASCUNHO", "created_by": user}
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
                  summary=None, key_points=None, sentiment=None, user="admin"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO filings (ticker, source, type, title, filing_date, raw_url, summary, key_points, sentiment) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, source, type_, title, filing_date, raw_url, summary,
             json.dumps(key_points, ensure_ascii=False) if key_points else None, sentiment)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "source": source, "type": type_,
               "title": title, "filing_date": filing_date, "summary": summary,
               "sentiment": sentiment, "review_status": "PENDENTE"}
        audit(conn, "filing", new_id, ticker, "CREATE", user, None, new)
    return new_id


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
                summary=None, sentiment=None, relevance=0, sector=None, user="admin"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO news_items (ticker, sector, title, source, url, published_at, summary, sentiment, relevance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, sector, title, source, url, published_at, summary, sentiment, relevance)
        )
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        new = {"id": new_id, "ticker": ticker, "title": title, "source": source,
               "review_status": "PENDENTE"}
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
