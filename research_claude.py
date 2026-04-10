"""
research_claude.py — Cliente Claude API para processamento de documentos de research.

Funções exportadas:
  process_filing(text, ticker, doc_type, doc_title) -> dict
  process_news(text, ticker, headline, source)       -> dict
  process_manual(text, ticker)                       -> dict
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_FILING_SYSTEM = """\
Você é um analista de research financeiro experiente, especializado em análise \
de filings regulatórios (CVM/SEC) para um fundo de ações brasileiro.
Sua função é extrair informações relevantes de documentos regulatórios e \
estruturá-las em formato JSON para alimentar a base de conhecimento do fundo."""

_FILING_USER = """\
Analise o seguinte documento regulatório e retorne um JSON com exatamente estas chaves:

{{
  "summary": "<resumo em 1 parágrafo conciso, em português>",
  "key_points": ["<ponto 1>", "<ponto 2>", "<ponto 3>", "<ponto 4>", "<ponto 5>"],
  "sentiment": "POSITIVO" | "NEUTRO" | "NEGATIVO",
  "relevance": <número inteiro de 0 a 10 indicando relevância para o investidor>,
  "update_thesis": true | false,
  "update_reason": "<motivo pelo qual a tese de investimento deve ser revisada, ou null>"
}}

Contexto:
- Ticker: {ticker}
- Tipo de documento: {doc_type}
- Título: {doc_title}

Documento:
{text}

Responda APENAS com o JSON válido, sem markdown, sem explicações adicionais."""

_NEWS_SYSTEM = """\
Você é um analista de research financeiro que monitora notícias para um fundo de ações. \
Analise notícias e artigos para identificar informações relevantes para posições do fundo."""

_NEWS_USER = """\
Analise a seguinte notícia/artigo e retorne um JSON com exatamente estas chaves:

{{
  "summary": "<resumo em 2-3 frases, em português>",
  "sentiment": "POSITIVO" | "NEUTRO" | "NEGATIVO",
  "relevance": <número inteiro de 0 a 10>,
  "update_thesis": true | false,
  "update_reason": "<motivo de revisão da tese, ou null>"
}}

Contexto:
- Ticker relacionado: {ticker}
- Fonte: {source}
- Manchete: {headline}

Conteúdo:
{text}

Responda APENAS com o JSON válido, sem markdown, sem explicações adicionais."""

_MANUAL_SYSTEM = """\
Você é um analista de research financeiro. Processe o conteúdo colado manualmente \
(artigo Bloomberg, relatório de sell-side, transcrição de call, etc.) e extraia \
informações estruturadas para a base de conhecimento do fundo."""

_MANUAL_USER = """\
Analise o seguinte conteúdo e retorne um JSON com exatamente estas chaves:

{{
  "summary": "<resumo em 1 parágrafo, em português>",
  "key_points": ["<ponto 1>", "<ponto 2>", "<ponto 3>", "<ponto 4>", "<ponto 5>"],
  "sentiment": "POSITIVO" | "NEUTRO" | "NEGATIVO",
  "relevance": <número inteiro de 0 a 10>,
  "update_thesis": true | false,
  "update_reason": "<motivo de revisão da tese, ou null>"
}}

Ticker(s) relacionado(s): {ticker}

Conteúdo:
{text}

Responda APENAS com o JSON válido, sem markdown, sem explicações adicionais."""

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_client():
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada")
    import anthropic
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _call(system_prompt, user_prompt, max_tokens=1024):
    """Call Claude and return the text response."""
    client = _get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


def _parse_json_response(raw):
    """Extract and parse the JSON from Claude's response."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(text)


def _truncate(text, max_chars=12000):
    """Truncate text to fit in context window."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[texto truncado para análise]"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_filing(text, ticker, doc_type="FILING", doc_title=""):
    """
    Process a regulatory filing (CVM/SEC) with Claude.

    Returns dict with: summary, key_points, sentiment, relevance,
                       update_thesis, update_reason
    Returns None on error.
    """
    try:
        prompt = _FILING_USER.format(
            ticker=ticker,
            doc_type=doc_type,
            doc_title=doc_title,
            text=_truncate(text),
        )
        raw = _call(_FILING_SYSTEM, prompt, max_tokens=1024)
        result = _parse_json_response(raw)
        # Normalise
        result.setdefault("key_points", [])
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except Exception as e:
        logger.error("process_filing error [%s]: %s", ticker, e)
        return None


def process_news(text, ticker, headline="", source=""):
    """
    Process a news item with Claude.

    Returns dict with: summary, sentiment, relevance, update_thesis, update_reason
    Returns None on error.
    """
    try:
        prompt = _NEWS_USER.format(
            ticker=ticker,
            source=source,
            headline=headline,
            text=_truncate(text, max_chars=6000),
        )
        raw = _call(_NEWS_SYSTEM, prompt, max_tokens=512)
        result = _parse_json_response(raw)
        result.setdefault("summary", "")
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except Exception as e:
        logger.error("process_news error [%s]: %s", ticker, e)
        return None


def process_manual(text, ticker=""):
    """
    Process manually pasted content (Bloomberg article, sell-side report, etc.).

    Returns dict with: summary, key_points, sentiment, relevance,
                       update_thesis, update_reason
    Returns None on error.
    """
    try:
        prompt = _MANUAL_USER.format(
            ticker=ticker or "não especificado",
            text=_truncate(text, max_chars=12000),
        )
        raw = _call(_MANUAL_SYSTEM, prompt, max_tokens=1024)
        result = _parse_json_response(raw)
        result.setdefault("key_points", [])
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except Exception as e:
        logger.error("process_manual error [%s]: %s", ticker, e)
        return None


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
