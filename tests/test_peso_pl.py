from app import compute_nav_total, build_portfolio_response


def test_compute_nav_total_soma_caixa_proventos_menos_custos():
    fc = {"caixa": 100.0, "proventos_a_receber": 50.0, "custos_provisionados": 10.0}
    assert compute_nav_total(1000.0, fc) == 1140.0


def test_compute_nav_total_campos_ausentes_ou_none_sao_zero():
    assert compute_nav_total(1000.0, {}) == 1000.0
    assert compute_nav_total(1000.0, {"caixa": None, "proventos_a_receber": None}) == 1000.0


def test_compute_nav_total_total_value_none():
    assert compute_nav_total(None, {"caixa": 200.0}) == 200.0


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


def test_cash_row_to_export_formata_colunas():
    from app import cash_row_to_export, EXPORT_HEADERS
    linha = cash_row_to_export({"label": "Caixa", "valor": 37293.5, "pct": 0.24})
    assert len(linha) == len(EXPORT_HEADERS)
    assert linha[0] == "Caixa"
    assert linha[3] == 0.24        # % Total
    assert linha[4] == 37293.5     # Valor Líquido
