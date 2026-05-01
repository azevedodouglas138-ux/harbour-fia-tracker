# HARBOUR IAT FIF AÇÕES RL — Portfolio Tracker

Web app para acompanhar a carteira do fundo HARBOUR IAT FIF AÇÕES RL em tempo real, com visual Bloomberg Terminal.

## Stack
- **Backend:** Python + Flask + yfinance
- **Frontend:** HTML + CSS + Vanilla JS + Chart.js
- **Deploy:** Render (free tier — dorme após 15min sem acesso)
- **Auto-close de cota:** GitHub Actions às 18h15 BRT (seg-sex)

## Localização
- **Pasta local:** `C:\Users\azeve.DOUGLAS_AZEVEDO\harbour-fia-tracker\`
- **GitHub:** https://github.com/azevedodouglas138-ux/harbour-fia-tracker
- **Produção:** https://harbour-fia-tracker.onrender.com

## Estrutura de arquivos
- `app.py` — Flask backend, endpoints, cálculo de cota e taxa de performance
- `cvm_daily_fetcher.py` — fetcher diário de dados CVM
- `research_claude.py` / `research_db.py` / `research_pipeline.py` — pipeline de research (SQLite + FTS5 + Claude API)
- `risk_methodology.py` — cálculo de métricas de risco
- `gerar_apresentacao.py` — geração de PPTX
- `data/portfolio.json` — posições (quantidade, preço alvo, etc.)
- `data/fund_config.json` — cota de fechamento, nº de cotas, caixa, proventos, custos, taxa perf., descrição do fundo
- `data/quota_history.json` — histórico completo de cotas (desde 27/02/2018)
- `data/cache.json` — cache de fundamentos (7d) e histórico (4h)
- `templates/index.html` — layout Bloomberg Terminal
- `static/style.css` — tema Bloomberg (preto, laranja, monospace)
- `static/app.js` — lógica de refresh, gráficos, modais
- `tests/` — testes (ex: `test_research_phase3.py`)

## Regras de cálculo importantes
- Cálculo intraday **sempre** usa o último fechamento de `quota_history.json` como base (função `get_effective_fund_config` em `app.py`).
- **Performance fee:** 20% sobre o alpha vs IBOV, provisão diária.
- Auto-close via endpoint `/api/quota-history/auto-close` (chamado pelo GitHub Actions).

## Abas da UI
- **Portfólio** — tabela 21 colunas, stats bar, gráfico rentabilidade acumulada, concentração setorial, upside, export CSV/Excel
- **Apresentação (209)** — 6 slides (Sobre, Performance, Retorno Anual, Risco, Concentração, Distribuição) + export PDF (html2canvas+jsPDF) / PPTX (python-pptx server-side)
- **Configurações** — editar cota, cotas, caixa, proventos, custos, taxa perf., descrição
- **Histórico de Cotas** — tabela com var dia % e retorno acumulado, registro manual
- **Research (212)** — knowledge base por empresa (design aprovado, em implementação)

## Fluxo de deploy
1. Editar arquivos locais
2. `git add . && git commit -m "..." && git push`
3. Render redeploy automático (~2-3 min) ou Manual Deploy no painel

## Auth
Variáveis de ambiente: `LOGIN_USER`, `LOGIN_PASSWORD` (admin) e `VIEWER_USER`, `VIEWER_PASSWORD` (read-only). Viewer tem toggles por aba no config.

## Convenções
- Idioma: comentários e commits em PT-BR
- Nunca commitar segredos (`GITHUB_TOKEN`, `SECRET_KEY`, senhas) — usar env vars
- Cache de fundamentos: 7 dias. Cache de histórico: 4h
- Antes de mexer em cálculo de cota ou performance fee, revisar `get_effective_fund_config` em `app.py`

## Sistema responsivo (spec 2026-05-01)

Toda nova aba ou card visual deve usar os primitivos:

- `.app-container` / `.tab-content` — container raiz (max-width 1920, padding fluido `clamp(12px, 2vw, 32px)`)
- `.dashboard-grid` — grid fluido auto-fit; cards de tamanhos diferentes via modificadores
- `.chart-card` — wrapper de qualquer card visual (background, border, top-border laranja, padding)
  - `.chart-card--md` — min-width 480px
  - `.chart-card--lg` — min-width 640px, ocupa span 2 quando há ≥2 colunas no grid
- `.table-wrap` — único local com scroll horizontal; primeira coluna pode ter `.sticky-col`
- `.chart-canvas-wrap` — envolve `<canvas>` Chart.js; modificadores `--line` (16/9), `--bar` (4/3), `--pie` (1/1), `--heat` (1/1, maior), `--dist` (16/9, menor)

**Tokens disponíveis** (em `:root`):
- Breakpoints: `--bp-sm: 720px`, `--bp-md: 1100px`, `--bp-lg: 1440px`, `--bp-xl: 1920px`
- Spacing: `--gap-xs: 4px`, `--gap-sm: 8px`, `--gap-md: 12px`, `--gap-lg: 16px`, `--gap-xl: 24px`

**Regras invioláveis:**
- Sem `max-height: Xvh` em wrappers de conteúdo (só em modais/dropdowns)
- Sem scroll horizontal fora de `.table-wrap`
- Sem `body.style.zoom` ou `transform: scale` em ancestrais de `<canvas>` (quebra hit detection do Chart.js)
- Sem media queries finas (1100-1280, 1280-1366, etc.); só os 4 breakpoints canônicos
- Tabelas grandes: marcar `<th>` e `<td>` com `data-tier="1|2|3|4"` para hiding progressivo

**Spec/plano completos:**
- `docs/superpowers/specs/2026-05-01-responsive-design-system-design.md`
- `docs/superpowers/plans/2026-05-01-responsive-design-system.md`
