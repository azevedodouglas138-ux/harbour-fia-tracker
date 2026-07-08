from app import compute_nav_total


def test_compute_nav_total_soma_caixa_proventos_menos_custos():
    fc = {"caixa": 100.0, "proventos_a_receber": 50.0, "custos_provisionados": 10.0}
    assert compute_nav_total(1000.0, fc) == 1140.0


def test_compute_nav_total_campos_ausentes_ou_none_sao_zero():
    assert compute_nav_total(1000.0, {}) == 1000.0
    assert compute_nav_total(1000.0, {"caixa": None, "proventos_a_receber": None}) == 1000.0


def test_compute_nav_total_total_value_none():
    assert compute_nav_total(None, {"caixa": 200.0}) == 200.0
