"""
research_pipeline.py — Pipeline de ingestão para a aba RESEARCH (212).

Fetchers:
  CVMFetcher   — Fatos Relevantes, ITR, DFP via dados.cvm.gov.br (tickers BR)
  SECFetcher   — 8-K, 10-K, 10-Q via EDGAR (tickers US / BDRs)
  RSSFetcher   — Notícias via feedparser + yfinance (todos os tickers)
  ManualIngestor — Processamento de artigos colados manualmente

PipelineScheduler — Background thread que coordena os fetchers a cada N horas.

Mapeamento CNPJ: data/ticker_cnpj.json  (editável pelo admin)
"""

import csv
import io
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

import research_db as _rdb
import research_claude as _claude

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
TICKER_CNPJ_FILE  = os.path.join(DATA_DIR, "ticker_cnpj.json")
EDGAR_TICKERS_CACHE = os.path.join(DATA_DIR, "edgar_company_tickers.json")

# ---------------------------------------------------------------------------
# BDR underlying mapping  (ticker BR sem .SA → ticker US)
# ---------------------------------------------------------------------------

BDR_UNDERLYING = {
    "MUTC34":  "MU",
    "NVDC34":  "NVDA",
    "A1MD34":  "AMD",
    "MSFT34":  "MSFT",
    "GOGL34":  "GOOGL",
    "AAPL34":  "AAPL",
    "AMZO34":  "AMZN",
    "META34":  "META",
    "M1TA34":  "META",
    "TSLA34":  "TSLA",
    "MELI34":  "MELI",
    "INBR32":  "INTR",   # Inter&Co Inc. (Nasdaq: INTR)
}

# ---------------------------------------------------------------------------
# CNPJ helpers
# ---------------------------------------------------------------------------

def _load_cnpj_map():
    """Load ticker→CNPJ mapping from JSON. Returns dict."""
    if not os.path.exists(TICKER_CNPJ_FILE):
        return {}
    try:
        with open(TICKER_CNPJ_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("load_cnpj_map: %s", e)
        return {}


def _save_cnpj_map(mapping):
    with open(TICKER_CNPJ_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def get_cnpj_map():
    return _load_cnpj_map()


def upsert_cnpj(ticker, cnpj):
    m = _load_cnpj_map()
    m[ticker.upper()] = cnpj
    _save_cnpj_map(m)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "harbour-fia-tracker/1.0 research-pipeline (contact: admin@harbourcapital.com.br)"
})

def _get(url, timeout=20, **kwargs):
    try:
        r = _SESSION.get(url, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        logger.warning("HTTP GET %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# CVMFetcher
# ---------------------------------------------------------------------------

CVM_DOC_TYPES = {
    "FATO_RELEVANTE": "FATO_RELEVANTE",
    "ITR":            "ITR",
    "DFP":            "DFP",
    "FRE":            "FRE",
}

CVM_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{doc_type}/DADOS/{filename}"

def _cvm_csv_filename(doc_type, year):
    """Return the expected CSV filename for a CVM doc type and year."""
    key = {
        "FATO_RELEVANTE": "fato_relevante_cia_aberta",
        "ITR":            "itr_cia_aberta_con_demonstracao_financeira",
        "DFP":            "dfp_cia_aberta_con_demonstracao_financeira",
        "FRE":            "fre_cia_aberta_geral",
    }.get(doc_type, doc_type.lower() + "_cia_aberta")
    return f"{key}_{year}.csv"


def _cnpj_normalise(cnpj):
    """Strip formatting from CNPJ for comparison: '09.449.019/0001-55' → '09449019000155'."""
    return "".join(c for c in cnpj if c.isdigit())


class CVMFetcher:
    """Fetch new CVM filings for BR tickers using dados.cvm.gov.br open data."""

    def fetch_all(self, tickers, days_back=30):
        """
        Fetch recent CVM documents for the given tickers.
        Returns total count of new items inserted.
        """
        cnpj_map = _load_cnpj_map()
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        total = 0

        for ticker in tickers:
            # Skip BDRs — they file with SEC, not CVM
            if ticker in BDR_UNDERLYING:
                continue
            cnpj = cnpj_map.get(ticker.upper())
            if not cnpj:
                logger.info("CVMFetcher: sem CNPJ para %s — pulando", ticker)
                continue
            total += self._fetch_ticker(ticker, cnpj, since)
        return total

    def _fetch_ticker(self, ticker, cnpj, since):
        """Fetch Fatos Relevantes for a single ticker. Returns count of new items."""
        cnpj_raw = _cnpj_normalise(cnpj)
        count = 0
        years = {datetime.now().year, datetime.now().year - 1}

        for year in sorted(years, reverse=True):
            count += self._fetch_doc_type(ticker, cnpj_raw, "FATO_RELEVANTE", year, since)

        return count

    def _fetch_doc_type(self, ticker, cnpj_raw, doc_type, year, since):
        filename = _cvm_csv_filename(doc_type, year)
        url = CVM_BASE.format(doc_type=doc_type, filename=filename)
        r = _get(url, timeout=30)
        if not r:
            return 0

        count = 0
        try:
            # CVM CSVs use ';' separator and latin-1 encoding
            text = r.content.decode("latin-1", errors="replace")
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
            for row in reader:
                row_cnpj = _cnpj_normalise(row.get("CNPJ_CIA", ""))
                if row_cnpj != cnpj_raw:
                    continue
                dt_receb = (row.get("DT_RECEB") or row.get("DT_REFER") or "")[:10]
                if dt_receb < since:
                    continue
                count += self._ingest_row(ticker, doc_type, row)
        except Exception as e:
            logger.error("CVMFetcher._fetch_doc_type [%s/%s]: %s", ticker, doc_type, e)

        return count

    def _ingest_row(self, ticker, doc_type, row):
        """Insert a CVM row as a filing (PENDENTE) if not already present."""
        link = row.get("LINK_DOC", "")
        title = (
            row.get("ASSUNTO")
            or row.get("DSCR_TIPO_DOC")
            or row.get("CATEGORIA")
            or doc_type
        )
        filing_date = (row.get("DT_REFER") or row.get("DT_RECEB") or "")[:10]

        # Deduplicate by URL
        existing = _rdb.get_filings(ticker=ticker, review_status=None)
        for f in existing:
            if f.get("raw_url") == link:
                return 0

        # Try to extract text for Claude processing
        text = self._extract_text(link) or title
        analysis = _claude.process_filing(
            text, ticker=ticker, doc_type=doc_type, doc_title=title
        ) if _claude.ANTHROPIC_API_KEY else None

        _rdb.create_filing(
            ticker=ticker,
            source="CVM",
            type_=doc_type,
            title=title,
            filing_date=filing_date,
            raw_url=link,
            summary=analysis["summary"] if analysis else None,
            key_points=analysis["key_points"] if analysis else None,
            sentiment=analysis["sentiment"] if analysis else None,
            user="pipeline",
        )
        logger.info("CVMFetcher: novo filing %s [%s] %s", ticker, doc_type, title[:60])
        return 1

    def _extract_text(self, url):
        """Attempt to extract text from a CVM document URL (best-effort)."""
        if not url:
            return None
        try:
            r = _get(url, timeout=20)
            if not r:
                return None
            ct = r.headers.get("content-type", "")
            if "pdf" in ct.lower():
                # Basic PDF text extraction using pdfminer if available, else skip
                try:
                    from pdfminer.high_level import extract_text as pdf_extract
                    return pdf_extract(io.BytesIO(r.content))[:15000]
                except ImportError:
                    return None
            # HTML/text
            text = r.text
            # Strip HTML tags naively
            import re
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s{3,}", "\n", text)
            return text[:15000]
        except Exception as e:
            logger.warning("extract_text %s: %s", url, e)
            return None


# ---------------------------------------------------------------------------
# SECFetcher
# ---------------------------------------------------------------------------

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/full-index/"

_edgar_cik_cache = {}   # ticker_upper → padded CIK string
_edgar_cache_loaded = False
_edgar_cache_lock = threading.Lock()

def _load_edgar_cik_cache():
    """Load ticker→CIK mapping (downloads once and caches to disk)."""
    global _edgar_cik_cache, _edgar_cache_loaded
    with _edgar_cache_lock:
        if _edgar_cache_loaded:
            return

        # Try disk cache first (valid for 7 days)
        if os.path.exists(EDGAR_TICKERS_CACHE):
            try:
                mtime = os.path.getmtime(EDGAR_TICKERS_CACHE)
                if time.time() - mtime < 7 * 86400:
                    with open(EDGAR_TICKERS_CACHE, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    _edgar_cik_cache = {v["ticker"].upper(): str(v["cik_str"]).zfill(10)
                                        for v in raw.values()}
                    _edgar_cache_loaded = True
                    return
            except Exception:
                pass

        # Download from SEC
        r = _get(EDGAR_COMPANY_TICKERS_URL, timeout=30)
        if r:
            try:
                raw = r.json()
                _edgar_cik_cache = {v["ticker"].upper(): str(v["cik_str"]).zfill(10)
                                    for v in raw.values()}
                with open(EDGAR_TICKERS_CACHE, "w", encoding="utf-8") as f:
                    json.dump(raw, f)
                _edgar_cache_loaded = True
            except Exception as e:
                logger.error("_load_edgar_cik_cache: %s", e)


class SECFetcher:
    """Fetch recent SEC filings for US tickers and BDRs via EDGAR."""

    FORMS = ("8-K", "10-K", "10-Q")

    def fetch_all(self, tickers, days_back=30):
        _load_edgar_cik_cache()
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        total = 0

        for ticker in tickers:
            us_ticker = BDR_UNDERLYING.get(ticker, ticker)
            # Only process US tickers and known BDRs
            if not (ticker in BDR_UNDERLYING or not ticker.endswith(("3", "4", "11", "32", "33", "34"))):
                continue
            # For pure BR tickers (not BDRs), skip — CVM handles them
            if ticker not in BDR_UNDERLYING and ticker.endswith(("3", "4", "11")):
                continue
            total += self._fetch_ticker(ticker, us_ticker, since)

        return total

    def _fetch_ticker(self, br_ticker, us_ticker, since):
        cik = _edgar_cik_cache.get(us_ticker.upper())
        if not cik:
            logger.info("SECFetcher: sem CIK para %s (%s) — pulando", br_ticker, us_ticker)
            return 0

        try:
            r = _get(EDGAR_SUBMISSIONS_URL.format(cik=cik), timeout=20)
            if not r:
                return 0
            data = r.json()
        except Exception as e:
            logger.error("SECFetcher._fetch_ticker [%s]: %s", us_ticker, e)
            return 0

        filings = data.get("filings", {}).get("recent", {})
        forms       = filings.get("form", [])
        dates       = filings.get("filingDate", [])
        accessions  = filings.get("accessionNumber", [])
        descriptions = filings.get("primaryDocument", [])

        count = 0
        for form, date, accn, doc in zip(forms, dates, accessions, descriptions):
            if form not in self.FORMS:
                continue
            if date < since:
                break   # results are newest-first; once past window, stop
            count += self._ingest_filing(br_ticker, us_ticker, cik, form, date, accn, doc)

        return count

    def _ingest_filing(self, br_ticker, us_ticker, cik, form, date, accn, primary_doc):
        accn_clean = accn.replace("-", "")
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_clean}/{primary_doc}"
        )
        title = f"{form} — {us_ticker} ({date})"

        # Deduplicate by URL
        existing = _rdb.get_filings(ticker=br_ticker, review_status=None)
        for f in existing:
            if f.get("raw_url") == doc_url:
                return 0

        # Best-effort text extraction (HTML filings)
        text = self._extract_html(doc_url) or title
        analysis = _claude.process_filing(
            text, ticker=br_ticker, doc_type=form, doc_title=title
        ) if _claude.ANTHROPIC_API_KEY else None

        _rdb.create_filing(
            ticker=br_ticker,
            source="SEC",
            type_=form,
            title=title,
            filing_date=date,
            raw_url=doc_url,
            summary=analysis["summary"] if analysis else None,
            key_points=analysis["key_points"] if analysis else None,
            sentiment=analysis["sentiment"] if analysis else None,
            user="pipeline",
        )
        logger.info("SECFetcher: novo filing %s [%s] %s", br_ticker, form, date)
        return 1

    def _extract_html(self, url):
        """Extract text from an EDGAR HTML filing (best-effort)."""
        try:
            r = _get(url, timeout=20)
            if not r:
                return None
            import re
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s{3,}", "\n", text)
            return text[:15000]
        except Exception as e:
            logger.warning("SECFetcher.extract_html %s: %s", url, e)
            return None


# ---------------------------------------------------------------------------
# RSSFetcher
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    ("InfoMoney",    "https://www.infomoney.com.br/feed/"),
    ("Reuters BR",   "https://feeds.reuters.com/reuters/BRbusinessNews"),
    ("Valor Online", "https://www.valor.com.br/rss"),
    ("Exame",        "https://exame.com/feed/"),
    ("E-Investidor", "https://einvestidor.estadao.com.br/feed/"),
]


class RSSFetcher:
    """Fetch news from RSS feeds and yfinance, matching against known tickers."""

    def fetch_all(self, tickers, days_back=3):
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser não instalado — RSS desabilitado")
            return 0

        since_dt = datetime.now(timezone.utc) - timedelta(days=days_back)
        ticker_set = set(t.upper() for t in tickers)
        total = 0

        # RSS feeds
        for source_name, feed_url in RSS_FEEDS:
            total += self._fetch_feed(feed_url, source_name, ticker_set, since_dt)

        # yfinance news for each ticker
        for ticker in tickers:
            total += self._fetch_yfinance(ticker, since_dt)

        return total

    def _fetch_feed(self, feed_url, source_name, ticker_set, since_dt):
        try:
            import feedparser
            feed = feedparser.parse(feed_url)
        except Exception as e:
            logger.warning("RSSFetcher feed %s: %s", feed_url, e)
            return 0

        count = 0
        for entry in feed.entries:
            # Parse published date
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import calendar
                ts = calendar.timegm(entry.published_parsed)
                published = datetime.fromtimestamp(ts, tz=timezone.utc)
            if published and published < since_dt:
                continue

            title = getattr(entry, "title", "")
            summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
            url = getattr(entry, "link", "")

            # Match against tickers
            matched = self._match_tickers(title + " " + summary_raw, ticker_set)
            if not matched:
                continue

            for ticker in matched:
                count += self._ingest_news(
                    ticker=ticker,
                    title=title,
                    source=source_name,
                    url=url,
                    published_dt=published,
                    text=summary_raw,
                )

        return count

    def _fetch_yfinance(self, ticker, since_dt):
        """Use yfinance to get recent news for a ticker."""
        try:
            import yfinance as yf
            # Map BDR to underlying for better news results
            yf_ticker = BDR_UNDERLYING.get(ticker, ticker)
            suffix = "" if yf_ticker == ticker and not ticker.endswith(".SA") else ""
            # For BR tickers, try with .SA suffix
            if ticker not in BDR_UNDERLYING and not ticker.endswith(".SA"):
                yf_ticker_str = ticker + ".SA"
            else:
                yf_ticker_str = yf_ticker

            t = yf.Ticker(yf_ticker_str)
            news_list = t.news or []
        except Exception as e:
            logger.warning("RSSFetcher.yfinance [%s]: %s", ticker, e)
            return 0

        count = 0
        for item in news_list:
            # yfinance news items are dicts with providerPublishTime (unix timestamp)
            pub_ts = item.get("providerPublishTime") or 0
            if pub_ts:
                pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
                if pub_dt < since_dt:
                    continue
                pub_str = pub_dt.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                pub_str = None

            title   = item.get("title", "")
            url     = item.get("link", "")
            source  = item.get("publisher", "yfinance")
            summary_text = title  # yfinance doesn't provide full text

            count += self._ingest_news(
                ticker=ticker,
                title=title,
                source=source,
                url=url,
                published_dt=datetime.fromtimestamp(pub_ts, tz=timezone.utc) if pub_ts else None,
                text=summary_text,
            )

        return count

    def _match_tickers(self, text, ticker_set):
        """Return set of tickers mentioned in text."""
        text_upper = text.upper()
        return {t for t in ticker_set if t in text_upper}

    def _ingest_news(self, ticker, title, source, url, published_dt, text):
        """Insert news item if not already in DB."""
        if not title:
            return 0

        # Deduplicate by URL or title
        if url:
            existing = _rdb.get_news(ticker=ticker)
            for n in existing:
                if n.get("url") == url:
                    return 0

        pub_str = published_dt.strftime("%Y-%m-%dT%H:%M:%S") if published_dt else None

        analysis = _claude.process_news(
            text=text, ticker=ticker, headline=title, source=source
        ) if _claude.ANTHROPIC_API_KEY else None

        _rdb.create_news(
            ticker=ticker,
            title=title,
            source=source,
            url=url,
            published_at=pub_str,
            summary=analysis["summary"] if analysis else None,
            sentiment=analysis["sentiment"] if analysis else None,
            relevance=analysis["relevance"] if analysis else 5,
            user="pipeline",
        )
        return 1


# ---------------------------------------------------------------------------
# ManualIngestor
# ---------------------------------------------------------------------------

class ManualIngestor:
    """Process manually pasted articles/reports via Claude."""

    def ingest(self, ticker, text, source="Manual", user="admin"):
        """
        Process a manually pasted article.
        Returns the created news_id or filing_id, plus the analysis dict.
        """
        if not text or not text.strip():
            return None, None

        analysis = _claude.process_manual(text, ticker=ticker)
        if not analysis:
            return None, None

        # Determine if this is more like a filing or a news item
        # We store manual articles as news_items with source="Manual"
        news_id = _rdb.create_news(
            ticker=ticker,
            title=f"[Manual] {source} — {datetime.utcnow().strftime('%Y-%m-%d')}",
            source=source,
            url=None,
            published_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            summary=analysis.get("summary"),
            sentiment=analysis.get("sentiment"),
            relevance=analysis.get("relevance", 5),
            user=user,
        )
        return news_id, analysis


# ---------------------------------------------------------------------------
# PipelineScheduler
# ---------------------------------------------------------------------------

class PipelineScheduler:
    """
    Background scheduler that runs the full ingestion pipeline every N hours.
    Same pattern as the GitHub sync background thread in app.py.
    """

    def __init__(self, interval_hours=6):
        self.interval_hours = interval_hours
        self._thread = None
        self._stop_event = threading.Event()
        self._status = {
            "running":     False,
            "last_run":    None,
            "last_result": {},
            "next_run":    None,
            "error":       None,
        }
        self._lock = threading.Lock()

    def start(self):
        """Start the background scheduler thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="research-scheduler")
        self._thread.start()
        logger.info("PipelineScheduler iniciado (intervalo: %sh)", self.interval_hours)

    def stop(self):
        """Stop the scheduler."""
        self._stop_event.set()

    def run_now(self, days_back=30):
        """Trigger an immediate run in a background thread."""
        t = threading.Thread(target=self._run_once, args=(days_back,), daemon=True)
        t.start()

    def get_status(self):
        with self._lock:
            return dict(self._status)

    def set_interval(self, hours):
        self.interval_hours = hours

    # ── internal ──────────────────────────────────────────────────────────

    def _loop(self):
        """Main scheduler loop: wait interval, then run."""
        # Set next run immediately so status shows up
        next_run = datetime.now(timezone.utc) + timedelta(hours=self.interval_hours)
        with self._lock:
            self._status["next_run"] = next_run.strftime("%Y-%m-%dT%H:%M:%S")

        while not self._stop_event.wait(self.interval_hours * 3600):
            self._run_once()
            next_run = datetime.now(timezone.utc) + timedelta(hours=self.interval_hours)
            with self._lock:
                self._status["next_run"] = next_run.strftime("%Y-%m-%dT%H:%M:%S")

    def _run_once(self, days_back=30):
        with self._lock:
            if self._status["running"]:
                logger.info("PipelineScheduler: já em execução, pulando")
                return
            self._status["running"] = True
            self._status["error"] = None

        started = datetime.now(timezone.utc)
        result = {"cvm": 0, "sec": 0, "rss": 0, "errors": []}

        try:
            # Get all known tickers from research DB
            companies = _rdb.get_companies()
            tickers = [c["ticker"] for c in companies]

            if not tickers:
                logger.info("PipelineScheduler: nenhum ticker cadastrado")
                return

            # CVM
            try:
                cvm = CVMFetcher()
                result["cvm"] = cvm.fetch_all(tickers, days_back=days_back)
            except Exception as e:
                result["errors"].append(f"CVM: {e}")
                logger.error("PipelineScheduler CVM: %s", e)

            # SEC
            try:
                sec = SECFetcher()
                result["sec"] = sec.fetch_all(tickers, days_back=days_back)
            except Exception as e:
                result["errors"].append(f"SEC: {e}")
                logger.error("PipelineScheduler SEC: %s", e)

            # RSS + yfinance
            try:
                rss = RSSFetcher()
                result["rss"] = rss.fetch_all(tickers, days_back=3)
            except Exception as e:
                result["errors"].append(f"RSS: {e}")
                logger.error("PipelineScheduler RSS: %s", e)

            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            logger.info(
                "PipelineScheduler concluído em %.1fs — CVM:%d SEC:%d RSS:%d erros:%d",
                elapsed, result["cvm"], result["sec"], result["rss"], len(result["errors"])
            )

        except Exception as e:
            result["errors"].append(str(e))
            logger.error("PipelineScheduler._run_once: %s", e)
            with self._lock:
                self._status["error"] = str(e)
        finally:
            with self._lock:
                self._status["running"]     = False
                self._status["last_run"]    = started.strftime("%Y-%m-%dT%H:%M:%S")
                self._status["last_result"] = result


# ---------------------------------------------------------------------------
# Module-level singleton scheduler
# ---------------------------------------------------------------------------

scheduler = PipelineScheduler(interval_hours=6)
manual_ingestor = ManualIngestor()
