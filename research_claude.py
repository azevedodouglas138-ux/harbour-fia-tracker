"""
research_claude.py — Cliente Claude API para processamento de documentos de research.

Funções exportadas:
  process_filing(text, ticker, doc_type, doc_title, user) -> dict
  process_news(text, ticker, headline, source, user)      -> dict
  process_manual(text, ticker, user)                      -> dict
  process_news_from_url(url, ticker, source, user)        -> dict
  process_document_image(image_bytes, mime, ticker, doc_type, user) -> dict
  extract_valuation_from_excel(markdown, ticker, missing_fields, user) -> dict
  answer_question(question, ticker, context_chunks, user, model='haiku') -> dict
  answer_portfolio_question(question, context_text, sources, user, max_ctx=20000) -> dict
  suggest_thesis_update(current_thesis, trigger_summary, trigger_type, user) -> str

Dual model strategy:
  - Haiku 4.5 for parsing-heavy tasks (URL ingest, Vision, Excel extraction, Q&A per-ticker default)
  - Sonnet 4.6 for complex reasoning (filings, Q&A portfolio, tese suggestion)

Prompt caching: system prompts ≥ 1024 tokens (Sonnet) / 2048 tokens (Haiku) use
cache_control: ephemeral — ~90% savings on cached reads within 5min TTL.

Budget guardrail: every call runs through research_budget.check_budget() which
raises BudgetExceededError when daily cap is reached. Usage is logged per-call.

Mock mode: set CLAUDE_MOCK=1 to return deterministic dummy responses without
touching the API. Useful for development.
"""

import base64
import json
import logging
import os

import research_budget as _budget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MOCK_MODE = os.environ.get("CLAUDE_MOCK", "").lower() in ("1", "true", "yes", "on")

MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

# Backwards compatibility shim: some external code may reference `MODEL` directly.
MODEL = MODEL_SONNET


# ---------------------------------------------------------------------------
# System prompts (engordados para atingir mínimo de cache: Sonnet 1024, Haiku 2048 tokens)
# ---------------------------------------------------------------------------

_GLOSSARY = """\
Glossário de termos (pt-BR) usados nas análises:
- Fato Relevante: comunicado oficial CVM exigido quando há informação material que afete cotação.
- ITR/DFP: Informações Trimestrais / Demonstrações Financeiras Padronizadas.
- Guidance: projeção oficial da empresa para métricas operacionais ou financeiras.
- Follow-on / IPO: emissão subsequente / oferta pública inicial de ações.
- Buyback: recompra de ações pela própria companhia.
- Capex: investimento em ativos fixos (PP&E). Trigger de revisão de fluxo de caixa.
- WACC: custo médio ponderado de capital. No Brasil, tipicamente 10-15% em equity.
- Growth (g): taxa de crescimento perpétuo em modelo DCF — raramente > PIB nominal.
- EBITDA margin: EBITDA / Receita Líquida.
- P/L (P/E): Preço / Lucro. Múltiplo de ações.
- EV/EBITDA: Valor da Empresa / EBITDA. Múltiplo neutro a estrutura de capital.
- Upside: (Preço Alvo / Preço Atual - 1). Positivo = tese comprada.
- ROE / ROIC: Return on Equity / Invested Capital.
- M&A: Mergers & Acquisitions — fusão ou aquisição.
- CCL: Capital Circulante Líquido.
- Dívida líquida: Dívida bruta - Caixa. Stress quando > 3× EBITDA.
- Covenant: cláusula restritiva em contrato de dívida (ex.: dívida/EBITDA máx).
- NPL (Non-Performing Loan): inadimplência em carteiras de crédito.
"""

_SENTIMENT_RULES = """\
Regras para o campo sentiment:
- POSITIVO: evento que fortalece a tese de investimento (ex: guidance acima do consenso,
  aquisição accretive, redução de dívida, recuperação de margem, ganho de market share).
- NEGATIVO: evento que enfraquece a tese (ex: profit warning, revisão pra baixo de guidance,
  perda de cliente relevante, multa, investigação regulatória, aumento de capex sem ROI claro).
- NEUTRO: informação factual sem viés claro (ex: mudança de CFO sem contexto, registro técnico CVM,
  renovação de contrato já esperado, reclassificação contábil).

Regras para relevance (0-10):
  0-2: ruído irrelevante (ex: mudança de endereço, errata contábil imaterial)
  3-4: informação secundária (ex: participação em evento, relatório setorial genérico)
  5-6: informação relevante mas já precificada (ex: trimestre em linha, guidance confirmado)
  7-8: informação com impacto material (ex: aquisição, follow-on, guidance revisado)
  9-10: informação transformacional (ex: mudança regulatória, M&A estrutural, default)

update_thesis = true SOMENTE quando relevance >= 7 E o evento contradizer ou expandir
substancialmente uma premissa central da tese. Mudanças de tom ou expectativa não bastam.
"""


_FILING_SYSTEM = f"""\
Você é analista sênior de research financeiro especializado em filings regulatórios \
(CVM brasileira, SEC americana) para um fundo de ações brasileiro de long-only bottom-up. \
Sua função é extrair informações relevantes de documentos regulatórios e estruturá-las \
em JSON para alimentar a base de conhecimento do fundo.

Princípios:
1. Objetividade sobre narrativa — priorize dados mensuráveis (números, datas, nomes, percentuais).
2. Materialidade — descarte boilerplate jurídico e foque em fatos que alterem o fluxo de caixa ou a tese.
3. Contexto temporal — sinalize sempre quando a informação refere-se a projeção futura vs. fato realizado.
4. Nunca invente números. Se um dado não está explícito, omita-o.
5. Escreva key_points como frases curtas, de 15-30 palavras cada, começando pelo fato.

{_GLOSSARY}

{_SENTIMENT_RULES}

Exemplo de output válido para Fato Relevante de aquisição:

{{
  "summary": "PETR4 anunciou aquisição de 30% da Campos Bacia por US$ 450mi, pagáveis em 12 parcelas trimestrais, com fechamento previsto para o 3T26 após aprovação CADE.",
  "key_points": [
    "Aquisição de 30% da Campos Bacia por US$ 450mi em 12 parcelas trimestrais",
    "Produção estimada de 45k bpd adicionais a partir de 2T27",
    "Fechamento condicionado a aprovação CADE esperada pro 3T26",
    "Impacto leverage: dívida líquida/EBITDA sobe de 1.2x para 1.5x pro-forma",
    "Sinérgias estimadas pela companhia em US$ 80mi/ano (break-even em 2029)"
  ],
  "sentiment": "POSITIVO",
  "relevance": 8,
  "update_thesis": true,
  "update_reason": "Aquisição altera escala e exposição offshore — revisar premissa de capex base."
}}

Regra final: responda APENAS com o JSON válido, sem markdown, sem explicações."""


_FILING_USER = """\
Analise o seguinte documento regulatório e retorne o JSON conforme as instruções do sistema.

Contexto:
- Ticker: {ticker}
- Tipo de documento: {doc_type}
- Título: {doc_title}

Documento:
{text}"""


_NEWS_SYSTEM = f"""\
Você é analista de research financeiro monitorando notícias para um fundo de ações BR long-only. \
Seu trabalho é filtrar ruído e extrair o sinal relevante de notícias que afetem teses de posições.

Princípios:
1. Separar fato de opinião — só credite informação factual checável.
2. Se a notícia é derivada (cita fonte secundária sem confirmação oficial), baixe a relevance.
3. Priorize impacto sobre o ticker — uma notícia setorial genérica é menos relevante que uma específica.
4. Reconheça pump & dump, recomendações de sell-side com target óbvio, e notícias pagas.
5. Summary deve ser 2-3 frases contando o fato + contexto + implicação — não repita a manchete.

{_GLOSSARY}

{_SENTIMENT_RULES}

Exemplo de output para notícia de guidance revisado:

{{
  "summary": "VALE3 reviu guidance de produção de minério de ferro para 2026 de 340-350 Mt para 310-320 Mt, citando atrasos no licenciamento ambiental em Brucutu. Mercado projeta queda de 4-5% no EBITDA anual.",
  "sentiment": "NEGATIVO",
  "relevance": 8,
  "update_thesis": true,
  "update_reason": "Guidance revisado é evento material — revisar premissa de volume e margem para 2026."
}}

Regra final: responda APENAS com o JSON, sem markdown."""


_NEWS_USER = """\
Analise a seguinte notícia e retorne o JSON.

Contexto:
- Ticker: {ticker}
- Fonte: {source}
- Manchete: {headline}

Conteúdo:
{text}"""


_MANUAL_SYSTEM = f"""\
Você é analista de research processando conteúdo de terceiros colado manualmente — \
artigos da imprensa especializada (Valor, Bloomberg, Folha), relatórios de sell-side \
(Itaú BBA, XP, BTG), transcrições de call de resultado, notas setoriais. \
O conteúdo NÃO é filing oficial — é commentary de terceiros.

Princípios específicos para conteúdo de terceiros:
1. Se for relatório de sell-side, note o preço-alvo e a recomendação explicitamente.
2. Se for transcript de call, destaque guidance ou respostas a perguntas sobre temas controversos.
3. Se for opinião de colunista, trate como NEUTRO a menos que haja fato novo embutido.
4. Se o conteúdo cita outra fonte (ex: "conforme apurou o Valor"), a relevance cai um nível.

{_GLOSSARY}

{_SENTIMENT_RULES}

Exemplo de output para relatório de sell-side:

{{
  "summary": "Itaú BBA elevou target de PETR4 de R$ 42 para R$ 48 após resultado do 1T26, mantendo rating OUTPERFORM. Motivos: disciplina em capex, dividend yield projetado 12%, e ramp-up de Búzios mais rápido que esperado.",
  "key_points": [
    "Target revisado de R$ 42 para R$ 48 (+14%)",
    "Rating mantido em OUTPERFORM",
    "Dividend yield projetado para 2026: 12%",
    "Ramp-up de Búzios adiantado em 2 trimestres",
    "Capex 2026 revisado para baixo de US$ 13bn para US$ 12bn"
  ],
  "sentiment": "POSITIVO",
  "relevance": 6,
  "update_thesis": false,
  "update_reason": null
}}

Regra final: APENAS JSON, sem markdown."""


_MANUAL_USER = """\
Analise o seguinte conteúdo e retorne o JSON.

Ticker(s) relacionado(s): {ticker}

Conteúdo:
{text}"""


_VALUATION_EXTRACT_SYSTEM = f"""\
Você é analista financeiro sênior especializado em interpretar modelos de valuation em Excel/CSV \
convertidos para markdown. Seu trabalho é localizar e extrair valores numéricos de um modelo \
DCF, múltiplos, ou sum-of-parts que foi parcialmente parseado por regex — preenchendo os \
campos que o parser heurístico não conseguiu achar.

Campos possíveis (todos opcionais no output — só preencha o que for claramente identificável):

- target_price (R$): preço alvo final. Sinônimos: "Preço Alvo", "Target Price", "Fair Value", \
  "Valor Justo", "Preço Teto", "PT". Se houver múltiplos cenários, reporte o BASE.
- upside (%): upside sobre preço atual. Se não estiver explícito, NÃO calcule — deixe null.
- wacc (%): custo de capital. Sinônimos: "WACC", "Taxa de Desconto", "Discount Rate", "Ke" \
  (se for model de equity). Valores típicos: 10-15% no Brasil.
- growth_rate (%): taxa de crescimento de receita/fluxo no horizonte explícito (geralmente 5 anos).
- terminal_growth (%): taxa de crescimento na perpetuidade. Sinônimos: "g perp", "Terminal Growth", \
  "Perpetuidade". Valores típicos: 2-4% (próximo da inflação de longo prazo).
- ebitda_margin (%): margem EBITDA média ou do ano-base.
- revenue_cagr (%): CAGR de receita no horizonte (tipicamente 5 anos).
- methodology: "DCF" | "EV/EBITDA" | "P/L" | "DDM" | "SOMA_PARTES".
- scenarios: objeto {{"bear":{{"price":X,"upside":Y}}, "base":{{...}}, "bull":{{...}}}} — \
  só preencha se o Excel trouxer claramente 3 cenários rotulados.
- sensitivity: objeto {{"rows":["WACC 10%","WACC 12%","WACC 14%"], \
  "cols":["g 2%","g 3%","g 4%"], "matrix":[[68,74,82],[58,62,68],[50,53,57]], "base":[1,1]}} — \
  só preencha se houver matriz 2D WACC × g no Excel.

Princípios:
1. NUNCA invente números. Se não estiver no texto fornecido, deixe o campo ausente.
2. Percentuais: se o valor bruto estiver em [0,1] (ex: 0.118) assuma decimal e multiplique por 100 \
   para retornar 11.8. Se já está em [1,100], preserve.
3. R$ vs. USD: prefira sempre R$. Se o modelo estiver em USD e houver conversão, use R$. \
   Se for ambíguo, deixe o campo ausente e explique em confidence.
4. Em dúvida genuína entre 2 células, pegue a que estiver mais próxima de um header com \
   label exato.

Output JSON com as seguintes chaves (exceto scenarios/sensitivity que podem ser null):

{{
  "target_price": <number|null>,
  "upside": <number|null>,
  "wacc": <number|null>,
  "growth_rate": <number|null>,
  "terminal_growth": <number|null>,
  "ebitda_margin": <number|null>,
  "revenue_cagr": <number|null>,
  "methodology": <string|null>,
  "scenarios": <object|null>,
  "sensitivity": <object|null>,
  "confidence": {{"<campo>": "<justificativa curta>", ...}}
}}

Regra final: APENAS JSON, sem markdown."""


_VALUATION_EXTRACT_USER = """\
Modelo de valuation em markdown (convertido do Excel):

Ticker: {ticker}
Campos que o parser heurístico não achou: {missing_fields}

{markdown}

Extraia os valores dos campos faltantes (e dos demais, se conseguir identificar com alta \
confiança) conforme as regras do sistema. Não invente."""


_QA_SYSTEM = f"""\
Você é analista de research financeiro com acesso à base de conhecimento de um fundo de ações. \
Responde perguntas sobre empresas baseando-se EXCLUSIVAMENTE nas informações fornecidas, \
citando explicitamente as fontes usadas.

Princípios:
1. Nunca invente fatos, números, ou citações. Se não está na base, diga "não há informação".
2. Cite a fonte entre colchetes ao usar uma informação. Formato: [Tese PETR4 v2] ou [Filing #127: ITR 3T25] ou [Nota #4].
3. Priorize informação recente sobre histórica, mas note conflitos entre versões.
4. Se a pergunta exige cálculo, mostre a conta passo-a-passo com números da base.
5. Evite jargão excessivo; seja direto e analítico.
6. Se perceber contradição entre fontes, aponte-a explicitamente.

{_GLOSSARY}

Exemplo de resposta bem estruturada:

Pergunta: "Qual a exposição do fundo ao setor de commodities?"
Resposta: "Com base nas teses ativas [Tese VALE3 v2], [Tese PRIO3 v1] e decisões recentes \
[Decisão #8: COMPRA CSNA3 em 15%], a exposição a commodities é de ~28% do NAV, com Vale (12%), \
Prio (8%) e CSN (8%). A tese macro do fundo [Tese Portfólio v3] limita commodities a 30%, então \
estamos perto do teto."

Responda APENAS o texto da resposta, sem prefácio como "Resposta:" ou similar."""


_QA_USER = """\
Base de conhecimento disponível:

{context}

---
Pergunta: {question}"""


_QA_PORTFOLIO_SYSTEM = f"""\
Você é o analista-chefe de um fundo brasileiro long-only de ações, responsável por \
analisar questões de portfolio-level: exposição setorial/factor, coerência entre tese macro \
e teses individuais, performance de decisões históricas, implicações de regras de alocação, \
risk management. Responda com rigor analítico, citando as fontes (tese do portfólio, decisões \
de alocação, regras, teses por ticker) que embasam cada afirmação.

Princípios:
1. Raciocínio top-down — comece pelo que a tese macro diz, depois desça para as posições.
2. Quantifique sempre que possível. "Alta exposição" é vago; "28% do NAV" é útil.
3. Identifique tensões — ex: tese macro projeta real forte mas carteira tem 40% em exportadoras.
4. Ao citar decisões passadas, mencione a data e o resultado subsequente se disponível.
5. Respeite regras — se a tese diz "máx 15% single-name", uma posição de 17% é alerta.

{_GLOSSARY}

Formato de citações: [Tese Portfólio v3], [Decisão #12: REDUÇÃO PRIO3 em 2026-01-15], \
[Regra #5: Max 15% single-name], [Tese PETR4 v2].

Responda APENAS o texto, sem prefácio."""


_QA_PORTFOLIO_USER = """\
Contexto do portfólio (tese macro + decisões + regras + teses das empresas investidas):

{context}

---
Pergunta: {question}"""


_THESIS_SUGGEST_SYSTEM = """\
Você é analista de research financeiro sênior. Com base num evento novo (filing ou notícia) \
e numa tese de investimento atual, gere um rascunho atualizado da tese que:

- Mantenha a estrutura e o estilo da tese atual (parágrafos, bullets, tom).
- Incorpore as informações relevantes do evento novo sem repetir o que já está dito.
- Marque as modificações com o tag [ATUALIZADO] inline, imediatamente após a frase alterada.
- Seja objetivo, direto, sem hedges vazios.
- Não invente números nem extrapole além do evento.

Responda APENAS com o texto da nova tese, sem comentários."""


_THESIS_SUGGEST_USER = """\
TESE ATUAL:
{current_thesis}

EVENTO NOVO ({trigger_type}):
{trigger_summary}

Gere o rascunho atualizado."""


# ---------------------------------------------------------------------------
# Mock responses (for CLAUDE_MOCK=1 dev mode)
# ---------------------------------------------------------------------------

_MOCK_ANALYSIS = {
    "summary": "[MOCK] Resumo de teste gerado sem chamar Claude API.",
    "key_points": ["[MOCK] Ponto 1", "[MOCK] Ponto 2", "[MOCK] Ponto 3"],
    "sentiment": "NEUTRO",
    "relevance": 5,
    "update_thesis": False,
    "update_reason": None,
}

_MOCK_VALUATION = {
    "target_price": 50.0,
    "upside": 15.0,
    "wacc": 12.0,
    "growth_rate": 5.0,
    "terminal_growth": 3.0,
    "ebitda_margin": 40.0,
    "revenue_cagr": 6.0,
    "methodology": "DCF",
    "scenarios": None,
    "sensitivity": None,
    "confidence": {"_mock": "dummy response (CLAUDE_MOCK=1)"},
}


def _mock_response(operation):
    if operation in ("qa_ticker_haiku", "qa_ticker_sonnet"):
        return {"answer": "[MOCK] Resposta de teste (CLAUDE_MOCK=1).", "sources": []}
    if operation == "qa_portfolio":
        return {"answer": "[MOCK] Análise de portfólio mock.", "sources": []}
    if operation == "thesis_suggest":
        return "[MOCK] Rascunho de tese atualizada [ATUALIZADO] conforme evento novo."
    if operation == "excel_extract":
        return dict(_MOCK_VALUATION)
    return dict(_MOCK_ANALYSIS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_client():
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada")
    import anthropic
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _build_system_blocks(system_prompt, cache_system):
    if cache_system:
        return [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]
    return system_prompt


def _call(system_prompt, user_content, max_tokens=1024,
          model=MODEL_HAIKU, cache_system=False,
          operation="generic", user="system"):
    """Low-level Claude call with budget check, usage logging, and mock mode.

    `user_content` can be either a string (simple text message) or a list of
    content blocks (for multimodal / image support).
    """
    # Mock short-circuit
    if MOCK_MODE:
        logger.info("claude_call MOCK operation=%s model=%s user=%s", operation, model, user)
        return None  # caller handles mock replacement

    # Budget guard (raises BudgetExceededError if exceeded)
    _budget.check_budget()

    client = _get_client()

    # Build message content
    if isinstance(user_content, str):
        messages = [{"role": "user", "content": user_content}]
    else:
        messages = [{"role": "user", "content": user_content}]

    system_blocks = _build_system_blocks(system_prompt, cache_system)

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        messages=messages,
    )

    # Log usage + compute cost
    try:
        _budget.log_usage(user, operation, model, message.usage)
    except Exception as exc:
        logger.warning("failed to log usage: %s", exc)

    # Return raw text
    return message.content[0].text.strip()


def _call_and_parse(system_prompt, user_content, max_tokens, model,
                    cache_system, operation, user):
    """Wrapper that returns parsed JSON or mock dict."""
    if MOCK_MODE:
        return _mock_response(operation)
    raw = _call(system_prompt, user_content, max_tokens=max_tokens,
                model=model, cache_system=cache_system,
                operation=operation, user=user)
    return _parse_json_response(raw)


def _parse_json_response(raw):
    """Extract and parse JSON from Claude response (strips markdown fences)."""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # drop first fence + possibly last fence
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])
    return json.loads(text)


def _truncate(text, max_chars=12000):
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[texto truncado para análise]"


# ---------------------------------------------------------------------------
# Public API — document analysis
# ---------------------------------------------------------------------------

def process_filing(text, ticker, doc_type="FILING", doc_title="", user="system"):
    """Analyze a regulatory filing (CVM/SEC). Uses Sonnet 4.6 + caching."""
    try:
        prompt = _FILING_USER.format(
            ticker=ticker, doc_type=doc_type, doc_title=doc_title,
            text=_truncate(text),
        )
        result = _call_and_parse(
            _FILING_SYSTEM, prompt, max_tokens=1024,
            model=MODEL_SONNET, cache_system=True,
            operation="process_filing", user=user,
        )
        result.setdefault("summary", "")
        result.setdefault("key_points", [])
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("process_filing error [%s]: %s", ticker, e)
        return None


def process_news(text, ticker, headline="", source="", user="system"):
    """Analyze a news article. Uses Haiku 4.5 + caching."""
    try:
        prompt = _NEWS_USER.format(
            ticker=ticker, source=source, headline=headline,
            text=_truncate(text, max_chars=6000),
        )
        result = _call_and_parse(
            _NEWS_SYSTEM, prompt, max_tokens=512,
            model=MODEL_HAIKU, cache_system=True,
            operation="process_news", user=user,
        )
        result.setdefault("summary", "")
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("process_news error [%s]: %s", ticker, e)
        return None


def process_manual(text, ticker="", user="system"):
    """Analyze manually pasted content (sell-side report, Bloomberg, transcript). Haiku."""
    try:
        prompt = _MANUAL_USER.format(
            ticker=ticker or "não especificado",
            text=_truncate(text, max_chars=12000),
        )
        result = _call_and_parse(
            _MANUAL_SYSTEM, prompt, max_tokens=1024,
            model=MODEL_HAIKU, cache_system=True,
            operation="process_manual", user=user,
        )
        result.setdefault("summary", "")
        result.setdefault("key_points", [])
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("process_manual error [%s]: %s", ticker, e)
        return None


def process_news_from_url(text, ticker, headline="", source="", user="system"):
    """Alias for process_news tagged with the url_ingest operation label.
    Accepts already-extracted text from `research_pipeline._fetch_url_text()`.
    Kept as a separate function so usage telemetry shows URL ingests distinctly
    from other news analyses.
    """
    try:
        prompt = _NEWS_USER.format(
            ticker=ticker, source=source, headline=headline,
            text=_truncate(text, max_chars=8000),
        )
        result = _call_and_parse(
            _NEWS_SYSTEM, prompt, max_tokens=512,
            model=MODEL_HAIKU, cache_system=True,
            operation="url_ingest", user=user,
        )
        result.setdefault("summary", "")
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("process_news_from_url error [%s]: %s", ticker, e)
        return None


def process_document_image(image_bytes, mime, ticker, doc_type="NEWS",
                            title="", source="", user="system"):
    """Analyze an image (screenshot/PDF page rendered) via Claude Vision.

    Routes to the NEWS or FILING prompt depending on doc_type. Haiku only.

    Returns dict with the same shape as process_news/process_filing.
    Returns None on error.
    """
    try:
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        is_filing = (doc_type or "").upper() == "FILING"
        system = _FILING_SYSTEM if is_filing else _NEWS_SYSTEM

        text_hint = (
            "Este é um documento regulatório oficial" if is_filing
            else "Este é um artigo de notícia"
        )
        text_block = (
            f"{text_hint} relacionado ao ticker {ticker}. "
            f"Fonte: {source or 'não especificada'}. "
            f"Título: {title or 'não especificado'}. "
            "Extraia o texto relevante da imagem e produza o JSON conforme as instruções do sistema."
        )

        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime or "image/png",
                    "data": b64,
                },
            },
            {"type": "text", "text": text_block},
        ]

        result = _call_and_parse(
            system, user_content, max_tokens=1024,
            model=MODEL_HAIKU, cache_system=True,
            operation="file_ingest_vision", user=user,
        )
        result.setdefault("summary", "")
        result.setdefault("key_points", [])
        result.setdefault("sentiment", "NEUTRO")
        result.setdefault("relevance", 5)
        result.setdefault("update_thesis", False)
        result.setdefault("update_reason", None)
        return result
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("process_document_image error [%s]: %s", ticker, e)
        return None


def extract_valuation_from_excel(markdown, ticker, missing_fields, user="system"):
    """Extract valuation fields from an Excel-converted markdown blob.

    Haiku 4.5 + cached system prompt. Returns dict with all valuation fields
    (any may be null). Falls back to {} on error.
    """
    try:
        prompt = _VALUATION_EXTRACT_USER.format(
            ticker=ticker,
            missing_fields=", ".join(missing_fields or []) or "(nenhum)",
            markdown=_truncate(markdown, max_chars=20000),
        )
        result = _call_and_parse(
            _VALUATION_EXTRACT_SYSTEM, prompt, max_tokens=2048,
            model=MODEL_HAIKU, cache_system=True,
            operation="excel_extract", user=user,
        )
        return result or {}
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("extract_valuation_from_excel error [%s]: %s", ticker, e)
        return {}


# ---------------------------------------------------------------------------
# Public API — Q&A
# ---------------------------------------------------------------------------

def answer_question(question, ticker, context_chunks, user="system", model="haiku"):
    """Answer a ticker-scoped question using RAG context.

    `model`: 'haiku' (default, ~5× cheaper) or 'sonnet' (more nuanced).
    """
    try:
        # Build context string
        parts = []
        for c in (context_chunks or []):
            label = {"thesis": "Tese", "filing": "Filing", "news": "Notícia",
                     "note": "Nota", "valuation": "Valuation"}.get(c.get("type"), c.get("type", "Item"))
            ticker_prefix = f"[{c['ticker']}] " if c.get("ticker") else ""
            parts.append(f"[{ticker_prefix}{label} #{c.get('id','?')}]\n{c.get('text') or c.get('snippet','')}")
        context = "\n\n---\n\n".join(parts) if parts else "Nenhuma informação encontrada na base."

        prompt = _QA_USER.format(question=question, context=_truncate(context, 40000))

        resolved_model = MODEL_HAIKU if str(model).lower() == "haiku" else MODEL_SONNET
        operation = "qa_ticker_haiku" if resolved_model == MODEL_HAIKU else "qa_ticker_sonnet"

        if MOCK_MODE:
            mock = _mock_response(operation)
            return {
                "answer": mock["answer"],
                "sources": [
                    {"type": c.get("type"), "id": c.get("id"),
                     "ticker": c.get("ticker"), "snippet": c.get("snippet", "")}
                    for c in (context_chunks or [])
                ],
            }

        answer = _call(_QA_SYSTEM, prompt, max_tokens=1024,
                       model=resolved_model, cache_system=True,
                       operation=operation, user=user)
        sources = [
            {"type": c.get("type"), "id": c.get("id"),
             "ticker": c.get("ticker"), "snippet": c.get("snippet", "")}
            for c in (context_chunks or [])
        ]
        return {"answer": answer, "sources": sources}
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("answer_question error [%s]: %s", ticker, e)
        return None


def answer_portfolio_question(question, context_text, sources=None, user="system",
                                max_ctx=20000):
    """Answer a portfolio-level question. `context_text` pre-built from caller.
    `max_ctx` caps the context character count (default 20k, down from 60k).
    """
    try:
        prompt = _QA_PORTFOLIO_USER.format(
            question=question,
            context=_truncate(context_text, max_chars=max_ctx),
        )
        if MOCK_MODE:
            mock = _mock_response("qa_portfolio")
            return {"answer": mock["answer"], "sources": sources or []}
        answer = _call(_QA_PORTFOLIO_SYSTEM, prompt, max_tokens=2048,
                       model=MODEL_SONNET, cache_system=True,
                       operation="qa_portfolio", user=user)
        return {"answer": answer, "sources": sources or []}
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("answer_portfolio_question error: %s", e)
        return None


def suggest_thesis_update(current_thesis, trigger_summary, trigger_type="filing", user="system"):
    """Generate a draft thesis update. Sonnet, no cache (prompt varies).
    Returns str or None on error.
    """
    try:
        prompt = _THESIS_SUGGEST_USER.format(
            current_thesis=_truncate(current_thesis or "Nenhuma tese ativa.", 6000),
            trigger_type=str(trigger_type).upper(),
            trigger_summary=trigger_summary or "Sem resumo disponível.",
        )
        if MOCK_MODE:
            return _mock_response("thesis_suggest")
        return _call(_THESIS_SUGGEST_SYSTEM, prompt, max_tokens=2048,
                     model=MODEL_SONNET, cache_system=False,
                     operation="thesis_suggest", user=user).strip()
    except _budget.BudgetExceededError:
        raise
    except Exception as e:
        logger.error("suggest_thesis_update error: %s", e)
        return None
