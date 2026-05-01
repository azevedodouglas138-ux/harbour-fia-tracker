# Sistema responsivo do Harbour Tracker — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aplicar o sistema responsivo descrito em [2026-05-01-responsive-design-system-design.md](../specs/2026-05-01-responsive-design-system-design.md) em toda a plataforma, eliminando o "desalinhamento e scroll ruim" entre 720px e 2560+px.

**Architecture:** Adicionar tokens CSS + 3 primitivos de layout (`.dashboard-grid`, `.chart-card`, `.table-wrap`, `.chart-canvas-wrap`) sem mudar nada visualmente; depois migrar cada aba para usar esses primitivos, em commits individuais para revert pontual. Sem reescrita: o CSS antigo é removido apenas quando o novo já está provando seu valor.

**Tech Stack:** CSS Grid + custom properties + media queries; Vanilla JS para o botão `+ COLUNAS`; Jinja2 templates Flask. Nada de build step, nada de framework novo.

---

## File Structure

| Arquivo | Responsabilidade | Tipo |
|---------|------------------|------|
| `static/style.css` | Tokens + primitivos no topo; refactor das regras antigas por aba | Modificar |
| `templates/index.html` | Estrutura de cada aba migrada para usar primitivos | Modificar |
| `static/app.js` | Estado/persistência do botão `+ COLUNAS` | Modificar |
| `AGENTS.md` | Documentar convenções do sistema novo (ao final) | Modificar |

Não há arquivos novos. Não há testes automatizados (projeto não tem infra de teste de UI).

**Validação por task:** checklist manual no Chrome DevTools (F12 → Toggle device toolbar → setar largura). Larguras canônicas: **720, 1100, 1440, 1920**.

---

# Fase 1 — Foundation (invisível ao usuário)

## Task 1: Adicionar tokens CSS

**Files:**
- Modificar: `static/style.css:6-30` (bloco `:root`)

- [ ] **Step 1: Adicionar breakpoints, container e spacing tokens no `:root` existente**

Localizar o bloco `:root { ... }` no início de `static/style.css` (linha 6) e adicionar antes da fechadura `}`:

```css
  /* ═══ Sistema responsivo (spec 2026-05-01) ═══ */
  --bp-sm:  720px;
  --bp-md:  1100px;
  --bp-lg:  1440px;
  --bp-xl:  1920px;
  --gap-xs: 4px;
  --gap-sm: 8px;
  --gap-md: 12px;
  --gap-lg: 16px;
  --gap-xl: 24px;
```

Resultado esperado: `:root` cresce de ~25 linhas para ~35 linhas. Nenhuma mudança visual.

- [ ] **Step 2: Validar visualmente que nada quebrou**

Abrir https://harbour-fia-tracker.onrender.com (ou rodar local com `python app.py`) e em DevTools → device toolbar → testar 720, 1100, 1440, 1920px. Tudo deve aparecer **exatamente igual** ao antes (tokens são inertes até serem usados).

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat(css): adiciona tokens de breakpoints e spacing (sistema responsivo)"
```

---

## Task 2: Adicionar primitivos de layout

**Files:**
- Modificar: `static/style.css` (adicionar bloco no fim do arquivo)

- [ ] **Step 1: Adicionar o bloco de primitivos no FIM do `static/style.css`**

Adicionar exatamente este bloco no final do arquivo:

```css
/* ═══════════════════════════════════════════════════════════════
   SISTEMA RESPONSIVO — primitivos (spec 2026-05-01)
   ═══════════════════════════════════════════════════════════════ */

/* Container raiz: max-width 1920px centralizado, padding fluido. */
.app-container,
.tab-content {
  max-width: var(--bp-xl);
  margin: 0 auto;
  padding-inline: clamp(12px, 2vw, 32px);
}
/* Topbar (.bbg-topbar) e fnbar (.bbg-fnbar) ficam intencionalmente fora deste
   container — vão até as bordas da tela, como o Bloomberg de verdade. */

/* Grid fluido para dashboards de cards. */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--card-min, 360px), 1fr));
  gap: var(--gap-md);
}

/* Card visual padrão. */
.chart-card {
  background: var(--surface);
  border: 1px solid var(--border);
  padding: var(--gap-md);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  min-width: 0;
}

/* Modificadores de tamanho intrínseco. */
.chart-card--md { --card-min: 480px; }
.chart-card--lg {
  --card-min: 640px;
  grid-column: span 2;
}
/* Em telas onde só cabe 1 coluna no grid, o span 2 é absorvido naturalmente
   pelo auto-fit (vira 1 coluna). Nenhuma regra adicional necessária. */

/* Wrapper único de tabelas. ÚNICO local com scroll horizontal no projeto. */
.table-wrap {
  overflow-x: auto;
  overflow-y: visible;
}
.table-wrap > table {
  min-width: max-content;
}
.table-wrap .sticky-col {
  position: sticky;
  left: 0;
  background: var(--surface);
  z-index: 1;
}

/* Wrapper de canvas Chart.js — aspect-ratio fixo + min/max-height. */
.chart-canvas-wrap {
  position: relative;
  width: 100%;
  min-height: var(--chart-min, 200px);
  max-height: var(--chart-max, 420px);
}
.chart-canvas-wrap--line { aspect-ratio: 16 / 9; }
.chart-canvas-wrap--bar  { aspect-ratio: 4 / 3;  --chart-max: 380px; }
.chart-canvas-wrap--pie  { aspect-ratio: 1 / 1;  --chart-min: 200px; --chart-max: 320px; }
.chart-canvas-wrap--heat { aspect-ratio: 1 / 1;  --chart-min: 280px; --chart-max: 480px; }
.chart-canvas-wrap--dist { aspect-ratio: 16 / 9; --chart-min: 220px; --chart-max: 360px; }
.chart-canvas-wrap > canvas {
  width: 100% !important;
  height: 100% !important;
}
```

- [ ] **Step 2: Validar que nada quebrou**

Recarregar a página. Como nenhuma classe nova está sendo USADA ainda, tudo deve continuar idêntico. Se algo quebrou, há colisão de seletor — verificar se algum CSS antigo já usava `.chart-card`, `.dashboard-grid`, etc.

Buscar conflitos: `grep -n "chart-card\|dashboard-grid\|table-wrap\|chart-canvas-wrap" static/style.css | head -20`

Nota: `.chart-card` JÁ EXISTE no CSS antigo (linhas ~520+, ~1600+). As regras antigas vão coexistir com as novas — o objetivo é convergir progressivamente. Como o seletor antigo é mais específico em vários pontos (ex.: `.chart-card:not(.wide) canvas`), ele continua tendo precedência onde já era usado. Isso é desejado: as abas não migradas continuam funcionando como antes.

- [ ] **Step 3: Commit**

```bash
git add static/style.css
git commit -m "feat(css): adiciona primitivos do sistema responsivo (.dashboard-grid, .chart-card, .table-wrap, .chart-canvas-wrap)"
```

---

## Task 3: Auditoria — remover `max-height: vh` e media queries redundantes

**Files:**
- Modificar: `static/style.css` (várias linhas, listadas abaixo)

- [ ] **Step 1: Listar todos os usos de `vh` e `max-height` em wrappers**

```bash
grep -n "max-height:\|vh\b" static/style.css
```

Resultado de referência (pode variar pós-tasks anteriores):

- 527: `.chart-card:not(.wide) canvas { max-height: 280px; min-height: 220px; }` — remover (será substituído pelo `.chart-canvas-wrap`)
- 934: `max-height: none;` — manter (é override válido em algum modal)
- 1572: `.chart-card:not(.wide) canvas { max-height: 320px; }` — remover (parte do `ec3c977`)
- 1699: `.chart-card:not(.wide) canvas { max-height: 240px; min-height: 180px; }` — remover
- 1726: `max-height: 90vh;` — verificar contexto (provavelmente modal); manter se for modal
- 1757: `.chart-card:not(.wide) canvas { max-height: 200px; min-height: 160px; }` — remover
- 1799: `@media (max-height: 540px) and (orientation: landscape)` — manter
- 2005: `max-height: 520px;` — verificar contexto

- [ ] **Step 2: Remover as 4 regras `.chart-card:not(.wide) canvas { max-height: ... }`**

Para cada linha listada (527, 1572, 1699, 1757):

```bash
# Localizar e ler o contexto de cada uma:
sed -n '525,530p' static/style.css
sed -n '1570,1575p' static/style.css
sed -n '1697,1702p' static/style.css
sed -n '1755,1760p' static/style.css
```

Remover as linhas que correspondem ao padrão `.chart-card:not(.wide) canvas { max-height: ...; min-height: ...; }`. Essas são regras que conflitam com o novo `.chart-canvas-wrap` e seriam removidas durante a migração das abas. Removendo agora simplifica o sweep.

Atenção: `.chart-card.wide canvas { ... }` (com `.wide`) pode existir e DEVE ser mantido — é override semântico para charts que ocupam linha inteira. Só remover as variantes `:not(.wide)`.

- [ ] **Step 3: Verificar que não quebrou nada**

Recarregar localmente. Os charts agora dependem do height definido por inline style (`<canvas height="180">`) ou pelo container. Pode haver charts levemente mais altos/baixos em algumas larguras — isso é esperado e será corrigido quando cada aba for migrada para `.chart-canvas-wrap`.

Larguras a validar: **1100px** (era a mais sensível ao breakpoint removido) e **720px**.

- [ ] **Step 4: Commit**

```bash
git add static/style.css
git commit -m "refactor(css): remove regras .chart-card:not(.wide) canvas redundantes (preparação para sistema responsivo)"
```

---

# Fase 2 — Refatorar abas críticas

## Task 4: TABELA — adicionar classe `.carteira-table` e estrutura

**Files:**
- Modificar: `templates/index.html:183-184` (envolver `<table id="portfolio-table">`)

- [ ] **Step 1: Adicionar classe `.carteira-table` à tabela e usar `.table-wrap`**

Localizar em `templates/index.html` (linha ~183):

```html
<div class="table-wrapper">
  <table id="portfolio-table">
```

Substituir por:

```html
<div class="table-wrap carteira-table-wrap">
  <table id="portfolio-table" class="carteira-table">
```

Por que: o spec usa o seletor `.carteira-table` para regras específicas; `.table-wrap` é o primitivo de scroll horizontal. Ambos coexistem.

- [ ] **Step 2: Verificar que CSS de `.table-wrapper` ainda aplica**

Buscar `grep -n "table-wrapper" static/style.css` — se houver regras em `.table-wrapper`, manter por enquanto (a classe permanece como compatibilidade até o cleanup final).

Decisão: NÃO remover `.table-wrapper` ainda. Vai ficar como classe redundante na div, sem prejuízo. Será removido na Task 15 (cleanup).

- [ ] **Step 3: Validar visualmente**

Recarregar TABELA. Em 1920px deve estar idêntico ao antes. Em 720px (meia tela), provavelmente vai aparecer scroll horizontal NA TABELA (esperado — `.table-wrap` permite). O resto da página NÃO deve scrollar horizontal.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "refactor(table): adiciona class .carteira-table e usa .table-wrap"
```

---

## Task 5: TABELA — sistema de tiers (4 níveis de prioridade de coluna)

**Files:**
- Modificar: `templates/index.html:187-208` (cabeçalho da tabela: 21 `<th>`)
- Modificar: `static/app.js` (renderização das linhas, onde os `<td>` são gerados)
- Modificar: `static/style.css` (regras de tier)

- [ ] **Step 1: Adicionar atributo `data-tier` em cada `<th>` da carteira**

Localizar em `templates/index.html` o bloco de `<th>` (linhas ~187-207). Modificar cada `<th>` adicionando `data-tier`:

```html
<th data-col="ticker"            data-tier="1">ATIVO</th>
<th data-col="categoria"         data-tier="3">CATEG.</th>
<th data-col="sector"            data-tier="2">SETOR</th>
<th data-col="pct_total"         data-tier="1" class="num">% TOTAL</th>
<th data-col="valor_liquido"     data-tier="1" class="num">VALOR LÍQ.</th>
<th data-col="preco"             data-tier="1" class="num">PREÇO</th>
<th data-col="var_dia_pct"       data-tier="1" class="num">VAR. DIA</th>
<th data-col="quantidade"        data-tier="1" class="num">QTDE</th>
<th data-col="liq_diaria_mm"     data-tier="1" class="num">LIQ. DIÁRIA <span class="col-info" data-tip="...">ⓘ</span></th>
<th data-col="trailing_pe"       data-tier="3" class="num">P/L TRAIL.</th>
<th data-col="forward_pe"        data-tier="3" class="num">P/L FWD.</th>
<th data-col="peg_ratio"         data-tier="4" class="num">PEG</th>
<th data-col="enterprise_to_ebitda" data-tier="4" class="num">EV/EBITDA</th>
<th data-col="return_on_equity"  data-tier="2" class="num">ROE %</th>
<th data-col="beta"              data-tier="3" class="num">BETA</th>
<th data-col="price_to_book"     data-tier="4" class="num">P/VPA</th>
<th data-col="dividend_yield"    data-tier="2" class="num">DIV. YIELD</th>
<th data-col="market_cap_bi"     data-tier="2" class="num">MKT CAP</th>
<th data-col="lucro_mi_26"       data-tier="3" class="num">LUCRO MI 26</th>
<th data-col="preco_alvo"        data-tier="1" class="num">P. ALVO</th>
<th data-col="upside_pct"        data-tier="1" class="num">UPSIDE</th>
```

(Atenção: preserve o `<span class="col-info" data-tip="...">` da coluna LIQ. DIÁRIA — não substitua o tooltip.)

- [ ] **Step 2: Adicionar `data-tier` nos `<td>` correspondentes**

Localizar em `static/app.js` a função que renderiza linhas da tabela (`renderTable` ou similar). Cada `<td>` precisa receber o mesmo `data-tier` do `<th>` correspondente.

Estratégia mais simples (single source of truth): em vez de duplicar o mapping no JS, **deixar o JS ler o tier do header em runtime**:

```js
// No início de renderTable() ou função equivalente:
const tierMap = {};
document.querySelectorAll('#portfolio-table thead th[data-col]').forEach(th => {
  tierMap[th.dataset.col] = th.dataset.tier;
});

// Quando construir cada <td>:
// (substituir o template literal atual por uma versão que injeta data-tier)
const td = (col, content, cls='') =>
  `<td data-col="${col}" data-tier="${tierMap[col] || '1'}" ${cls ? `class="${cls}"` : ''}>${content}</td>`;
```

Localizar a função real e adaptar. Provável que esteja em torno de uma função chamada `renderTable()` ou similar (~linha 200-400 do `app.js`).

- [ ] **Step 3: Adicionar regras CSS de tier no fim do `static/style.css`**

```css
/* ═══════════════════════════════════════════════════════════════
   TABELA CARTEIRA — sistema de tiers (spec 2026-05-01)
   ═══════════════════════════════════════════════════════════════ */
@media (max-width: 1099px) {
  .carteira-table [data-tier="2"],
  .carteira-table [data-tier="3"],
  .carteira-table [data-tier="4"] { display: none; }
}
@media (min-width: 1100px) and (max-width: 1439px) {
  .carteira-table [data-tier="3"],
  .carteira-table [data-tier="4"] { display: none; }
}
@media (min-width: 1440px) and (max-width: 1919px) {
  .carteira-table [data-tier="4"] { display: none; }
}

/* Override pelo botão "+ COLUNAS" (Task 6). */
body[data-force-all-cols="true"] .carteira-table [data-tier] {
  display: revert;
}
```

- [ ] **Step 4: Validar nas 4 larguras**

DevTools → 720px: 9 colunas (ATIVO, % TOTAL, VALOR LÍQ., PREÇO, VAR. DIA, QTDE, LIQ. DIÁRIA, P. ALVO, UPSIDE). Pode haver scroll horizontal leve dependendo do conteúdo (esperado).

DevTools → 1100px: 13 colunas (acima + SETOR, ROE %, DIV. YIELD, MKT CAP).

DevTools → 1440px: 18 colunas (acima + CATEG., P/L TRAIL., P/L FWD., LUCRO MI 26, BETA).

DevTools → 1920px: 21 colunas (todas).

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/app.js static/style.css
git commit -m "feat(table): sistema de tiers para tabela carteira (9/13/18/21 cols por breakpoint)"
```

---

## Task 6: TABELA — coluna ATIVO sticky + botão `+ COLUNAS`

**Files:**
- Modificar: `templates/index.html` (header da tabela: adicionar botão antes do `<table>`; cabeçalho ATIVO recebe class `sticky-col`)
- Modificar: `static/app.js` (handler do botão; primeira coluna `<td>` recebe class `sticky-col`)
- Modificar: `static/style.css` (estilo do botão + override de `.carteira-table .sticky-col`)

- [ ] **Step 1: Adicionar `class="sticky-col"` ao `<th data-col="ticker">`**

Em `templates/index.html` linha ~187:

```html
<th data-col="ticker" data-tier="1" class="sticky-col">ATIVO</th>
```

- [ ] **Step 2: Adicionar `class="sticky-col"` ao `<td>` da coluna ticker no JS**

No mesmo lugar do Task 5 Step 2, garantir que a célula da coluna `ticker` recebe `class="sticky-col"`. Exemplo:

```js
// Caso especial pra coluna ticker:
const isTicker = col === 'ticker';
const cls = (isTicker ? 'sticky-col' : '') + (numCol ? ' num' : '');
```

- [ ] **Step 3: Adicionar botão `+ COLUNAS` no header da tabela**

Localizar o header da aba TABELA em `templates/index.html` (provavelmente um `<div>` antes do `<div class="table-wrap">`). Adicionar:

```html
<div class="carteira-toolbar">
  <button type="button" class="bbg-btn" id="btn-toggle-all-cols">+ COLUNAS</button>
</div>
```

Se já existe uma toolbar com outros botões (refresh, export, etc.), adicionar dentro dela.

- [ ] **Step 4: Adicionar handler em `static/app.js`**

Adicionar bloco no fim do arquivo (ou junto aos outros listeners de botões):

```js
/* ═══ Botão "+ COLUNAS" — força mostrar todas as 21 colunas ═══ */
(function setupForceAllCols() {
  const KEY = 'carteira-force-all-cols';
  const btn = document.getElementById('btn-toggle-all-cols');
  if (!btn) return;

  const apply = (on) => {
    if (on) {
      document.body.dataset.forceAllCols = 'true';
      localStorage.setItem(KEY, 'true');
      btn.classList.add('active');
      btn.textContent = '− COLUNAS';
    } else {
      delete document.body.dataset.forceAllCols;
      localStorage.removeItem(KEY);
      btn.classList.remove('active');
      btn.textContent = '+ COLUNAS';
    }
  };

  apply(localStorage.getItem(KEY) === 'true');
  btn.addEventListener('click', () => {
    apply(localStorage.getItem(KEY) !== 'true');
  });
})();
```

- [ ] **Step 5: Estilo do botão e override do sticky**

Adicionar no `static/style.css`:

```css
.carteira-toolbar {
  display: flex;
  gap: var(--gap-sm);
  margin-bottom: var(--gap-sm);
}
#btn-toggle-all-cols.active {
  border-color: var(--orange);
  color: var(--orange);
}

/* Sticky-col na carteira: garantir z-index acima das outras células e bg sólido */
.carteira-table th.sticky-col,
.carteira-table td.sticky-col {
  background: var(--surface);
  position: sticky;
  left: 0;
  z-index: 2;
}
.carteira-table thead th.sticky-col { z-index: 3; }
```

- [ ] **Step 6: Validar**

- 720px: scrollar a tabela horizontalmente, ATIVO permanece visível na borda esquerda.
- Clicar `+ COLUNAS`: todas as 21 colunas aparecem mesmo em 720px (vai dar muito scroll horizontal, mas funciona).
- Recarregar página: estado do botão persiste.
- Clicar de novo: volta ao normal.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html static/app.js static/style.css
git commit -m "feat(table): coluna ATIVO sticky + botão '+ COLUNAS' com persistência"
```

---

## Task 7: RISCO — restruturação para `.dashboard-grid` + classificação de cards

**Files:**
- Modificar: `templates/index.html:608-810` (toda a estrutura da aba RISCO)
- Modificar: `static/style.css` (remover `.risk-row` se houver e ajustar regras de `.risk-card`)

- [ ] **Step 1: Substituir os 7 `<div class="risk-row">` por um único `<div class="dashboard-grid risk-dashboard">`**

A estrutura atual tem 7 rows com 2 cards cada (último com 1 full-width). Substituir TODA a área dentro de `<div id="tab-risk" class="tab-content...">` por:

```html
<div id="tab-risk" class="tab-content{% if ns2.first %} active{% endif %}">
{% set ns2.first = false %}

  <div class="dashboard-grid risk-dashboard">

    <!-- Tier "compacto" primeiro: KPIs essenciais -->
    <!-- VaR / CVaR -->
    <div class="chart-card risk-card" id="risk-var-card">
      <!-- conteúdo idêntico ao que está hoje no risk-var-card -->
    </div>

    <!-- Sortino & Calmar -->
    <div class="chart-card risk-card" id="risk-sortino-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Liquidez -->
    <div class="chart-card risk-card" id="risk-liq-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Concentração Setorial -->
    <div class="chart-card risk-card" id="risk-concentration-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Tier "médio": gráficos com janela -->
    <!-- Beta Rolante -->
    <div class="chart-card chart-card--md risk-card" id="risk-beta-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Tracking Error -->
    <div class="chart-card chart-card--md risk-card" id="risk-te-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Capture Up/Down -->
    <div class="chart-card chart-card--md risk-card" id="risk-capture-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Rolling Sharpe / Sortino -->
    <div class="chart-card chart-card--md risk-card" id="risk-rolling-ratios-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Exposição Cambial -->
    <div class="chart-card chart-card--md risk-card" id="risk-fx-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Tier "grande": cards que merecem 2 colunas quando há espaço -->
    <!-- Stress Test -->
    <div class="chart-card chart-card--lg risk-card" id="risk-stress-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Matriz de Correlação -->
    <div class="chart-card chart-card--lg risk-card" id="risk-corr-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Risk Attribution -->
    <div class="chart-card chart-card--lg risk-card" id="risk-attr-card">
      <!-- conteúdo idêntico ao atual -->
    </div>

    <!-- Distribuição de Retornos -->
    <div class="chart-card chart-card--lg risk-card" id="risk-dist-card">
      <!-- conteúdo idêntico ao atual; remover style="grid-column: 1 / -1" -->
    </div>

  </div>
</div>
```

**Importante:** copiar EXATAMENTE o conteúdo interno (tudo dentro da div com id `risk-XXX-card`) de cada card que existe hoje em [index.html:611-810](../../../templates/index.html). Não alterar headers, controles, IDs internos. A única mudança é a div externa do card e a remoção dos `<div class="risk-row">`.

Em particular: **remover o `style="grid-column: 1 / -1"` do `risk-dist-card`** — o `chart-card--lg` já cuida disso (span 2). Em telas estreitas onde só cabe 1 coluna, ele naturalmente vira full-width.

- [ ] **Step 2: Remover/limpar regras de `.risk-row` e ajustar `.risk-card` no CSS**

```bash
grep -n "\.risk-row\|\.risk-card" static/style.css
```

- Remover toda regra que comece com `.risk-row` (já não existem mais no HTML).
- Manter regras de `.risk-card` que sejam temáticas/visuais (cores, badges); remover as que tentam controlar dimensão (height, max-width, etc.) — agora é o `.chart-card` que cuida.

Se houver dúvida em alguma regra: comentar, recarregar, ver se nada quebra. Se não quebrou, deletar.

- [ ] **Step 3: Validar nas 4 larguras**

- **720px**: 1 coluna, 13 cards empilhados. Cards `--lg` ocupam 1 coluna (não há buracos).
- **1100px**: 2 colunas (cards compactos lado a lado; cards `--md` em 1 coluna; `--lg` ocupando 2 colunas = 1 row inteira).
- **1440px**: 2-3 colunas (cabe span 2 confortavelmente).
- **1920px**: 3-4 colunas, cards `--lg` ocupando 2 colunas.

Se aparecer "buraco" em alguma largura, ajustar `--card-min` do tier afetado.

Tooltips dos charts dentro da aba devem continuar **colados no cursor** (regressão do bug que resolvemos).

- [ ] **Step 4: Commit**

```bash
git add templates/index.html static/style.css
git commit -m "refactor(risk): migra aba RISCO para .dashboard-grid + reclassifica 13 cards (compacto/médio/grande)"
```

---

# Fase 3 — Sweep das 7 abas restantes

> **Padrão geral pra cada aba do sweep:**
> 1. Identificar o container raiz da aba e qualquer grade ad-hoc.
> 2. Substituir a grade por `.dashboard-grid` + `.chart-card` (com `--md` ou `--lg` se aplicável).
> 3. Envolver cada `<canvas>` em `<div class="chart-canvas-wrap chart-canvas-wrap--TIPO">`.
> 4. Validar nas 4 larguras. Commit.

## Task 8: GRÁFICOS (aba 201)

**Files:**
- Modificar: `templates/index.html:283-352` (área da aba `tab-charts`)
- Modificar: `static/style.css` (remover regras antigas de `.chart-card` específicas dessa aba se houver)

- [ ] **Step 1: Localizar e mapear os charts atuais**

```bash
grep -n "tab-charts\|history-chart\|sector-chart\|upside-chart\|dd-chart\|vol-chart\|attrib-chart" templates/index.html
```

A aba GRÁFICOS contém: `history-chart` (line/area), `sector-chart` (pie), `upside-chart` (bar), `dd-chart` (line), `vol-chart` (line), `attrib-chart` (bar).

- [ ] **Step 2: Refatorar a estrutura para usar `.dashboard-grid`**

Identificar o grid atual da aba (provavelmente uma sequência de divs com classes `.chart-card.wide` ou `.charts-grid`). Substituir por:

```html
<div class="dashboard-grid">
  <div class="chart-card chart-card--lg" id="card-history">
    <!-- header existente -->
    <div class="chart-canvas-wrap chart-canvas-wrap--line">
      <canvas id="history-chart"></canvas>
    </div>
  </div>

  <div class="chart-card" id="card-sector">
    <!-- header existente -->
    <div class="chart-canvas-wrap chart-canvas-wrap--pie">
      <canvas id="sector-chart"></canvas>
    </div>
  </div>

  <div class="chart-card" id="card-upside">
    <!-- header existente -->
    <div class="chart-canvas-wrap chart-canvas-wrap--bar">
      <canvas id="upside-chart"></canvas>
    </div>
  </div>

  <div class="chart-card chart-card--md" id="card-dd">
    <!-- header existente -->
    <div class="chart-canvas-wrap chart-canvas-wrap--line">
      <canvas id="dd-chart"></canvas>
    </div>
  </div>

  <div class="chart-card chart-card--md" id="card-vol">
    <!-- header existente -->
    <div class="chart-canvas-wrap chart-canvas-wrap--line">
      <canvas id="vol-chart"></canvas>
    </div>
  </div>

  <div class="chart-card chart-card--md" id="card-attrib">
    <!-- header existente -->
    <div class="chart-canvas-wrap chart-canvas-wrap--bar">
      <canvas id="attrib-chart"></canvas>
    </div>
  </div>
</div>
```

(Manter os IDs e a estrutura interna de header/controles existente em cada card.)

Remover atributos `height="..."` dos `<canvas>` se houver — o wrapper agora controla a dimensão.

- [ ] **Step 3: Remover `display: none` de canvas se forem JS-toggled**

Alguns canvas têm `style="display:none"` no HTML porque o JS mostra/esconde. Verificar se isso ainda é necessário com o wrapper. Se sim, mover o `display:none` pro `.chart-card` pai em vez do canvas:

```html
<div class="chart-card chart-card--md" id="card-dd" style="display:none">
```

- [ ] **Step 4: Validar**

Testar nas 4 larguras. Charts mantêm aspect ratio. Tooltip colado no cursor.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/style.css
git commit -m "refactor(charts): migra aba GRÁFICOS para .dashboard-grid + .chart-canvas-wrap"
```

---

## Task 9: CVM OFICIAL (aba 204)

**Files:**
- Modificar: `templates/index.html:1140-1170` (área dos 4 charts)
- Modificar: `static/style.css` (remover `.cvm-charts-grid` e `.cvm-chart-wrap`)

- [ ] **Step 1: Substituir `.cvm-charts-grid` por `.dashboard-grid`**

Localizar em `templates/index.html` o bloco com `cvm-chart-pl`, `cvm-chart-cota`, `cvm-chart-fluxo`, `cvm-chart-cotst`. A estrutura atual usa `<div class="cvm-charts-grid">` com `<div class="cvm-chart-wrap">` por canvas.

Substituir por:

```html
<div class="dashboard-grid">
  <div class="chart-card chart-card--md">
    <!-- header existente: "PATRIMÔNIO LÍQUIDO" -->
    <div class="chart-canvas-wrap chart-canvas-wrap--line">
      <canvas id="cvm-chart-pl"></canvas>
    </div>
  </div>
  <div class="chart-card chart-card--md">
    <!-- header existente: "COTA CVM vs CALC" -->
    <div class="chart-canvas-wrap chart-canvas-wrap--line">
      <canvas id="cvm-chart-cota"></canvas>
    </div>
  </div>
  <div class="chart-card chart-card--md">
    <!-- header existente: "FLUXO" -->
    <div class="chart-canvas-wrap chart-canvas-wrap--bar">
      <canvas id="cvm-chart-fluxo"></canvas>
    </div>
  </div>
  <div class="chart-card chart-card--md">
    <!-- header existente: "COTISTAS" -->
    <div class="chart-canvas-wrap chart-canvas-wrap--line">
      <canvas id="cvm-chart-cotst"></canvas>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Remover regras antigas de `.cvm-charts-grid` e `.cvm-chart-wrap` no CSS**

```bash
grep -n "cvm-charts-grid\|cvm-chart-wrap" static/style.css
```

Remover ambas as regras (~10-15 linhas).

- [ ] **Step 3: Validar nas 4 larguras**

Em 720px: 1 coluna (4 charts empilhados). Em 1100+: 2 colunas. Em 1440+: 2 colunas (--md tem min 480, então 1440 cabe 3 mas com 4 cards uniform fica balanceado em 2x2 ou 3+1).

- [ ] **Step 4: Commit**

```bash
git add templates/index.html static/style.css
git commit -m "refactor(cvm): migra aba CVM OFICIAL para .dashboard-grid + .chart-canvas-wrap"
```

---

## Task 10: ÍNDICES (aba 211)

**Files:**
- Modificar: `templates/index.html:1020-1080` (área da aba `tab-indices`)
- Modificar: `static/style.css` (regras `.idx-*` se conflitarem)

- [ ] **Step 1: Localizar a estrutura atual**

```bash
grep -n "tab-indices\|idx-treemap\|idx-table" templates/index.html
```

Espera-se: 2 tabelas `.idx-table` + 1 treemap `idx-treemap-canvas`.

- [ ] **Step 2: Refatorar para `.dashboard-grid`**

```html
<div id="tab-indices" class="tab-content...">
  <div class="dashboard-grid">

    <!-- Tabelas de índices (provavelmente 2 listas: BR e mundial) -->
    <div class="chart-card">
      <!-- header existente -->
      <div class="table-wrap">
        <table class="idx-table">
          <!-- conteúdo existente -->
        </table>
      </div>
    </div>

    <div class="chart-card">
      <!-- segunda tabela -->
      <div class="table-wrap">
        <table class="idx-table">
          <!-- conteúdo existente -->
        </table>
      </div>
    </div>

    <!-- Treemap (full width quando possível) -->
    <div class="chart-card chart-card--lg">
      <!-- header existente -->
      <div class="chart-canvas-wrap chart-canvas-wrap--heat">
        <canvas id="idx-treemap-canvas"></canvas>
      </div>
    </div>

  </div>
</div>
```

- [ ] **Step 3: Validar**

Em 720px: tudo empilhado. Treemap em 1:1 (quadrado).
Em 1100+: 2 tabelas lado a lado, treemap embaixo (span 2).

- [ ] **Step 4: Commit**

```bash
git add templates/index.html static/style.css
git commit -m "refactor(indices): migra aba ÍNDICES para .dashboard-grid + .chart-canvas-wrap"
```

---

## Task 11: HISTÓRICO DE COTAS (aba 203)

**Files:**
- Modificar: `templates/index.html:580-595` (tabela history-table)

- [ ] **Step 1: Migrar wrapper da tabela**

A tabela `#history-table` tem só 4 colunas (DATA, COTA FECHAMENTO, VAR. DIA %, RETORNO ACUM. %). Não precisa de tiers — todas cabem em 720px.

Substituir:

```html
<div class="table-wrapper table-wrapper--history">
  <table id="history-table">
```

Por:

```html
<div class="table-wrap historico-table-wrap">
  <table id="history-table">
```

- [ ] **Step 2: Validar**

A aba HISTÓRICO tem também um formulário e um chart de cota acima. Verificar se ambos estão dentro de uma estrutura consistente. Se já estão funcionando bem, deixar como está. Se houver bug, envolver em `.chart-card`.

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "refactor(history): aba HISTÓRICO usa .table-wrap"
```

---

## Task 12: EVENTOS (aba 210)

**Files:**
- Modificar: `templates/index.html:941-964`

A estrutura atual tem 2 modos de visualização (`events-timeline-view` e
`events-byasset-view`). O timeline é populado pelo JS livremente. O modo
"por ativo" tem inline style `display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;padding:12px 0`,
que é exatamente um `.dashboard-grid` ad-hoc.

- [ ] **Step 1: Substituir o inline style do `events-byasset-view` por `.dashboard-grid`**

Em [index.html:962](../../../templates/index.html):

```html
<div id="events-byasset-view" class="hidden" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;padding:12px 0"></div>
```

Trocar por:

```html
<div id="events-byasset-view" class="hidden dashboard-grid" style="--card-min:320px;padding:12px 0"></div>
```

(`--card-min: 320px` mantém o tamanho mínimo de card desta aba específica
que é menor que o default 360px porque cards de evento são compactos.)

- [ ] **Step 2: Verificar se o JS que adiciona cards a este container envolve em `.chart-card`**

```bash
grep -n "events-byasset-view\|byasset" static/app.js | head -10
```

Se o JS gera `<div>` ad-hoc por evento, modificar para `<div class="chart-card">`. Se já usa `.chart-card` ou similar, manter como está.

- [ ] **Step 3: Validar nas 4 larguras**

Em ambos os modos (TIMELINE e POR ATIVO). No "POR ATIVO", os cards devem
refluir 1 → 2 → 3 → 4 colunas conforme a largura aumenta.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html static/app.js
git commit -m "refactor(events): aba EVENTOS usa .dashboard-grid em vez de inline grid"
```

---

## Task 13: PRÉ-TRADE (aba 209)

**Files:**
- Modificar: `templates/index.html:819-933`

A estrutura tem 2 `.risk-row` com 4 `.chart-card.risk-card` total
(BASKET, IMPACTO COTA, COMPLIANCE, CARTEIRA ANTES/DEPOIS) + painéis
colapsáveis (PARÂMETROS, HISTÓRICO). Cada card tem `style="flex:N"`
inline.

- [ ] **Step 1: Substituir os 2 `.risk-row` por um único `.dashboard-grid`**

Trocar a sequência:

```html
<div class="risk-row">
  <div class="chart-card risk-card" style="flex:1.3;min-width:0">...</div>
  <div class="chart-card risk-card" style="flex:1">...</div>
</div>
<div class="risk-row">
  <div class="chart-card risk-card" style="flex:1">...</div>
  <div class="chart-card risk-card" style="flex:1">...</div>
</div>
```

Por:

```html
<div class="dashboard-grid">
  <!-- BASKET é o card principal, merece span 2 -->
  <div class="chart-card chart-card--lg risk-card">
    <!-- conteúdo idêntico ao atual do BASKET (incluindo tabela) -->
  </div>

  <!-- Os outros 3 cards: tamanho médio -->
  <div class="chart-card chart-card--md risk-card" id="pretrade-cota-card">
    <!-- conteúdo idêntico ao atual -->
  </div>

  <div class="chart-card chart-card--md risk-card" id="pretrade-compliance-card">
    <!-- conteúdo idêntico ao atual -->
  </div>

  <div class="chart-card chart-card--md risk-card" id="pretrade-portfolio-card">
    <!-- conteúdo idêntico ao atual -->
  </div>
</div>
```

Remover os `style="flex:..."` inline. A largura agora vem do
`.chart-card--lg` / `.chart-card--md`.

- [ ] **Step 2: Envolver `#pt-basket-table` em `.table-wrap`**

Em [index.html:834](../../../templates/index.html), substituir:

```html
<div style="overflow-x:auto">
  <table id="pt-basket-table" style="width:100%;...">
```

Por:

```html
<div class="table-wrap">
  <table id="pt-basket-table" class="pt-basket-table" style="width:100%;...">
```

- [ ] **Step 3: Painéis colapsáveis (params, history) — manter como `.chart-card`**

Os blocos `pretrade-params-panel` e `pretrade-history-panel` ([index.html:907-931](../../../templates/index.html)) já usam `.chart-card.risk-card` internamente. Não migrar — eles são overlays/colapsáveis, não fazem parte do grid. Manter como está.

- [ ] **Step 4: Validar nas 4 larguras**

- 720px: cards empilhados, BASKET ocupa largura total, scroll horizontal só dentro da tabela do basket.
- 1100px: 2 colunas (BASKET ocupa 1 row inteira, 3 outros cards em ordem 1→2→1).
- 1440-1920px: BASKET span 2, outros 3 em 1 coluna cada.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/style.css
git commit -m "refactor(pretrade): migra PRÉ-TRADE para .dashboard-grid + .table-wrap"
```

---

## Task 14: CONFIGURAÇÕES (aba 202)

**Files:**
- Modificar: `templates/index.html:378-435` (cfg-grid + cfg-panel)
- Modificar: `static/style.css` (regra de `.cfg-grid` se restritiva)

A aba tem `.cfg-grid` envolvendo 3 `.cfg-panel` (COTA DO FUNDO, CAIXA E
AJUSTES, TAXA DE PERFORMANCE). É um caso natural de `.dashboard-grid`.

- [ ] **Step 1: Substituir `.cfg-grid` por `.dashboard-grid` mantendo `.cfg-panel`**

Em [index.html:380](../../../templates/index.html):

```html
<div class="cfg-grid">
  <div class="cfg-panel">...</div>
  <div class="cfg-panel">...</div>
  <div class="cfg-panel">...</div>
</div>
```

Trocar por:

```html
<div class="dashboard-grid">
  <div class="chart-card cfg-panel">...</div>
  <div class="chart-card cfg-panel">...</div>
  <div class="chart-card cfg-panel">...</div>
</div>
```

`.cfg-panel` continua existindo (conteúdo interno usa). `.chart-card` vira o
container visual; `.cfg-panel` adiciona detalhes específicos (header com `◆`).

- [ ] **Step 2: Auditar regra antiga de `.cfg-grid` no CSS**

```bash
grep -n "\.cfg-grid" static/style.css
```

Se for só `.cfg-grid { display: grid; grid-template-columns: ... }`, remover (substituída pelo `.dashboard-grid`).
Se tiver regras específicas de espaçamento que continuem fazendo sentido, mover para `.dashboard-grid` da aba via override ou para `.cfg-panel`.

- [ ] **Step 3: Painel ACESSO VIEWER — mesmo tratamento**

Em [index.html:444](../../../templates/index.html), o `<div class="cfg-panel viewer-access-panel">` está fora do grid principal. Adicionar `chart-card`:

```html
<div class="chart-card cfg-panel viewer-access-panel">
```

- [ ] **Step 4: Validar**

Em todas as larguras: os 3 painéis de configuração refluem (1→2→3 colunas) automaticamente. O painel ACESSO VIEWER continua abaixo, full-width.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/style.css
git commit -m "refactor(config): aba CONFIGURAÇÕES usa .dashboard-grid + .chart-card nos cfg-panels"
```

---

# Fase 4 — Cleanup

## Task 15: Remover CSS órfão + atualizar AGENTS.md

**Files:**
- Modificar: `static/style.css` (remover regras não utilizadas)
- Modificar: `AGENTS.md` (adicionar seção de convenções)

- [ ] **Step 1: Identificar CSS órfão**

```bash
# Para cada classe suspeita de ter ficado órfã, verificar uso no HTML+JS:
for cls in risk-row table-wrapper cvm-charts-grid cvm-chart-wrap; do
  echo "=== $cls ==="
  grep -rn "$cls" templates/ static/ | grep -v "static/style.css"
done
```

Se a classe não aparece em nenhum `templates/*.html` ou `static/*.js`, ela é órfã. Remover do `style.css`.

Candidatos prováveis após o sweep:
- `.risk-row`
- `.table-wrapper`
- `.table-wrapper--history`
- `.cvm-charts-grid`
- `.cvm-chart-wrap`
- Media queries de `.chart-card:not(.wide) canvas` que ainda não foram removidas
- Breakpoints intermediários do `ec3c977` que ficaram redundantes (1100-1280, 1280-1366, etc.)

- [ ] **Step 2: Remover cada classe órfã, recarregando entre cada remoção**

Não fazer todas as remoções de uma vez — remover uma de cada vez, validar no browser. Se algo quebrar, reverter aquela única remoção.

- [ ] **Step 3: Atualizar AGENTS.md com convenções do sistema**

Adicionar seção em `AGENTS.md`:

```markdown
## Sistema responsivo (spec 2026-05-01)

Toda nova aba ou card visual deve usar os primitivos:

- `.app-container` — wrapper raiz da página (max-width 1920, padding fluido)
- `.dashboard-grid` — grid fluido auto-fit; cards de tamanhos diferentes via `.chart-card`, `.chart-card--md`, `.chart-card--lg`
- `.chart-card` — wrapper de qualquer card visual; modificadores `--md` (480px min) e `--lg` (640px min, span 2)
- `.table-wrap` — único local com scroll horizontal; primeira coluna pode ter `.sticky-col`
- `.chart-canvas-wrap` — envolve `<canvas>`; modificadores `--line`, `--bar`, `--pie`, `--heat`, `--dist`

Regras invioláveis:
- Sem `max-height: Xvh` em wrappers de conteúdo
- Sem scroll horizontal fora de `.table-wrap`
- Sem `body.style.zoom` (quebra hit detection do Chart.js)
- Sem media queries finas (1100-1280, 1280-1366); só os 4 breakpoints canônicos: 720 / 1100 / 1440 / 1920
- Tabelas grandes: marcar `<th>`/`<td>` com `data-tier="1|2|3|4"`

Spec completo: [docs/superpowers/specs/2026-05-01-responsive-design-system-design.md](docs/superpowers/specs/2026-05-01-responsive-design-system-design.md)
```

- [ ] **Step 4: Commit final**

```bash
git add static/style.css AGENTS.md
git commit -m "chore(css): remove regras órfãs pós-migração + documenta convenções em AGENTS.md"
```

---

# Validação final (não é uma task — é checklist pré-deploy)

Antes de pushar, abrir `https://harbour-fia-tracker.onrender.com` (após deploy) ou local com `python app.py` e percorrer:

- [ ] TABELA em 720, 1100, 1440, 1920 — tiers corretos, ATIVO sticky, botão `+ COLUNAS` funciona
- [ ] RISCO em 720, 1100, 1440, 1920 — 13 cards refluem sem buracos, tooltip colado no cursor
- [ ] GRÁFICOS — 6 charts mantêm aspect-ratio em todas as larguras
- [ ] CVM OFICIAL — 4 charts em grid, sem offset de tooltip
- [ ] ÍNDICES — treemap + 2 tabelas refluem
- [ ] HISTÓRICO — tabela com scroll horizontal só quando necessário
- [ ] EVENTOS, PRÉ-TRADE, CONFIGURAÇÕES — sem desalinhamento
- [ ] Topbar sticky em todas as abas
- [ ] Sem scroll horizontal acidental na página em nenhuma largura
- [ ] localStorage["carteira-force-all-cols"] persiste entre reloads
- [ ] Light/dark themes ainda funcionam

Se tudo passar: `git push origin main`.
