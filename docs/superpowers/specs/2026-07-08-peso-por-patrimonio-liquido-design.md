# Design — Peso das posições por Patrimônio Líquido completo

**Data:** 2026-07-08
**Branch:** `feat/peso-por-patrimonio-liquido`
**Autor:** Douglas Azevedo (gestor) + Claude

## Problema

O `% TOTAL` de cada posição na tabela da carteira usa como denominador apenas a
**soma das posições em bolsa** (`total_value`), calculado em
[`build_portfolio_response`](../../../app.py) (`app.py:701-751`). Caixa e proventos
a receber — componentes fundamentais do patrimônio líquido do fundo — **não entram**
nesse cálculo. Consequência: os pesos superestimam a exposição real de cada ativo
frente ao PL, e o efeito cresce conforme o caixa cresce.

Além disso, o código já é **inconsistente**: alguns pontos usam a base "só ações"
(`total_value`) e outros já usam o PL cheio (`nav`). Exemplos:

| Local | Base usada hoje |
|---|---|
| `% TOTAL` da tabela + upside/beta ponderados | só ações (`total_value`) |
| Concentração por ativo/setor (limites, pré-trade) | só ações (`total_value`) |
| Retorno do fundo / cota estimada | só ações (via `pct_total`) |
| HHI de concentração (`app.py:3990`) | PL cheio (`nav`) |
| VaR / component-VAR | pesos por ações, R$ por PL cheio |

A fórmula do PL (`carteira + caixa + proventos − custos`) está **duplicada inline**
em ~5 lugares: `app.py:632, 2083, 2144, 2378, 2731`.

## Decisão de escopo (aprovada)

**Consistência total:** peso = `valor_liquido / PL` em **todo lugar** — tabela,
limites de concentração, métricas de risco (VaR/beta) e a cota estimada.

Onde `PL = Σ posições + caixa + proventos_a_receber − custos_provisionados`
(o mesmo `nav_total` que `calculate_quota` já computa hoje).

**Exibição:** o não-investido aparece como **duas linhas separadas** ao fim da
tabela — "Caixa" e "Proventos a receber" — cada uma com seu %.

## Arquitetura (Abordagem escolhida: denominador único no builder)

### A. Núcleo (backend)

1. **Novo helper `compute_nav_total(total_value, fund_config)`** — única fonte da
   fórmula do PL. Substitui as 5 duplicações inline (`app.py:632, 2083, 2144, 2378, 2731`).
   ```python
   def compute_nav_total(total_value, fund_config):
       caixa    = fund_config.get("caixa") or 0
       proventos = fund_config.get("proventos_a_receber") or 0
       custos   = fund_config.get("custos_provisionados") or 0
       return (total_value or 0) + caixa + proventos - custos
   ```

2. **`build_portfolio_response(portfolio, prices, fundamentals, fund_config)`** —
   nova assinatura recebendo `fund_config`. Calcula `nav_total` via o helper e define
   `pct_total = valor_liquido / nav_total`. Retorna também `nav_total`, `caixa`,
   `proventos`, `custos` e um campo novo `cash_rows`.

3. **`cash_rows`** — campo separado no dict de resposta, **nunca** dentro de `rows`
   (o `rows` de cálculo continua só com ações, preservando HHI/setor/beta/VaR/concentração).
   Estrutura:
   ```python
   cash_rows = [
       {"label": "Caixa",                "valor": caixa,     "pct": caixa/nav*100},
       {"label": "Proventos a receber",  "valor": proventos, "pct": proventos/nav*100},
   ]
   # linha condicional (só quando custos != 0):
   #   {"label": "Custos provisionados", "valor": -custos,   "pct": -custos/nav*100}
   ```

4. **~12 call sites** de `build_portfolio_response` passam `fund_config`. A maioria
   já o tem via `get_effective_fund_config()`; os demais fazem o load. Lista:
   `app.py:835, 954, 1397, 2082, 2142, 2376, 2661, 2729, 3064, 3089, 3690`.
   **Atenção ao fluxo de simulação pré-trade** (`app.py:3064-3092`): o `pdata_antes`
   (`3064`) usa `fund_config`; o `pdata_depois` (`3089`) usa `fund_config_sim`, que já
   ajusta o caixa pós-operação (`app.py:2994-3004`). Mesma regra para o denominador da
   concentração: `compute_nav_total(total_antes, fund_config)` e
   `compute_nav_total(total_depois, fund_config_sim)`.

### B. Propagação

- **Cota** (`calculate_quota`, `app.py:624`): **zero mudança de código.** Consome
  `pct_total` (`app.py:662`); como as somas agora dão <100%, a cota passa a diluir
  pelo caixa automaticamente. Caixa/proventos não entram no retorno porque estão em
  `cash_rows`, fora de `rows`. `calculate_quota` passa a usar `compute_nav_total`
  internamente (substitui a duplicação de `app.py:632`).

- **Concentração pré-trade** (`_calcular_concentracao_pretrade`, `app.py:2046`):
  callers (`app.py:3067, 3092`) passam o **PL** no lugar de `total_value`. Limites de
  enquadramento passam a ser checados contra o PL.

- **Risco** (`api_risk_var` `app.py:2063`, component-VAR `app.py:2020`,
  `api_risk_concentration` `app.py:2656`): denominador de peso alinhado ao PL. Já
  usam `nav` para os R$; alinhar o % ao mesmo `nav`.

- **`weighted_beta` e `weighted_upside`** (`app.py:753-755`): passam a ser
  **PL-ponderados** (dividem por `nav_total`) → "beta e upside efetivos do fundo"
  (caixa entra como beta 0 / upside 0, diluindo). Os múltiplos `_wavg` (P/L,
  EV/EBITDA, ROE, P/VPA, DY…) **ficam inalterados** — normalizados só entre ações que
  têm o dado; média de múltiplo incluindo caixa não faz sentido.

### C. Frontend + export

- **`static/app.js` e `static/mobile.js`**: renderizar duas linhas ("Caixa",
  "Proventos a receber") ao fim da tabela de posições, a partir de `cash_rows`. Sem
  setor; com % e valor; estilo visual de subtotal (distinto das posições).
- **Linha "Custos provisionados"** (negativa) só renderiza quando `custos != 0`
  (hoje = 0). Garante que os % exibidos somem 100%.
- **Validação obrigatória nos 2 temas** — Bloomberg dark + Harbour azul institucional.
- **Export CSV** (`row_to_export`/`EXPORT_HEADERS`, `app.py:817-828`): **incluir** as
  linhas de caixa/proventos para o CSV somar 100%.

### D. Testes / validação

1. `Σ pct(ações) + pct(caixa) + pct(proventos) = 100%` (± arredondamento), com os
   números reais (caixa 37.293,50; proventos 309.000; PL ≈ 15,5M).
2. Cota estimada reflete a diluição pelo caixa (efeito hoje ~2,2%).
3. Concentração por ativo/setor e limites agora checados contra o PL.
4. `compute_nav_total` retorna o mesmo valor dos 5 pontos que substituiu (regressão).
5. App rodando localmente: tabela validada nos dois temas.

## Consequência prática (números de hoje)

Caixa+proventos ≈ R$ 346k sobre PL ≈ R$ 15,5M (~2,2%). Pesos das ações caem ~2,2%
cada — ex.: MUTC34 de 37,37% → ~36,5%. Efeito pequeno hoje, correto e escalável.

## Fora de escopo (YAGNI)

- Flag de base configurável (`PL` vs `carteira`) — decisão já é "sempre PL".
- Rendimento intraday do caixa (CDI): mantido como 0% intraday, igual ao modelo atual.
- Refatoração não relacionada a peso/PL.
