# Sistema responsivo do Harbour Tracker — Design

**Data:** 2026-05-01
**Status:** Aprovado, aguardando plano de implementação

## 1. Contexto e problema

A plataforma cresceu organicamente: novas abas e cards foram adicionados sem
um sistema de layout coerente. Hoje:

- Larguras intermediárias (notebook em meia tela, ~720-1100px) ficam
  visualmente quebradas em várias abas.
- Larguras grandes (monitor externo 1920+) deixam conteúdo "esticado" sem
  aproveitamento real do espaço.
- O usuário precisa redimensionar a janela para encontrar a largura "certa"
  em que cada aba funciona.
- O commit `ec3c977` ("pente fino de responsividade") adicionou ~328 linhas
  de CSS com breakpoints novos (1100-1280px) e media queries que cobrem
  pontos específicos sem um sistema unificado, gerando inconsistência entre
  abas e dificultando manutenção.
- Tentativas anteriores de fix (zoom global, ResizeObserver, devicePixelRatio,
  etc.) atacaram sintomas em vez da raiz arquitetural.

A causa raiz é arquitetural: **falta um sistema de layout consistente**.
Cada aba tem sua grade própria, suas media queries próprias, suas regras de
tamanho de canvas próprias. O resultado é frágil em qualquer largura que
não seja a "típica" em que cada aba foi originalmente desenhada.

## 2. Objetivos e não-objetivos

**Objetivos:**

1. Estabelecer um sistema de layout único (tokens + primitivos) que toda
   aba use.
2. Garantir experiência fluida em todo o range 720px → 2560+px sem
   redimensionamento manual.
3. Resolver os bugs visuais conhecidos em TABELA (200) e RISCO (207).
4. Reduzir a quantidade de CSS específico por aba; centralizar regras
   responsivas em primitivos compartilhados.
5. Fornecer um caminho claro para abas futuras: declarar layout em termos
   dos primitivos, não escrever CSS novo.

**Não-objetivos:**

1. Suporte mobile/tablet (`< 720px`). O usuário não usa esses contextos.
2. Mudança visual gratuita. A estética Bloomberg Terminal (preto, laranja,
   monospace, denso) é mantida. Mudanças visuais são consequência de
   correção de layout, não estética.
3. Reescrita do CSS do zero. O sistema é introduzido em paralelo;
   migrações são feitas por aba, em commits revertíveis.
4. Suporte a temas/modos além dos atuais (light/dark já existem e
   permanecem como estão).

## 3. Fundações (tokens)

### 3.1 Breakpoints canônicos

```css
:root {
  --bp-sm:  720px;   /* meia tela (split com Excel/Bloomberg) */
  --bp-md:  1100px;  /* notebook estreito                     */
  --bp-lg:  1440px;  /* notebook tela cheia / monitor padrão  */
  --bp-xl:  1920px;  /* monitor externo grande                */
}
```

Estes são os ÚNICOS breakpoints permitidos em media queries do projeto.
Breakpoints adicionais (1100-1280, 1280-1366, etc.) introduzidos pelo
commit `ec3c977` são removidos — a fluidez vem dos primitivos
container-aware, não de media queries finas.

### 3.2 Container raiz

```css
.app-container {
  max-width: var(--bp-xl);   /* 1920px */
  margin: 0 auto;
  padding-inline: clamp(12px, 2vw, 32px);
}
```

Em monitores 2560+, o conteúdo permanece centralizado dentro de uma faixa
de até 1920px. Sem scroll horizontal acidental.

### 3.3 Spacing tokens

```css
:root {
  --gap-xs: 4px;
  --gap-sm: 8px;
  --gap-md: 12px;
  --gap-lg: 16px;
  --gap-xl: 24px;
}
```

Todo `padding`, `margin`, `gap` no projeto usa estes tokens. Valores
hard-coded (`padding: 7px 11px`, etc.) são substituídos pelos tokens mais
próximos durante a migração.

## 4. Primitivos de layout

Três componentes CSS que substituem as grades ad-hoc atuais.

### 4.1 `.dashboard-grid`

Grade fluida que se adapta automaticamente à largura disponível.

```css
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--card-min, 360px), 1fr));
  gap: var(--gap-md);
}
```

Comportamento esperado:

- 720-1100px: 1-2 colunas
- 1100-1440px: 2-3 colunas
- 1440-1920px: 3-4 colunas
- 1920+px: 4-5 colunas

`--card-min` pode ser overridado por aba se necessário (ex.: aba com
poucos cards muito largos pode usar `--card-min: 480px`).

### 4.2 `.chart-card` e modificadores

Wrapper único para qualquer card visual (KPI, gráfico, tabela mini).

```css
.chart-card {
  background: var(--surface);
  border: 1px solid var(--border);
  padding: var(--gap-md);
  display: flex;
  flex-direction: column;
  gap: var(--gap-sm);
  min-width: 0; /* permite shrink dentro do grid */
}

.chart-card--md { --card-min: 480px; }
.chart-card--lg {
  --card-min: 640px;
  grid-column: span 2;
}
```

Comportamento desejado para cards `--lg`: ocupam 2 colunas quando há
≥2 colunas no grid; em larguras onde só cabe 1 coluna do grid (telas
estreitas), o card ocupa 1 coluna sem deixar buraco. O mecanismo
exato (container queries, `minmax(min(640px, 100%), 1fr)`, ou outro)
é decisão de implementação validada na §11.

O `chart-card` tem header padrão (title + controles) e área de conteúdo.
A altura é determinada pelo conteúdo (gráfico tem aspect-ratio, tabela
mini cresce).

### 4.3 `.table-wrap`

ÚNICO container do projeto onde scroll horizontal é permitido.

```css
.table-wrap {
  overflow-x: auto;
  overflow-y: visible;
}

.table-wrap table {
  min-width: max-content;
}

.table-wrap .sticky-col {
  position: sticky;
  left: 0;
  background: var(--surface);
  z-index: 1;
}
```

Qualquer scroll horizontal fora de `.table-wrap` no projeto é considerado
bug.

## 5. TABELA (aba 200) — sistema de tiers

### 5.1 Marcação

Cada `<th>` e cada `<td>` correspondente recebem `data-tier="N"`:

| Tier | Largura mínima | Colunas (cumulativo) |
|------|----------------|----------------------|
| 1    | sempre visível | 9 cols essenciais    |
| 2    | ≥ 1100px       | +4 → 13 cols         |
| 3    | ≥ 1440px       | +5 → 18 cols         |
| 4    | ≥ 1920px       | +3 → 21 cols (todas) |

### 5.2 Distribuição das 21 colunas

**Tier 1 (sempre):** ATIVO (sticky), % TOTAL, VALOR LÍQ., PREÇO, VAR. DIA,
QTDE, LIQ. DIÁRIA, P. ALVO, UPSIDE.

**Tier 2 (1100+):** SETOR, ROE %, DIV. YIELD, MKT CAP.

**Tier 3 (1440+):** CATEG., P/L TRAIL., P/L FWD., LUCRO MI 26, BETA.

**Tier 4 (1920+):** PEG, EV/EBITDA, P/VPA.

### 5.3 Implementação

Tiers são controlados via media queries (não container queries, porque
a tabela precisa reagir à largura da viewport, não do container, dado o
sticky):

```css
@media (max-width: 1099px) {
  .carteira-table [data-tier="2"],
  .carteira-table [data-tier="3"],
  .carteira-table [data-tier="4"] { display: none; }
}
@media (max-width: 1439px) {
  .carteira-table [data-tier="3"],
  .carteira-table [data-tier="4"] { display: none; }
}
@media (max-width: 1919px) {
  .carteira-table [data-tier="4"] { display: none; }
}
```

### 5.4 Botão "+ COLUNAS"

Botão no header da tabela com toggle. Quando ativo:

```js
document.body.dataset.forceAllCols = 'true';
localStorage.setItem('carteira-force-all-cols', 'true');
```

CSS sobrescreve os display:none:

```css
body[data-force-all-cols="true"] .carteira-table [data-tier] {
  display: revert;
}
```

Estado persiste em localStorage, mas com `clamp` por sanidade: se a
viewport ficar < 720px (raríssimo no uso real), força reset para evitar
tabela de 21 colunas em janela minúscula.

### 5.5 Sticky ATIVO

Coluna ATIVO recebe class `sticky-col` (definida em §4.3). Ao rolar
horizontalmente, ela fica visível na borda esquerda.

## 6. RISCO (aba 207) — grid intrínseco

### 6.1 Reclassificação dos 13 cards

| Card                       | Modificador        | Min-width |
|----------------------------|--------------------|-----------|
| VaR / CVaR                 | `.chart-card`      | 360px     |
| Sortino / Calmar           | `.chart-card`      | 360px     |
| Liquidez                   | `.chart-card`      | 360px     |
| Concentração Setorial      | `.chart-card`      | 360px     |
| Beta Rolante               | `.chart-card--md`  | 480px     |
| Tracking Error             | `.chart-card--md`  | 480px     |
| Capture (Up/Down)          | `.chart-card--md`  | 480px     |
| Rolling Sharpe/Sortino     | `.chart-card--md`  | 480px     |
| Exposição Cambial          | `.chart-card--md`  | 480px     |
| Stress Test                | `.chart-card--lg`  | 640px, span 2 |
| Matriz de Correlação       | `.chart-card--lg`  | 640px, span 2 |
| Risk Attribution           | `.chart-card--lg`  | 640px, span 2 |
| Distribuição de Retornos   | `.chart-card--lg`  | 640px, span 2 |

### 6.2 Estrutura HTML

A estrutura atual de 7 `.risk-row` (cada uma com 2 cards) é substituída
por um único `.dashboard-grid` contendo os 13 cards diretamente.

```html
<div class="tab-content" id="tab-risk">
  <div class="dashboard-grid risk-dashboard">
    <div class="chart-card" id="risk-var-card">…</div>
    <div class="chart-card" id="risk-sortino-card">…</div>
    …
    <div class="chart-card--lg" id="risk-corr-card">…</div>
    …
  </div>
</div>
```

A ordem dos cards no HTML define a ordem de leitura (importante porque o
grid auto-fit preserva ordem). Sugestão:

1. KPIs principais primeiro: VaR, Sortino/Calmar, Liquidez, Concentração
2. Gráficos médios: Beta, TE, Capture, Rolling, FX
3. Cards grandes ao final: Stress, Correlação, Attribution, Distribuição

Isso garante que em telas estreitas o usuário vê os números importantes
sem rolar muito, e os cards grandes (que ficam de página inteira) vêm
depois.

### 6.3 Zero media query nesta aba

Todo o reflow da aba RISCO sai do `auto-fit` + `span 2`. Isso é
intencional: prova que o sistema funciona sem patches específicos.

## 7. Gráficos — aspect-ratios canônicos

Todo `<canvas>` de Chart.js é envolto em wrapper com aspect-ratio fixo +
limites de altura. Chart.js usa `responsive: true` +
`maintainAspectRatio: false`, deixando o wrapper ditar a dimensão.

```css
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
```

Mapeamento dos canvas atuais → modificadores:

| Canvas              | Modificador                   |
|---------------------|-------------------------------|
| history-chart       | `.chart-canvas-wrap--line`    |
| sector-chart        | `.chart-canvas-wrap--pie`     |
| upside-chart        | `.chart-canvas-wrap--bar`     |
| dd-chart            | `.chart-canvas-wrap--line`    |
| vol-chart           | `.chart-canvas-wrap--line`    |
| attrib-chart        | `.chart-canvas-wrap--bar`     |
| risk-beta-chart     | `.chart-canvas-wrap--line`    |
| risk-rolling-…      | `.chart-canvas-wrap--line`    |
| risk-dist-chart     | `.chart-canvas-wrap--dist`    |
| idx-treemap-canvas  | `.chart-canvas-wrap--heat`    |
| cvm-chart-pl        | `.chart-canvas-wrap--line`    |
| cvm-chart-cota      | `.chart-canvas-wrap--line`    |
| cvm-chart-fluxo     | `.chart-canvas-wrap--bar`     |
| cvm-chart-cotst     | `.chart-canvas-wrap--line`    |

## 8. Scroll & overflow

### 8.1 Regras

1. Scroll vertical: APENAS na página inteira. Nenhum wrapper de conteúdo
   tem `max-height: Xvh` ou `overflow-y: scroll`.
2. Scroll horizontal: APENAS dentro de `.table-wrap`.
3. Topbar (cota + abas): `position: sticky; top: 0; z-index: …`.
4. Modais: ao abrir, adicionam `overflow: hidden` no `<body>` para
   travar scroll do fundo.
5. Container raiz nunca passa de 1920px (§3.2).

### 8.2 Auditoria necessária

Durante a Fase 1, fazer grep do projeto por:

- `max-height:` em CSS → revisar cada caso, manter só onde é semântico
  (ex.: dropdown limitado a 300px de altura)
- `overflow-y` / `overflow-x` → idem
- `vh` em CSS → idem (provavelmente todos os usos em wrappers de
  conteúdo são removidos)

## 9. Sweep das abas (ordem de aplicação)

Cada aba é refatorada em commit próprio para permitir revert pontual.

| # | Aba         | O que aplicar                                              | Esforço |
|---|-------------|------------------------------------------------------------|---------|
| 1 | TABELA      | Sistema de tiers + sticky + botão `+ COLUNAS`              | Alto    |
| 2 | RISCO       | Grid intrínseco + reclassificar 13 cards                   | Médio   |
| 3 | GRÁFICOS    | `.dashboard-grid` + chart-canvas-wrap                      | Baixo   |
| 4 | CVM OFICIAL | `.cvm-charts-grid` → `.dashboard-grid` + canvas-wrap       | Baixo   |
| 5 | ÍNDICES     | `.dashboard-grid` + chart-canvas-wrap (treemap)            | Médio   |
| 6 | HISTÓRICO   | `.table-wrap` simples (4 colunas, sem tiers)               | Baixo   |
| 7 | EVENTOS     | `.dashboard-grid` para listagem de eventos                 | Médio   |
| 8 | PRÉ-TRADE   | `.dashboard-grid` + form-grid                              | Médio   |
| 9 | CONFIGURAÇÕES | form-grid responsivo                                     | Baixo   |

## 10. Fases de implementação

### Fase 1 — Foundation (invisível ao usuário)

1. Adicionar tokens CSS (breakpoints, container, spacing) em
   `static/style.css` no topo, junto às outras `:root` vars.
2. Adicionar primitivos `.dashboard-grid`, `.chart-card`,
   `.chart-card--md`, `.chart-card--lg`, `.table-wrap`,
   `.chart-canvas-wrap` e modificadores.
3. Adicionar `.app-container` e wrapping em `index.html`.
4. Auditoria de scroll/overflow (§8.2): remover `max-height: Xvh` e
   `overflow` zumbis.
5. Remover media queries do commit `ec3c977` que ficaram redundantes
   com o sistema novo (a maioria — checkpoints intermediários
   1100-1280, 1280-1366, etc. somem).

Critério de saída: nenhuma regressão visível em nenhuma aba; CSS
diff é majoritariamente "adições + remoções de blocos antigos".

### Fase 2 — Críticas

6. Refactor TABELA com sistema de tiers + sticky + botão `+ COLUNAS`.
7. Refactor RISCO com grid intrínseco + reclassificação dos 13 cards.

### Fase 3 — Sweep

Aplicar o sistema nas 7 abas restantes, 1 commit por aba, na ordem
da §9.

### Fase 4 — Cleanup

8. Remover qualquer CSS órfão (regras que sobraram sem uso após
   migração).
9. Atualizar AGENTS.md com convenções do novo sistema (referência
   rápida pra futuras adições de aba).

## 11. Validação

Cada PR (cada aba) é validado contra checklist nas 4 larguras
canônicas:

- **720px**: meia tela. Tudo funciona, sem scroll horizontal acidental.
  Tabela mostra apenas Tier 1.
- **1100px**: notebook estreito. Tier 2 da tabela aparece. Cards do
  RISCO em 2-3 colunas.
- **1440px**: notebook tela cheia. Tier 3. RISCO em 3 colunas com
  cards `--lg` em span 2.
- **1920px**: monitor grande. Tier 4 (todas as 21 cols). RISCO em
  4 colunas.

Para cada largura, verificar:

- Sem scroll horizontal acidental
- Topbar sticky funcional
- Tooltips dos gráficos colados no cursor (não voltar a regredir)
- Sem sobreposição de elementos
- Sem espaçamento esquisito (gap inconsistente)

## 12. Riscos e mitigações

**R1: Tabela com `position: sticky` quebrar em alguns navegadores.**
Mitigação: testar em Chrome (alvo principal), Edge, Firefox antes do
merge. Fallback: remover sticky em browsers que não suportam — degrada
para scroll horizontal sem coluna fixa, mas tabela continua funcional.

**R2: `auto-fit` com `span 2` produzir espaços vazios em larguras
intermediárias.** Mitigação: testar especificamente em 1100px e
1440px. Se aparecer "buraco", ajustar `--card-min` dos cards `--lg` ou
considerar `auto-fill` em vez de `auto-fit`.

**R3: Migração introduzir regressão visual.** Mitigação: 1 commit por
aba; cada commit é revertível independentemente. Validação manual
nas 4 larguras antes de cada commit.

**R4: Botão "+ COLUNAS" + localStorage gerar estado órfão (igual ao
caso `terminal-font-scale` que vivemos).** Mitigação: o estado é só
um boolean (`true` ou ausente); sem valores numéricos que possam
desconfigurar a UI; remoção do feature no futuro só requer apagar a
chave.
