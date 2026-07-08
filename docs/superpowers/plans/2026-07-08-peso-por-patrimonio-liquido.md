# Peso das posições por PL completo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o peso de cada posição (`pct_total`) e todos os derivados (cota, concentração, risco, export) usarem o Patrimônio Líquido completo como denominador, e exibir Caixa e Proventos como duas linhas na tabela.

**Architecture:** Um helper único `compute_nav_total()` define o PL (`carteira + caixa + proventos − custos`). `build_portfolio_response` passa a receber `fund_config`, computa `pct_total = valor_liquido / PL` e devolve `cash_rows`. Cota, concentração e risco herdam a base PL. Desktop `app.js` alinha seu motor de recálculo intraday e passa a renderizar as duas linhas de caixa (o `mobile.js` já faz isso).

**Tech Stack:** Python 3.14 / Flask, pytest 9.0.3, JS vanilla (static/app.js, static/mobile.js).

## Global Constraints

- **PL** = `total_value + caixa + proventos_a_receber − custos_provisionados`, sempre via `compute_nav_total(total_value, fund_config)`.
- O array `rows` (usado em HHI, setor, beta, VaR, concentração) **NUNCA** contém caixa/proventos. Esses vão só em `cash_rows`.
- `build_portfolio_response(portfolio, prices, fundamentals, fund_config)` — `fund_config` é **obrigatório** (sem default), para que qualquer call-site esquecido falhe de forma visível em vez de silenciosamente voltar à base carteira.
- Idioma pt-BR na UI e mensagens.
- Toda mudança visual validada nos **2 temas**: Bloomberg dark + Harbour azul institucional.
- Testes com pytest; `from app import ...` funciona (app importa sem side-effects bloqueantes).
- Branch: `feat/peso-por-patrimonio-liquido`. Commits frequentes.
- Valores reais de referência hoje: `caixa=37293.5`, `proventos_a_receber=309000.0`, `custos_provisionados=0.0`.

---

### Task 1: Helper `compute_nav_total` e fim das 5 duplicações da fórmula do PL

**Files:**
- Modify: `app.py` — adiciona helper antes de `calculate_quota` (~linha 620); substitui inline em `app.py:632, 2083, 2144, 2378, 2731`.
- Test: `tests/test_peso_pl.py` (criar)

**Interfaces:**
- Produces: `compute_nav_total(total_value: float, fund_config: dict) -> float`

Nota: hoje `app.py:632` subtrai `custos`, mas `2083/2144/2378/2731` **não** subtraem. Após a troca, todos passam a subtrair `custos` — sem mudança numérica hoje (`custos=0`), e mais correto.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_peso_pl.py
from app import compute_nav_total


def test_compute_nav_total_soma_caixa_proventos_menos_custos():
    fc = {"caixa": 100.0, "proventos_a_receber": 50.0, "custos_provisionados": 10.0}
    assert compute_nav_total(1000.0, fc) == 1140.0


def test_compute_nav_total_campos_ausentes_ou_none_sao_zero():
    assert compute_nav_total(1000.0, {}) == 1000.0
    assert compute_nav_total(1000.0, {"caixa": None, "proventos_a_receber": None}) == 1000.0


def test_compute_nav_total_total_value_none():
    assert compute_nav_total(None, {"caixa": 200.0}) == 200.0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_peso_pl.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_nav_total'`

- [ ] **Step 3: Implementar o helper**

Inserir em `app.py` logo antes de `def calculate_quota` (~linha 623):

```python
def compute_nav_total(total_value, fund_config):
    """Patrimônio líquido do fundo: carteira + caixa + proventos a receber − custos provisionados.
    Fonte única da fórmula do PL (antes duplicada inline em vários endpoints)."""
    caixa     = fund_config.get("caixa") or 0
    proventos = fund_config.get("proventos_a_receber") or 0
    custos    = fund_config.get("custos_provisionados") or 0
    return (total_value or 0) + caixa + proventos - custos
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_peso_pl.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Substituir a duplicação em `calculate_quota` (app.py:631-632)**

De:
```python
    nav_carteira = sum(r.get("valor_liquido") or 0 for r in rows)
    nav_total    = nav_carteira + caixa + proventos - custos
```
Para:
```python
    nav_carteira = sum(r.get("valor_liquido") or 0 for r in rows)
    nav_total    = compute_nav_total(nav_carteira, fund_config)
```

- [ ] **Step 6: Substituir as 4 duplicações dos endpoints de risco/fx**

Em `app.py:2083`, `2144`, `2378`, `2731`, cada linha tem a forma:
```python
    nav = (pdata.get("total_value") or 0) + (fund_config.get("caixa") or 0) + (fund_config.get("proventos_a_receber") or 0)
```
Trocar cada uma por:
```python
    nav = compute_nav_total(pdata.get("total_value"), fund_config)
```

- [ ] **Step 7: Sanidade — import e regressão**

Run: `python -c "import app; print('OK')"` → Expected: `OK`
Run: `python -m pytest tests/test_peso_pl.py -q` → Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_peso_pl.py
git commit -m "feat: helper compute_nav_total (fonte unica da formula do PL)"
```

---

### Task 2: `build_portfolio_response` PL-based + `cash_rows` + todos os call-sites

**Files:**
- Modify: `app.py` — `build_portfolio_response` (696-782) e ~11 call-sites (`835, 954, 1397, 2082, 2142, 2376, 2661, 2729, 3064, 3089, 3690`).
- Test: `tests/test_peso_pl.py`

**Interfaces:**
- Consumes: `compute_nav_total` (Task 1)
- Produces: `build_portfolio_response(portfolio, prices, fundamentals, fund_config)` retornando, além do atual, as chaves `nav_total`, `caixa`, `proventos_a_receber`, `custos_provisionados`, e `cash_rows: list[{"label","valor","pct"}]`. `pct_total` de cada row passa a ser `valor_liquido / nav_total * 100`. `weighted_beta`/`weighted_upside` passam a dividir por `nav_total`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# adicionar em tests/test_peso_pl.py
from app import build_portfolio_response

def _portfolio():
    return {
        "fund_name": "TESTE FIA",
        "positions": [
            {"ticker": "AAA3", "yahoo_ticker": "AAA3.SA", "quantidade": 100, "categoria": "Acao"},
            {"ticker": "BBB4", "yahoo_ticker": "BBB4.SA", "quantidade": 100, "categoria": "Acao"},
        ],
    }

def _prices():
    return {
        "AAA3.SA": {"price": 10.0, "change_pct": 1.0},
        "BBB4.SA": {"price": 5.0, "change_pct": -2.0},
    }

def test_pct_total_usa_pl_completo():
    # carteira = 100*10 + 100*5 = 1500 ; PL = 1500 + 300 = 1800
    fc = {"caixa": 300.0, "proventos_a_receber": 0.0, "custos_provisionados": 0.0}
    data = build_portfolio_response(_portfolio(), _prices(), {}, fc)
    aaa = next(r for r in data["rows"] if r["ticker"] == "AAA3")
    assert aaa["pct_total"] == round(1000 / 1800 * 100, 2)   # 55.56
    assert data["nav_total"] == 1800.0

def test_cash_rows_presentes_e_soma_100():
    fc = {"caixa": 300.0, "proventos_a_receber": 0.0, "custos_provisionados": 0.0}
    data = build_portfolio_response(_portfolio(), _prices(), {}, fc)
    labels = [c["label"] for c in data["cash_rows"]]
    assert "Caixa" in labels and "Proventos a receber" in labels
    caixa_row = next(c for c in data["cash_rows"] if c["label"] == "Caixa")
    assert caixa_row["pct"] == round(300 / 1800 * 100, 2)    # 16.67
    total = sum(r["pct_total"] for r in data["rows"]) + sum(c["pct"] for c in data["cash_rows"])
    assert abs(total - 100.0) < 0.05

def test_cash_rows_nao_poluem_rows_de_calculo():
    fc = {"caixa": 300.0, "proventos_a_receber": 100.0, "custos_provisionados": 0.0}
    data = build_portfolio_response(_portfolio(), _prices(), {}, fc)
    assert all(r["ticker"] in ("AAA3", "BBB4") for r in data["rows"])
    assert len(data["rows"]) == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_peso_pl.py -q`
Expected: FAIL — `TypeError: build_portfolio_response() missing 1 required positional argument: 'fund_config'`

- [ ] **Step 3: Alterar a assinatura e o cálculo do `pct_total`**

Em `app.py:696`:
```python
def build_portfolio_response(portfolio, prices, fundamentals, fund_config):
```

Em `app.py:750-751`, computar o PL e usar como denominador:
```python
    nav_total = compute_nav_total(total_value, fund_config)
    for r in rows:
        r["pct_total"] = round(r["valor_liquido"] / nav_total * 100, 2) if r["valor_liquido"] and nav_total > 0 else None
```

- [ ] **Step 4: PL-ponderar `weighted_upside` e `weighted_beta`**

Em `app.py:753-755`, trocar o denominador `total_value` por `nav_total`:
```python
    weighted_upside = round(sum(r["upside_pct"] * r["valor_liquido"] / nav_total for r in rows if r["upside_pct"] and r["valor_liquido"]), 2) if nav_total > 0 else None
    beta_rows = [r for r in rows if r["beta"] is not None and r["valor_liquido"]]
    weighted_beta = round(sum(r["beta"] * r["valor_liquido"] / nav_total for r in beta_rows), 2) if beta_rows and nav_total > 0 else None
```
(Os `_wavg` de múltiplos em `app.py:757-761` **não mudam** — normalizam entre ações que têm o dado.)

- [ ] **Step 5: Construir `cash_rows` e expandir o `return`**

Inserir antes do `return` (~app.py:776), e acrescentar as chaves ao dict retornado (777-782):
```python
    caixa     = fund_config.get("caixa") or 0
    proventos = fund_config.get("proventos_a_receber") or 0
    custos    = fund_config.get("custos_provisionados") or 0
    _pl = nav_total if nav_total and nav_total > 0 else 1
    cash_rows = [
        {"label": "Caixa",               "valor": round(caixa, 2),     "pct": round(caixa / _pl * 100, 2)},
        {"label": "Proventos a receber", "valor": round(proventos, 2), "pct": round(proventos / _pl * 100, 2)},
    ]
    if custos:
        cash_rows.append({"label": "Custos provisionados", "valor": round(-custos, 2), "pct": round(-custos / _pl * 100, 2)})

    return {
        "fund_name": portfolio["fund_name"], "total_value": round(total_value, 2),
        "nav_total": round(nav_total, 2),
        "caixa": round(caixa, 2), "proventos_a_receber": round(proventos, 2),
        "custos_provisionados": round(custos, 2),
        "cash_rows": cash_rows,
        "weighted_upside": weighted_upside, "weighted_beta": weighted_beta,
        "weighted_stats": weighted_stats,
        "last_price_update": _brt_now().isoformat(), "rows": rows,
    }
```

- [ ] **Step 6: Rodar os testes de unidade (devem passar)**

Run: `python -m pytest tests/test_peso_pl.py -q`
Expected: PASS

- [ ] **Step 7: Atualizar os call-sites com `fund_config` já disponível ANTES da chamada**

`app.py:2082` (`api_risk_var`) — `fund_config` já existe em 2077. Trocar:
```python
    pdata       = build_portfolio_response(portfolio, prices, funds, fund_config)
```

`app.py:3064` (simulação, ANTES) — `fund_config` disponível:
```python
    pdata_antes = build_portfolio_response(portfolio, prices, fundamentals, fund_config)
```

`app.py:3089` (simulação, DEPOIS) — usar `fund_config_sim` (caixa pós-operação):
```python
    pdata_depois = build_portfolio_response(portfolio_sim, prices_sim, fundamentals, fund_config_sim)
```

- [ ] **Step 8: Atualizar os call-sites que precisam obter/reordenar `fund_config`**

Para cada um abaixo, garantir `fund_config = get_effective_fund_config()` **antes** da chamada e passá-lo:

`app.py:954` (`api_portfolio`) — mover o `get_effective_fund_config()` de 956 para antes de 954:
```python
    fund_config = get_effective_fund_config()
    data      = build_portfolio_response(portfolio, prices, funds, fund_config)
    # Attach quota data — always uses last closing from history as base
    data["quota"] = calculate_quota(data["rows"], fund_config, prices)
```

`app.py:835` (`get_export_data`):
```python
    funds     = get_cached_fundamentals(tickers)
    fund_config = get_effective_fund_config()
    return build_portfolio_response(portfolio, prices, funds, fund_config)
```

`app.py:1397`, `2142`, `2376`, `2729` — cada um tem `fund_config = get_effective_fund_config()` na linha logo APÓS a chamada; mover para antes e adicionar `fund_config` ao build. `app.py:2661` (`api_risk_concentration`) **não** tem `fund_config`; adicionar `fund_config = get_effective_fund_config()` antes da linha 2661 e passá-lo. `app.py:3690`: idem — garantir `fund_config` antes e passar.

- [ ] **Step 9: Sanidade — nenhum call-site esquecido**

Run: `python -c "import app; print('OK')"` → Expected: `OK`
Run: `git grep -n "build_portfolio_response(" app.py`
Expected: toda ocorrência de chamada (não a `def`) termina com `, fund_config)` ou `, fund_config_sim)`. Confirme visualmente que não sobrou nenhuma com 3 argumentos.

- [ ] **Step 10: Commit**

```bash
git add app.py tests/test_peso_pl.py
git commit -m "feat: pct_total e derivados por PL completo + cash_rows"
```

---

### Task 3: Concentração e risco com denominador PL

**Files:**
- Modify: `app.py` — `api_risk_concentration` (2661-2699), `_calcular_concentracao_pretrade` callers (3067, 3092), `_compute_component_var_by_beta` (2020-2041).
- Test: `tests/test_peso_pl.py`

**Interfaces:**
- Consumes: `compute_nav_total`, `build_portfolio_response(..., fund_config)`.

Nota: em `_compute_component_var_by_beta`, `contrib_pct` e `var_1d_rs` são **invariantes** ao denominador do peso (a razão `w*beta/w_beta` cancela). Só o `weight_pct` exibido muda. Portanto a mudança é de exibição.

- [ ] **Step 1: Teste — concentração setorial usa PL**

```python
# adicionar em tests/test_peso_pl.py
def test_concentracao_pretrade_usa_pl():
    from app import _calcular_concentracao_pretrade, compute_nav_total
    rows = [
        {"ticker": "AAA3", "yahoo_ticker": "AAA3.SA", "valor_liquido": 1000.0, "sector": "Tecnologia"},
        {"ticker": "BBB4", "yahoo_ticker": "BBB4.SA", "valor_liquido": 500.0,  "sector": "Financeiro"},
    ]
    fc = {"caixa": 300.0, "proventos_a_receber": 0.0, "custos_provisionados": 0.0}
    pl = compute_nav_total(1500.0, fc)  # 1800
    conc = _calcular_concentracao_pretrade(rows, pl)
    assert conc["por_ativo"]["AAA3.SA"] == round(1000 / 1800 * 100, 4)  # 55.5556
```

- [ ] **Step 2: Rodar e ver passar (a função já divide pelo denominador passado)**

Run: `python -m pytest tests/test_peso_pl.py::test_concentracao_pretrade_usa_pl -q`
Expected: PASS — confirma que passar o PL basta; a mudança é nos call-sites.

- [ ] **Step 3: Callers da concentração pré-trade passam o PL**

`app.py:3067`:
```python
    conc_antes  = _calcular_concentracao_pretrade(pdata_antes["rows"], compute_nav_total(total_antes, fund_config))
```
`app.py:3092`:
```python
    conc_depois  = _calcular_concentracao_pretrade(pdata_depois["rows"], compute_nav_total(total_depois, fund_config_sim)) if total_depois else {"por_ativo": {}, "por_setor": {}, "hhi": 0}
```

- [ ] **Step 4: `api_risk_concentration` — peso setorial e HHI por PL**

Em `app.py:2662`, após obter `pdata` (já com `fund_config`, Task 2), computar o PL:
```python
    total_value = pdata.get("total_value") or 0
    nav         = compute_nav_total(total_value, fund_config)
    if not total_value:
        return jsonify({"error": "Sem dados de portfólio"}), 400
```
Em `app.py:2678-2679`, trocar o denominador do peso setorial e do HHI de `total_value` para `nav`:
```python
        peso = data["valor"] / nav
        hhi += peso ** 2
```
(`top1/top3/top5` em 2696-2699 já herdam o PL via `pct_total`.)

- [ ] **Step 5: `_compute_component_var_by_beta` — weight_pct exibido por PL**

Em `app.py:2026` e `2031`, trocar `total_value` por `nav` no cálculo do peso `w`/`w_beta` (o `nav` já é parâmetro da função):
```python
    w_beta = sum(r["beta"] * r["valor_liquido"] / nav for r in rows_v)
```
```python
        w           = (r.get("valor_liquido") or 0) / nav
```

- [ ] **Step 6: Sanidade**

Run: `python -c "import app; print('OK')"` → Expected: `OK`
Run: `python -m pytest tests/test_peso_pl.py -q` → Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_peso_pl.py
git commit -m "feat: concentracao e component-VAR com denominador PL"
```

---

### Task 4: Desktop `app.js` — motor intraday por PL + duas linhas de caixa

**Files:**
- Modify: `static/app.js` — `onPriceUpdate` (~609-689) e `renderTable` (~221-281, tfoot ~308).

**Interfaces:**
- Consumes: resposta de `/api/portfolio` com `cash_rows`, `nav_total`, e `quota.{caixa,proventos_a_receber,custos_provisionados}`.

- [ ] **Step 1: Recompute intraday do `pct_total` por PL (app.js:625-629)**

De:
```javascript
    const total = portfolioData.rows.reduce((s,r) => s + (r.valor_liquido||0), 0);
    portfolioData.total_value = Math.round(total * 100) / 100;
    portfolioData.rows.forEach(r => {
      r.pct_total = total > 0 && r.valor_liquido ? Math.round(r.valor_liquido / total * 10000) / 100 : null;
    });
```
Para:
```javascript
    const total = portfolioData.rows.reduce((s,r) => s + (r.valor_liquido||0), 0);
    portfolioData.total_value = Math.round(total * 100) / 100;
    const q0 = portfolioData.quota || {};
    const navPL = total + (q0.caixa||0) + (q0.proventos_a_receber||0) - (q0.custos_provisionados||0);
    portfolioData.nav_total = Math.round(navPL * 100) / 100;
    portfolioData.rows.forEach(r => {
      r.pct_total = navPL > 0 && r.valor_liquido ? Math.round(r.valor_liquido / navPL * 10000) / 100 : null;
    });
```

- [ ] **Step 2: Provisão de performance por PL (app.js:668 e 684)**

Nas duas linhas que usam `* total` para `provisao_performance_rs`, trocar `total` por `navPL`:
```javascript
        portfolioData.quota.provisao_performance_rs  = Math.round(Math.max(0, alpha * feeRate) * navPL * 100) / 100;
```
(A `const navPL` do Step 1 está no mesmo escopo da função `onPriceUpdate`, acessível em ambos os ramos.)

- [ ] **Step 3: Renderizar duas linhas de caixa na tabela (renderTable)**

Após o loop que faz `tbody.appendChild(tr)` das posições (~app.js:281), acrescentar as linhas de `cash_rows`:
```javascript
    (portfolioData.cash_rows || []).forEach(c => {
      const tr = document.createElement('tr');
      tr.className = 'cash-row';
      tr.innerHTML = `
        <td></td>
        <td class="ticker">${c.label}</td>
        <td>—</td>
        <td>—</td>
        <td class="num">${c.pct!=null?fmt(c.pct,2)+'%':'—'}</td>
        <td class="num">${fmtBRL(c.valor)}</td>`;
      tbody.appendChild(tr);
    });
```
Ajustar o número de `<td>` para bater exatamente com as colunas da tabela desktop (conferir o `tr.innerHTML` das posições em ~247-280 e replicar a contagem de células, deixando vazias as colunas de métricas).

- [ ] **Step 4: Estilo `.cash-row` nos 2 temas**

Em `static/style.css`, adicionar um estilo discreto de subtotal para `.cash-row` (ex.: `font-style: italic; opacity: .85; border-top: 1px dashed var(--border);`) usando as variáveis de tema existentes, para funcionar em Bloomberg dark e Harbour.

- [ ] **Step 5: Verificação manual nos 2 temas**

Rodar o app e conferir a tabela:
```bash
python app.py
```
Abrir a carteira; confirmar: (a) as duas linhas "Caixa" e "Proventos a receber" aparecem ao fim; (b) `Σ %` das ações + caixa + proventos = 100%; (c) trocar entre os dois temas e validar contraste/legibilidade das linhas de caixa.
Expected: soma 100% e linhas legíveis nos dois temas. (Ver skill `superpowers:verification-before-completion`.)

- [ ] **Step 6: Commit**

```bash
git add static/app.js static/style.css
git commit -m "feat: desktop tabela por PL + linhas de caixa/proventos"
```

---

### Task 5: Export CSV/Excel inclui as linhas de caixa

**Files:**
- Modify: `app.py` — `api_export_csv` (~1037-1047) e `api_export_excel` (~1050-1061).
- Test: `tests/test_peso_pl.py`

**Interfaces:**
- Consumes: `get_export_data()` (retorna dict com `rows` e `cash_rows` após Task 2).

- [ ] **Step 1: Teste — export inclui linha de Caixa**

```python
# adicionar em tests/test_peso_pl.py
def test_cash_row_to_export_formata_colunas():
    from app import cash_row_to_export, EXPORT_HEADERS
    linha = cash_row_to_export({"label": "Caixa", "valor": 37293.5, "pct": 0.24})
    assert len(linha) == len(EXPORT_HEADERS)
    assert linha[0] == "Caixa"
    assert linha[3] == 0.24        # % Total
    assert linha[4] == 37293.5     # Valor Líquido
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_peso_pl.py::test_cash_row_to_export_formata_colunas -q`
Expected: FAIL — `ImportError: cannot import name 'cash_row_to_export'`

- [ ] **Step 3: Implementar `cash_row_to_export`**

Após `row_to_export` (~app.py:828), com o mesmo número de colunas de `EXPORT_HEADERS` (20), preenchendo só Ativo/%%/Valor:
```python
def cash_row_to_export(c):
    row = [None] * len(EXPORT_HEADERS)
    row[0] = c["label"]     # Ativo
    row[3] = c["pct"]       # % Total
    row[4] = c["valor"]     # Valor Líquido (R$)
    return row
```

- [ ] **Step 4: Escrever as linhas de caixa no CSV e no Excel**

Em `api_export_csv`, após `for r in data["rows"]: w.writerow(row_to_export(r))` (app.py:1044):
```python
    for c in data.get("cash_rows", []): w.writerow(cash_row_to_export(c))
```
Em `api_export_excel`, após `for r in data["rows"]: ws.append(row_to_export(r))` (app.py:1061):
```python
    for c in data.get("cash_rows", []): ws.append(cash_row_to_export(c))
```

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/test_peso_pl.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_peso_pl.py
git commit -m "feat: export CSV/Excel inclui linhas de caixa e proventos"
```

---

### Task 6: `mobile.js` — descontar custos na base do PL

**Files:**
- Modify: `static/mobile.js` — `renderCarteira` (~124-128).

- [ ] **Step 1: Netar `custos_provisionados` na base**

Em `static/mobile.js:124-128`:
```javascript
    const caixa = q.caixa || 0;
    const prov = q.proventos_a_receber || 0;
    const custos = q.custos_provisionados || 0;
    const equity = p.total_value || 0;
    // PL do fundo = ativos + caixa + proventos a receber − custos provisionados (base dos percentuais).
    const base = (equity + caixa + prov - custos) || 1;
```

- [ ] **Step 2: Verificação manual (mobile)**

Abrir a versão mobile (`/m` ou o template mobile) e confirmar que as linhas de Caixa/Proventos e os pesos das posições continuam corretos (custos=0 hoje → sem mudança visível; garante consistência quando ≠0).

- [ ] **Step 3: Commit**

```bash
git add static/mobile.js
git commit -m "fix: mobile desconta custos provisionados na base do PL"
```

---

## Self-Review

**Cobertura do spec:**
- Seção A (helper + build_portfolio_response + cash_rows) → Tasks 1, 2. ✓
- Seção B (cota herda; concentração; risco; weighted_beta/upside PL) → Tasks 2, 3. Cota: sem código (herda `pct_total`), coberto pelo teste de soma=100% e validação manual. ✓
- Seção C (app.js recompute + linhas; mobile custos; export) → Tasks 4, 5, 6. ✓
- Seção D (testes: soma 100%, cota diluída, concentração vs PL, regressão helper) → Steps de teste nas Tasks 1-5 + verificação manual Task 4. ✓

**Placeholder scan:** sem TBD/TODO; todo step tem código ou comando concreto. ✓

**Consistência de tipos/nomes:** `compute_nav_total(total_value, fund_config)`, `build_portfolio_response(..., fund_config)`, `cash_rows[{label,valor,pct}]`, `cash_row_to_export(c)` usados de forma idêntica entre tasks. ✓

## Decisão do gestor (RESOLVIDA)

**HHI de concentração: PL-based** (Task 3, Step 4) — **decidido, manter como está.**
Razão do gestor: o caixa faz parte do patrimônio do fundo e às vezes é representativo;
excluí-lo apontaria uma concentração *maior* que a real. Não abrir de novo — implementar
o Step 4 da Task 3 com denominador `nav` (PL) conforme escrito.
