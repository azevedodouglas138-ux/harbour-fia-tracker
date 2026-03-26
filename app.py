import base64
import csv
import io
import json
import os
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

import yfinance as yf
from flask import Flask, Response, jsonify, render_template, request, send_file, session, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

LOGIN_USER  = os.environ.get("LOGIN_USER", "admin")
LOGIN_PASS  = os.environ.get("LOGIN_PASSWORD", "")
VIEWER_USER = os.environ.get("VIEWER_USER", "")
VIEWER_PASS = os.environ.get("VIEWER_PASSWORD", "")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")   # "owner/repo"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

def _github_push(relative_path, content_str, commit_msg):
    """Push a single file to GitHub. Called in a background thread."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        import requests as req
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{relative_path}"
        r   = req.get(api_url, headers=headers, timeout=10)
        sha = r.json().get("sha") if r.ok else None
        payload = {
            "message": commit_msg,
            "content": base64.b64encode(content_str.encode("utf-8")).decode(),
            "branch":  GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        resp = req.put(api_url, json=payload, headers=headers, timeout=15)
        if not resp.ok:
            print(f"[github_push] {relative_path} → {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[github_push] error: {e}")

def github_push_async(relative_path, content_str, commit_msg):
    """Fire-and-forget GitHub file push (non-blocking)."""
    t = threading.Thread(target=_github_push,
                         args=(relative_path, content_str, commit_msg),
                         daemon=True)
    t.start()
PORTFOLIO_FILE      = os.path.join(DATA_DIR, "portfolio.json")
CACHE_FILE          = os.path.join(DATA_DIR, "cache.json")
FUND_CONFIG_FILE    = os.path.join(DATA_DIR, "fund_config.json")
QUOTA_HISTORY_FILE  = os.path.join(DATA_DIR, "quota_history.json")
VIEWER_CONFIG_FILE  = os.path.join(DATA_DIR, "viewer_config.json")

_price_cache = {"data": {}, "expires_at": 0}
FUNDAMENTALS_TTL = 4 * 3600
HISTORY_TTL      = 4 * 3600
STOCK_HIST_TTL   = 3600

RANGE_TO_PERIOD = {
    "1S": {"period": "5d"},
    "1M": {"period": "1mo"},
    "3M": {"period": "3mo"},
    "6M": {"period": "6mo"},
    "1A": {"period": "1y"},
}

SECTOR_PT = {
    "Energy": "Energia", "Financial Services": "Serv. Financeiros",
    "Real Estate": "Imobiliário", "Consumer Cyclical": "Consumo Cíclico",
    "Consumer Defensive": "Consumo Básico", "Healthcare": "Saúde",
    "Technology": "Tecnologia", "Industrials": "Industriais",
    "Basic Materials": "Mat. Básicos", "Communication Services": "Comunicação",
    "Utilities": "Utilidades",
}

# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def load_portfolio():
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_portfolio(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    github_push_async("data/portfolio.json", content, "chore: update portfolio.json via UI")

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cache(data):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_fund_config():
    defaults = {
        "quota_fechamento": 0, "data_fechamento": "",
        "num_cotas": None, "caixa": 0,
        "proventos_a_receber": 0, "custos_provisionados": 0,
        "performance_fee_rate": 20, "performance_fee_acumulada_rs": 0,
    }
    if not os.path.exists(FUND_CONFIG_FILE):
        return defaults
    with open(FUND_CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {**defaults, **data}

def save_fund_config(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(FUND_CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    github_push_async("data/fund_config.json", content, "chore: update fund_config.json via UI")

def load_quota_history():
    if not os.path.exists(QUOTA_HISTORY_FILE):
        return []
    with open(QUOTA_HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_quota_history(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(QUOTA_HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    github_push_async("data/quota_history.json", content, "chore: update quota_history.json via auto-close")

def get_effective_fund_config():
    """Returns fund_config, overriding quota_fechamento/data_fechamento with the last history entry."""
    config = load_fund_config()
    history = load_quota_history()
    if history:
        last = history[-1]
        config["quota_fechamento"] = last["cota_fechamento"]
        config["data_fechamento"]  = last["data"]
    return config

_VIEWER_CONFIG_DEFAULTS = {
    "tab_table":     True,
    "tab_charts":    True,
    "tab_config":    True,
    "tab_history":   True,
    "tab_macro":     True,
    "tab_watchlist": False,
    "tab_screener":  False,
}

def load_viewer_config():
    if not os.path.exists(VIEWER_CONFIG_FILE):
        return dict(_VIEWER_CONFIG_DEFAULTS)
    with open(VIEWER_CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {**_VIEWER_CONFIG_DEFAULTS, **data}

def save_viewer_config(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(VIEWER_CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    github_push_async("data/viewer_config.json", content, "chore: update viewer_config.json via UI")

# ---------------------------------------------------------------------------
# Price fetching — always includes ^BVSP
# ---------------------------------------------------------------------------

def fetch_prices(tickers):
    all_fetch = list(set(list(tickers) + ["^BVSP"]))
    result = {}
    for ticker in all_fetch:
        try:
            info = yf.Ticker(ticker).fast_info
            price = info.last_price
            prev  = info.previous_close
            result[ticker] = {
                "price":      round(price, 2) if price else None,
                "change_pct": round((price - prev) / prev * 100, 2) if price and prev else None,
            }
        except Exception as e:
            result[ticker] = {"price": None, "change_pct": None, "error": str(e)}
    return result

def get_cached_prices(tickers):
    now = time.time()
    if now < _price_cache["expires_at"]:
        return _price_cache["data"]
    data = fetch_prices(tickers)
    _price_cache["data"] = data
    _price_cache["expires_at"] = now + 30
    return data

def invalidate_price_cache():
    _price_cache["expires_at"] = 0

# ---------------------------------------------------------------------------
# Fundamentals (weekly cache)
# ---------------------------------------------------------------------------

def _round(val, d):
    try: return round(float(val), d) if val is not None else None
    except: return None

# BDRs: mapa ticker .SA → ticker americano subjacente (para buscar forwardPE/pegRatio)
BDR_UNDERLYING = {
    "MUTC34.SA": "MU",
    "NVDC34.SA": "NVDA",
    "A1MD34.SA": "AMD",
    "MSFT34.SA": "MSFT",
    "GOGL34.SA": "GOOGL",
    "AAPL34.SA": "AAPL",
    "AMZO34.SA": "AMZN",
    "META34.SA": "META",
    "TSLA34.SA": "TSLA",
}

def fetch_fundamentals(tickers):
    # Busca fundamentals dos subjacentes americanos de BDRs de uma vez
    us_tickers = list({BDR_UNDERLYING[t] for t in tickers if t in BDR_UNDERLYING})
    us_info = {}
    for ut in us_tickers:
        try:
            us_info[ut] = yf.Ticker(ut).info
        except Exception:
            us_info[ut] = {}

    result = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            dy, roe, beta, ev_ebitda = info.get("dividendYield"), info.get("returnOnEquity"), info.get("beta"), info.get("enterpriseToEbitda")
            sector_en = info.get("sector")

            # Para BDRs: complementa forwardPE e pegRatio do ticker americano subjacente
            us = us_info.get(BDR_UNDERLYING.get(ticker), {})
            forward_pe = _round(info.get("forwardPE") or us.get("forwardPE"), 2)
            peg_ratio  = _round(info.get("pegRatio")  or us.get("pegRatio"),  2)

            result[ticker] = {
                "trailing_pe":         _round(info.get("trailingPE"), 2),
                "forward_pe":          forward_pe,
                "peg_ratio":           peg_ratio,
                "price_to_book":       _round(info.get("priceToBook"), 1),
                "dividend_yield":      round(dy if dy > 1 else dy * 100, 2) if dy else None,
                "market_cap":          info.get("marketCap"),
                "fifty_two_week_high": _round(info.get("fiftyTwoWeekHigh"), 2),
                "fifty_two_week_low":  _round(info.get("fiftyTwoWeekLow"), 2),
                "short_name":          info.get("shortName") or info.get("longName"),
                "beta":                _round(beta, 2),
                "enterprise_to_ebitda": _round(ev_ebitda, 1),
                "return_on_equity":    round(roe * 100, 1) if roe is not None else None,
                "sector":              SECTOR_PT.get(sector_en, sector_en) if sector_en else None,
            }
        except Exception as e:
            result[ticker] = {"error": str(e)}
    return result

def get_cached_fundamentals(tickers):
    cache = load_cache()
    now = time.time()
    # Invalida se expirado OU se peg_ratio ainda não está no cache (campo novo)
    if any(now > cache.get(t, {}).get("expires_at", 0) or "peg_ratio" not in cache.get(t, {}) for t in tickers):
        fresh = fetch_fundamentals(tickers)
        for t, d in fresh.items():
            cache[t] = {**d, "expires_at": now + FUNDAMENTALS_TTL}
        save_cache(cache)
    return {t: {k: v for k, v in cache.get(t, {}).items() if k != "expires_at"} for t in tickers}

# ---------------------------------------------------------------------------
# Portfolio history vs IBOV
# ---------------------------------------------------------------------------

def compute_portfolio_history(positions, days=90):
    import pandas as pd
    tickers  = [p["yahoo_ticker"] for p in positions]
    qty_map  = {p["yahoo_ticker"]: p["quantidade"] for p in positions}
    all_tick = tickers + ["^BVSP"]
    end   = datetime.now()
    start = end - timedelta(days=days + 45)
    try:
        df = yf.download(all_tick, start=start.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
    except Exception as e:
        return {"series": [], "error": str(e)}
    if df.empty:
        return {"series": []}
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": all_tick[0]})
    close = close.ffill()
    port  = sum(close[t] * qty_map.get(t, 0) for t in tickers if t in close.columns)
    ibov  = close["^BVSP"] if "^BVSP" in close.columns else None
    valid = port.dropna()
    valid = valid[valid > 0].tail(days)
    if len(valid) == 0:
        return {"series": []}
    base_p = float(valid.iloc[0])
    base_i = float(ibov.loc[valid.index[0]]) if ibov is not None and valid.index[0] in ibov.index else None
    series = []
    for dt in valid.index:
        pv = float(valid[dt])
        in_ = None
        if ibov is not None and base_i and dt in ibov.index:
            iv = ibov[dt]
            if iv == iv: in_ = round(float(iv) / base_i * 100, 2)
        series.append({"date": dt.strftime("%Y-%m-%d"),
                       "portfolio": round(pv / base_p * 100, 2) if base_p else None,
                       "portfolio_abs": round(pv, 2), "ibov": in_})
    return {"series": series}

def get_cached_history(positions, days=90):
    cache = load_cache()
    now   = time.time()
    key   = f"history_{days}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return cache[key]["data"]
    data = compute_portfolio_history(positions, days)
    cache[key] = {"data": data, "expires_at": now + HISTORY_TTL}
    save_cache(cache)
    return data

def invalidate_history_cache():
    cache = load_cache()
    for k in list(cache.keys()):
        if k.startswith("history_"): del cache[k]
    save_cache(cache)

def compute_stock_history(yahoo_ticker, range_key):
    """Fetch price history for a single ticker + ^BVSP comparison, indexed to 100."""
    import pandas as pd
    if range_key == "YTD":
        kwargs = {"start": f"{datetime.now().year}-01-01"}
    else:
        kwargs = RANGE_TO_PERIOD.get(range_key, {"period": "1mo"})
    try:
        raw = yf.download(
            [yahoo_ticker, "^BVSP"],
            progress=False,
            auto_adjust=True,
            **kwargs,
        )
    except Exception as e:
        return {"series": [], "error": str(e)}
    if raw is None or (hasattr(raw, 'empty') and raw.empty):
        return {"series": []}
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    close = close.ffill()
    if yahoo_ticker not in close.columns:
        return {"series": [], "error": "ticker not found"}
    stock = close[yahoo_ticker].dropna()
    ibov  = close["^BVSP"] if "^BVSP" in close.columns else None
    if stock.empty:
        return {"series": []}
    base_s = float(stock.iloc[0])
    base_i = float(ibov.iloc[0]) if ibov is not None and not ibov.empty else None
    try:
        fi = yf.Ticker(yahoo_ticker).fast_info
        w52_high = round(float(fi.fifty_two_week_high), 2) if fi.fifty_two_week_high else None
        w52_low  = round(float(fi.fifty_two_week_low),  2) if fi.fifty_two_week_low  else None
    except Exception:
        w52_high = w52_low = None
    series = []
    for dt in stock.index:
        sv = float(stock[dt])
        iv = None
        if ibov is not None and base_i and dt in ibov.index:
            raw_iv = float(ibov[dt])
            if raw_iv == raw_iv:  # not NaN
                iv = round(raw_iv / base_i * 100, 2)
        series.append({
            "date":    dt.strftime("%Y-%m-%d"),
            "price":   round(sv, 2),
            "indexed": round(sv / base_s * 100, 2) if base_s else None,
            "ibov":    iv,
        })
    period_return = round((float(stock.iloc[-1]) / base_s - 1) * 100, 2) if base_s else None
    ibov_return   = round((series[-1]["ibov"] / 100 - 1) * 100, 2) if series and series[-1]["ibov"] else None
    vs_ibov = round(period_return - ibov_return, 2) if period_return is not None and ibov_return is not None else None
    return {
        "series":        series,
        "ticker":        yahoo_ticker,
        "period_return": period_return,
        "ibov_return":   ibov_return,
        "vs_ibov":       vs_ibov,
        "w52_high":      w52_high,
        "w52_low":       w52_low,
        "base_price":    round(base_s, 2),
    }

def get_cached_stock_history(yahoo_ticker, range_key):
    cache = load_cache()
    now   = time.time()
    key   = f"stock_hist_{yahoo_ticker}_{range_key}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return cache[key]["data"]
    data = compute_stock_history(yahoo_ticker, range_key)
    cache[key] = {"data": data, "expires_at": now + STOCK_HIST_TTL}
    save_cache(cache)
    return data

# ---------------------------------------------------------------------------
# Market hours check (BRT = UTC-3, sem horário de verão desde 2019)
# ---------------------------------------------------------------------------

def is_market_open():
    """B3: seg-sex, 10:00–17:30 BRT."""
    brt = datetime.utcnow() - timedelta(hours=3)
    if brt.weekday() >= 5:          # sábado=5, domingo=6
        return False
    t = brt.hour * 60 + brt.minute  # minutos desde meia-noite
    return 10 * 60 <= t < 17 * 60 + 30

# ---------------------------------------------------------------------------
# Quota & Performance Fee calculation
# ---------------------------------------------------------------------------

def calculate_quota(rows, fund_config, prices):
    quota_fech = fund_config.get("quota_fechamento") or 0
    num_cotas  = fund_config.get("num_cotas")
    caixa      = fund_config.get("caixa") or 0
    proventos  = fund_config.get("proventos_a_receber") or 0
    custos     = fund_config.get("custos_provisionados") or 0
    fee_rate   = (fund_config.get("performance_fee_rate") or 20) / 100

    nav_carteira = sum(r.get("valor_liquido") or 0 for r in rows)
    nav_total    = nav_carteira + caixa + proventos - custos

    # Fora do horário de mercado: exibe apenas o fechamento, sem variação intraday
    if not is_market_open():
        result = {
            "quota_fechamento":         quota_fech,
            "data_fechamento":          fund_config.get("data_fechamento", ""),
            "cota_estimada":            quota_fech if quota_fech else None,
            "variacao_pct":             0.0,
            "variacao_rs_por_cota":     0.0,
            "retorno_fundo_pct":        0.0,
            "retorno_ibov_pct":         0.0,
            "alpha_pct":                0.0,
            "provisao_performance_pct": 0.0,
            "provisao_performance_rs":  0.0,
            "nav_total":                round(nav_total, 2),
            "mercado_fechado":          True,
            "caixa": caixa, "proventos_a_receber": proventos,
            "custos_provisionados": custos, "num_cotas": num_cotas,
        }
        if num_cotas:
            result["variacao_total_rs"] = 0.0
        return result

    valid = [r for r in rows if r.get("pct_total") and r.get("var_dia_pct") is not None]
    retorno_carteira = sum((r["var_dia_pct"] / 100) * (r["pct_total"] / 100) for r in valid) if valid else 0.0

    ibov_data    = prices.get("^BVSP", {})
    ibov_ret_pct = ibov_data.get("change_pct") or 0
    ibov_ret     = ibov_ret_pct / 100

    alpha        = retorno_carteira - ibov_ret
    provisao_pct = max(0.0, alpha * fee_rate)

    provisao_rs  = provisao_pct * nav_total

    cota_est = quota_fech * (1 + retorno_carteira) if quota_fech else None

    result = {
        "quota_fechamento":        quota_fech,
        "data_fechamento":         fund_config.get("data_fechamento", ""),
        "cota_estimada":           round(cota_est, 8) if cota_est else None,
        "variacao_pct":            round(retorno_carteira * 100, 4),
        "variacao_rs_por_cota":    round(cota_est - quota_fech, 8) if cota_est else None,
        "retorno_fundo_pct":       round(retorno_carteira * 100, 4),
        "retorno_ibov_pct":        round(ibov_ret * 100, 4),
        "alpha_pct":               round(alpha * 100, 4),
        "provisao_performance_pct": round(provisao_pct * 100, 4),
        "provisao_performance_rs": round(provisao_rs, 2),
        "nav_total":               round(nav_total, 2),
        "mercado_fechado":         False,
        "caixa": caixa, "proventos_a_receber": proventos,
        "custos_provisionados": custos, "num_cotas": num_cotas,
    }
    if num_cotas and cota_est:
        result["variacao_total_rs"] = round((cota_est - quota_fech) * num_cotas, 2)
    return result

# ---------------------------------------------------------------------------
# Portfolio response builder
# ---------------------------------------------------------------------------

def build_portfolio_response(portfolio, prices, fundamentals):
    rows = []
    total_value = 0.0
    for pos in portfolio["positions"]:
        yahoo = pos["yahoo_ticker"]
        pd_   = prices.get(yahoo, {})
        fund  = fundamentals.get(yahoo, {})
        price = pd_.get("price")
        qtde  = pos["quantidade"]
        vl    = round(price * qtde, 2) if price else None
        if vl: total_value += vl
        pa    = pos.get("preco_alvo")
        upside = round((pa / price - 1) * 100, 2) if price and pa and price > 0 else None
        mc     = fund.get("market_cap")
        rows.append({
            "ticker": pos["ticker"], "yahoo_ticker": yahoo,
            "categoria": pos.get("categoria", "Acao"), "quantidade": qtde,
            "liq_diaria_mm": pos.get("liq_diaria_mm"),
            "lucro_mi_26":   pos.get("lucro_mi_26"),
            "preco_alvo": pa, "preco": price,
            "var_dia_pct": pd_.get("change_pct"),
            "valor_liquido": vl, "upside_pct": upside,
            "trailing_pe": fund.get("trailing_pe"), "forward_pe": fund.get("forward_pe"),
            "peg_ratio": fund.get("peg_ratio"),
            "price_to_book": fund.get("price_to_book"), "dividend_yield": fund.get("dividend_yield"),
            "market_cap_bi": round(mc / 1e9, 1) if mc else None,
            "week_high": fund.get("fifty_two_week_high"), "week_low": fund.get("fifty_two_week_low"),
            "short_name": fund.get("short_name"), "beta": fund.get("beta"),
            "enterprise_to_ebitda": fund.get("enterprise_to_ebitda"),
            "return_on_equity": fund.get("return_on_equity"),
            "sector": fund.get("sector") or pos.get("categoria", "Outros"),
        })
    for r in rows:
        r["pct_total"] = round(r["valor_liquido"] / total_value * 100, 2) if r["valor_liquido"] and total_value > 0 else None

    weighted_upside = round(sum(r["upside_pct"] * r["valor_liquido"] / total_value for r in rows if r["upside_pct"] and r["valor_liquido"]), 2) if total_value > 0 else None
    beta_rows = [r for r in rows if r["beta"] is not None and r["valor_liquido"]]
    weighted_beta = round(sum(r["beta"] * r["valor_liquido"] / total_value for r in beta_rows), 2) if beta_rows and total_value > 0 else None

    def _wavg(field):
        valid = [r for r in rows if r.get(field) is not None and r["valor_liquido"]]
        wt = sum(r["valor_liquido"] for r in valid)
        if not valid or wt == 0: return None
        return round(sum(r[field] * r["valor_liquido"] / wt for r in valid), 2)

    weighted_stats = {
        "w_trailing_pe":          _wavg("trailing_pe"),
        "w_forward_pe":           _wavg("forward_pe"),
        "w_peg_ratio":            _wavg("peg_ratio"),
        "w_enterprise_to_ebitda": _wavg("enterprise_to_ebitda"),
        "w_return_on_equity":     _wavg("return_on_equity"),
        "w_beta":                 weighted_beta,
        "w_price_to_book":        _wavg("price_to_book"),
        "w_dividend_yield":       _wavg("dividend_yield"),
        "w_var_dia_pct":          _wavg("var_dia_pct"),
        "w_upside_pct":           weighted_upside,
        "w_lucro_mi_26":          sum(r["lucro_mi_26"] for r in rows if r.get("lucro_mi_26")) or None,
    }

    return {
        "fund_name": portfolio["fund_name"], "total_value": round(total_value, 2),
        "weighted_upside": weighted_upside, "weighted_beta": weighted_beta,
        "weighted_stats": weighted_stats,
        "last_price_update": datetime.now().isoformat(), "rows": rows,
    }

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

EXPORT_HEADERS = [
    "Ativo","Categoria","Setor","% Total","Valor Líquido (R$)","Preço (R$)",
    "Var. Dia %","Quantidade","Liq. Diária (mm)",
    "P/L Trailing","P/L Forward","EV/EBITDA","ROE %","Beta",
    "Lucro mi 26","P/VPA","Div. Yield %","Mkt Cap (Bi R$)","Preço Alvo (R$)","Upside %",
]

def row_to_export(r):
    return [r["ticker"],r["categoria"],r.get("sector"),r["pct_total"],r["valor_liquido"],r["preco"],
            r["var_dia_pct"],r["quantidade"],r["liq_diaria_mm"],
            r["trailing_pe"],r["forward_pe"],r.get("enterprise_to_ebitda"),r.get("return_on_equity"),r.get("beta"),
            r["lucro_mi_26"],r["price_to_book"],r["dividend_yield"],r["market_cap_bi"],r["preco_alvo"],r["upside_pct"]]

def get_export_data():
    portfolio = load_portfolio()
    tickers   = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices    = get_cached_prices(tickers)
    funds     = get_cached_fundamentals(tickers)
    return build_portfolio_response(portfolio, prices, funds)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_PUBLIC = {"/login", "/logout"}

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)
    return decorated

@app.before_request
def require_login():
    if request.path in _PUBLIC:
        return
    if request.path.startswith("/static/"):
        return
    if request.path == "/api/quota-history/auto-close":
        return
    if not session.get("role"):
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        if LOGIN_PASS and u == LOGIN_USER and p == LOGIN_PASS:
            session["role"] = "admin"
            return redirect("/")
        if VIEWER_PASS and u == VIEWER_USER and p == VIEWER_PASS:
            session["role"] = "viewer"
            return redirect("/")
        error = "Usuário ou senha incorretos."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", role=session.get("role", "viewer"), viewer_config=load_viewer_config())

@app.route("/api/portfolio")
def api_portfolio():
    portfolio = load_portfolio()
    tickers   = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices    = get_cached_prices(tickers)
    funds     = get_cached_fundamentals(tickers)
    data      = build_portfolio_response(portfolio, prices, funds)
    # Attach quota data — always uses last closing from history as base
    fund_config  = get_effective_fund_config()
    data["quota"] = calculate_quota(data["rows"], fund_config, prices)
    return jsonify(data)

@app.route("/api/prices")
def api_prices():
    portfolio = load_portfolio()
    tickers   = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices    = get_cached_prices(tickers)
    funds     = get_cached_fundamentals(tickers)
    # Expose only the fields used in real-time refresh
    fund_slim = {t: {k: funds[t].get(k) for k in ("trailing_pe","forward_pe","peg_ratio")} for t in tickers}
    return jsonify({"prices": prices, "fundamentals": fund_slim, "timestamp": datetime.now().isoformat()})

@app.route("/api/fundamentals")
def api_fundamentals():
    portfolio = load_portfolio()
    tickers   = [p["yahoo_ticker"] for p in portfolio["positions"]]
    return jsonify({"fundamentals": get_cached_fundamentals(tickers)})

@app.route("/api/history")
def api_history():
    days = max(10, min(int(request.args.get("days", 90)), 365))
    portfolio = load_portfolio()
    return jsonify(get_cached_history(portfolio["positions"], days))

@app.route("/api/fund-config", methods=["GET"])
def api_get_fund_config(): return jsonify(load_fund_config())

@app.route("/api/fund-config", methods=["POST"])
@require_admin
def api_update_fund_config():
    payload = request.json
    config  = load_fund_config()
    for key in ["quota_fechamento","data_fechamento","num_cotas","caixa",
                "proventos_a_receber","custos_provisionados","performance_fee_rate","performance_fee_acumulada_rs"]:
        if key not in payload: continue
        val = payload[key]
        if key == "data_fechamento":
            config[key] = val
        elif val in (None, ""):
            config[key] = None
        else:
            try: config[key] = float(val)
            except: config[key] = val
    save_fund_config(config)
    invalidate_price_cache()
    return jsonify({"ok": True})

@app.route("/api/export/csv")
@require_admin
def api_export_csv():
    data   = get_export_data()
    output = io.StringIO()
    w      = csv.writer(output)
    w.writerow(EXPORT_HEADERS)
    for r in data["rows"]: w.writerow(row_to_export(r))
    output.seek(0)
    filename = f"harbour_fia_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.route("/api/export/excel")
@require_admin
def api_export_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    data = get_export_data()
    wb = Workbook(); ws = wb.active; ws.title = "Portfólio"
    hf = Font(bold=True, color="E0E3F0", name="Calibri")
    hfill = PatternFill(start_color="1A1D27", end_color="1A1D27", fill_type="solid")
    ws.append(EXPORT_HEADERS)
    for cell in ws[1]: cell.font = hf; cell.fill = hfill; cell.alignment = Alignment(horizontal="center")
    for r in data["rows"]: ws.append(row_to_export(r))
    for i, w_ in enumerate([8,9,18,8,16,10,9,12,15,11,11,9,7,7,11,11,7,10,13,14,9], 1):
        ws.column_dimensions[ws.cell(1,i).column_letter].width = w_
    ws.row_dimensions[1].height = 22
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    filename = f"harbour_fia_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/portfolio/update", methods=["POST"])
@require_admin
def api_update_position():
    payload = request.json
    ticker  = payload.get("ticker")
    if not ticker: return jsonify({"error": "ticker required"}), 400
    portfolio = load_portfolio()
    updated = False
    for pos in portfolio["positions"]:
        if pos["ticker"] == ticker:
            for field in ["quantidade","liq_diaria_mm","lucro_mi_26","preco_alvo"]:
                if field in payload:
                    val = payload[field]
                    pos[field] = float(val) if val not in (None,"") else None
            updated = True; break
    if not updated: return jsonify({"error": "ticker not found"}), 404
    save_portfolio(portfolio); invalidate_price_cache(); invalidate_history_cache()
    return jsonify({"ok": True})

@app.route("/api/portfolio/add", methods=["POST"])
@require_admin
def api_add_position():
    payload = request.json
    ticker  = payload.get("ticker","").upper().strip()
    if not ticker: return jsonify({"error": "ticker required"}), 400
    yahoo_ticker = ticker + ".SA"
    try:
        price = yf.Ticker(yahoo_ticker).fast_info.last_price
        if price is None: return jsonify({"error": f"Ticker {yahoo_ticker} não encontrado"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 400
    portfolio = load_portfolio()
    if any(p["ticker"] == ticker for p in portfolio["positions"]):
        return jsonify({"error": "Ticker já existe na carteira"}), 409
    def _f(k): v = payload.get(k); return float(v) if v not in (None,"") else None
    portfolio["positions"].append({
        "ticker": ticker, "yahoo_ticker": yahoo_ticker,
        "categoria": payload.get("categoria","Acao"),
        "quantidade": float(payload.get("quantidade",0)),
        "liq_diaria_mm": _f("liq_diaria_mm"), "lucro_mi_26": _f("lucro_mi_26"),
        "preco_alvo": _f("preco_alvo"),
    })
    save_portfolio(portfolio); invalidate_price_cache(); invalidate_history_cache()
    return jsonify({"ok": True})

@app.route("/api/portfolio/<ticker>", methods=["DELETE"])
@require_admin
def api_delete_position(ticker):
    portfolio = load_portfolio()
    before = len(portfolio["positions"])
    portfolio["positions"] = [p for p in portfolio["positions"] if p["ticker"] != ticker.upper()]
    if len(portfolio["positions"]) == before: return jsonify({"error": "ticker not found"}), 404
    save_portfolio(portfolio); invalidate_price_cache(); invalidate_history_cache()
    return jsonify({"ok": True})

@app.route("/api/quota-history/auto-close", methods=["POST"])
def api_auto_close():
    """Called by GitHub Actions at 17:35 BRT on weekdays to auto-register the closing NAV."""
    # Optional secret token check
    secret = os.environ.get("AUTO_CLOSE_SECRET", "")
    if secret:
        token = request.headers.get("X-Secret", "") or request.json.get("secret", "") if request.is_json else ""
        if token != secret:
            return jsonify({"error": "unauthorized"}), 401

    today = datetime.now().strftime("%Y-%m-%d")

    portfolio = load_portfolio()
    tickers   = [p["yahoo_ticker"] for p in portfolio["positions"]]
    invalidate_price_cache()
    prices    = fetch_prices(tickers)           # fresh, no cache
    funds     = get_cached_fundamentals(tickers)
    data      = build_portfolio_response(portfolio, prices, funds)
    fund_config = get_effective_fund_config()
    quota     = calculate_quota(data["rows"], fund_config, prices)

    cota_est = quota.get("cota_estimada")
    if not cota_est:
        return jsonify({"error": "cota estimada indisponível — preços não carregados"}), 500

    history = load_quota_history()
    history = [h for h in history if h["data"] != today]
    history.append({"data": today, "cota_fechamento": round(cota_est, 8)})
    history.sort(key=lambda x: x["data"])
    save_quota_history(history)

    return jsonify({"ok": True, "data": today, "cota_fechamento": round(cota_est, 8)})

@app.route("/api/performance-chart")
def api_performance_chart():
    history = load_quota_history()
    if not history:
        return jsonify({"series": []})

    cache = load_cache()
    now   = time.time()
    ibov_key       = "ibov_history_full"
    benchmarks_key = "benchmarks_history_full"

    # ── IBOV ──
    ibov_map = {}
    if cache.get(ibov_key) and now < cache[ibov_key].get("expires_at", 0):
        ibov_map = cache[ibov_key]["data"]
    else:
        start  = history[0]["data"]
        end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
        try:
            hist = yf.Ticker("^BVSP").history(
                start=start, end=end_dt.strftime("%Y-%m-%d"), timeout=10
            )
            if not hist.empty:
                ibov_map = {str(d.date()): round(float(v), 2) for d, v in hist["Close"].items()}
        except Exception as e:
            print(f"[perf-chart] IBOV error: {e}")
        ttl = HISTORY_TTL if ibov_map else 120
        cache[ibov_key] = {"data": ibov_map, "expires_at": now + ttl}
        save_cache(cache)

    # ── Additional benchmarks: SMLL, IDIV, S&P500, NASDAQ, CDI ──
    benchmark_maps = {}
    if cache.get(benchmarks_key) and now < cache[benchmarks_key].get("expires_at", 0):
        benchmark_maps = cache[benchmarks_key]["data"]
    else:
        start  = history[0]["data"]
        end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
        # CDI first — independent of yfinance, must not be blocked by hanging requests
        try:
            cdi_daily = load_cdi_map()
            if cdi_daily:
                cumulative = 100.0
                cdi_cum = {}
                for d in sorted(cdi_daily.keys()):
                    cumulative *= (1 + cdi_daily[d] / 100)
                    cdi_cum[d] = round(cumulative, 6)
                benchmark_maps["cdi"] = cdi_cum
        except Exception as e:
            print(f"[perf-chart] CDI error: {e}")

        # SMAL11.SA = iShares Small Cap Brasil ETF (proxy SMLL index)
        # DIVO11.SA = It Now IDIV ETF (proxy IDIV index)
        extra_tickers = {
            "^SMLL":  "SMAL11.SA",
            "^IDIV":  "DIVO11.SA",
            "^GSPC":  "^GSPC",
            "^IXIC":  "^IXIC",
        }
        for out_key, yf_ticker in extra_tickers.items():
            try:
                hist = yf.Ticker(yf_ticker).history(
                    start=start, end=end_dt.strftime("%Y-%m-%d"), timeout=10
                )
                if not hist.empty:
                    benchmark_maps[out_key] = {
                        str(d.date()): round(float(v), 2)
                        for d, v in hist["Close"].items()
                    }
            except Exception as e:
                print(f"[perf-chart] {yf_ticker} error: {e}")
        ttl = HISTORY_TTL if benchmark_maps else 120
        cache[benchmarks_key] = {"data": benchmark_maps, "expires_at": now + ttl}
        save_cache(cache)

    series = [{"date": e["data"], "fund": e["cota_fechamento"], "ibov": ibov_map.get(e["data"])}
              for e in history]
    return jsonify({"series": series, "base_date": history[0]["data"], "benchmarks": benchmark_maps})

CDI_TTL = 24 * 3600

def load_cdi_map():
    """Returns {YYYY-MM-DD: daily_rate_pct} from cache or BCB API."""
    import math, requests as req
    cache    = load_cache()
    now      = time.time()
    cdi_key  = "cdi_daily"
    history  = load_quota_history()
    if not history:
        return {}

    start_date = history[0]["data"]
    end_date   = history[-1]["data"]

    cached = cache.get(cdi_key, {})
    # Serve from cache if fresh AND covers the full range
    if cached.get("expires_at", 0) > now and cached.get("end_date") == end_date:
        return cached["data"]

    start_str = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    end_str   = datetime.strptime(end_date,   "%Y-%m-%d").strftime("%d/%m/%Y")
    url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados"
           f"?formato=json&dataInicial={start_str}&dataFinal={end_str}")
    try:
        resp = req.get(url, timeout=20)
        resp.raise_for_status()
        raw = resp.json()
        if not isinstance(raw, list):
            raise ValueError("resposta inesperada do BCB")
        cdi_map = {}
        for item in raw:
            d = datetime.strptime(item["data"], "%d/%m/%Y").strftime("%Y-%m-%d")
            cdi_map[d] = float(item["valor"])
        cache[cdi_key] = {"data": cdi_map, "end_date": end_date, "expires_at": now + CDI_TTL}
        save_cache(cache)
        return cdi_map
    except Exception:
        return cached.get("data", {})

@app.route("/api/drawdown-volatility")
def api_drawdown_volatility():
    import math
    history = load_quota_history()
    if not history:
        return jsonify({"series": []})

    dates = [e["data"] for e in history]
    cotas = [e["cota_fechamento"] for e in history]

    # Drawdown: (cota / peak_so_far - 1) * 100
    peak = cotas[0]
    drawdown = []
    for c in cotas:
        if c > peak:
            peak = c
        drawdown.append(round((c / peak - 1) * 100, 2))

    # Rolling annualized volatility (21-day window)
    vol_window = 21
    rolling_vol = [None] * min(vol_window, len(cotas))
    for i in range(vol_window, len(cotas)):
        sl = cotas[i - vol_window: i + 1]
        daily = [(sl[j] / sl[j-1] - 1) for j in range(1, len(sl))]
        n = len(daily)
        mean_r = sum(daily) / n
        var = sum((r - mean_r) ** 2 for r in daily) / n
        std_d = math.sqrt(var) if var > 0 else 0
        rolling_vol.append(round(std_d * math.sqrt(252) * 100, 2))

    series = [{"date": d, "drawdown": dd, "vol": v}
              for d, dd, v in zip(dates, drawdown, rolling_vol)]

    return jsonify({"series": series})

@app.route("/api/performance-indicators")
def api_performance_indicators():
    import math
    history = load_quota_history()
    if len(history) < 2:
        return jsonify({"data": {}})

    entries   = [(datetime.strptime(e["data"], "%Y-%m-%d"), e["cota_fechamento"]) for e in history]
    last_date = entries[-1][0]
    cdi_map   = load_cdi_map()

    def cdi_ann_for_window(start_dt, end_dt):
        """Annualized CDI for the date window (exclusive start, inclusive end)."""
        rates = [v for d, v in cdi_map.items()
                 if start_dt < datetime.strptime(d, "%Y-%m-%d") <= end_dt]
        if not rates:
            return None
        compound = 1.0
        for r in rates:
            compound *= (1 + r / 100)
        n = len(rates)
        return ((compound) ** (252 / n) - 1) * 100

    def compute_metrics(sl):
        if len(sl) < 2:
            return {"ret": None, "vol": None, "sharpe": None}
        dates = [d for d, _ in sl]
        cotas = [c for _, c in sl]
        ret_cum = (cotas[-1] / cotas[0] - 1) * 100
        daily = [(cotas[i] / cotas[i-1] - 1) for i in range(1, len(cotas))]
        if len(daily) < 2:
            return {"ret": round(ret_cum, 2), "vol": None, "sharpe": None}
        n      = len(daily)
        mean_r = sum(daily) / n
        var    = sum((r - mean_r) ** 2 for r in daily) / n
        std_d  = math.sqrt(var) if var > 0 else 0
        vol_ann = std_d * math.sqrt(252) * 100
        ret_ann = ((cotas[-1] / cotas[0]) ** (252 / n) - 1) * 100
        if vol_ann > 0:
            cdi = cdi_ann_for_window(dates[0], dates[-1])
            sharpe = round((ret_ann - (cdi or 0)) / vol_ann, 2)
        else:
            sharpe = None
        return {
            "ret":    round(ret_cum, 2),
            "vol":    round(vol_ann, 2) if std_d > 0 else None,
            "sharpe": sharpe,
        }

    def get_window(months_back=None, ytd=False, no_mes=False):
        if no_mes:
            cutoff = datetime(last_date.year, last_date.month, 1)
        elif ytd:
            cutoff = datetime(last_date.year, 1, 1)
        elif months_back:
            cutoff = last_date - timedelta(days=int(months_back * 365.25 / 12))
        else:
            return entries
        before = [(d, c) for d, c in entries if d < cutoff]
        after  = [(d, c) for d, c in entries if d >= cutoff]
        return ([before[-1]] if before else []) + after

    windows = [
        ("no_mes", get_window(no_mes=True)),
        ("no_ano", get_window(ytd=True)),
        ("3m",     get_window(months_back=3)),
        ("6m",     get_window(months_back=6)),
        ("12m",    get_window(months_back=12)),
        ("24m",    get_window(months_back=24)),
        ("36m",    get_window(months_back=36)),
        ("48m",    get_window(months_back=48)),
        ("60m",    get_window(months_back=60)),
        ("total",  entries),
    ]

    return jsonify({"data": {k: compute_metrics(sl) for k, sl in windows}})

@app.route("/api/monthly-returns")
def api_monthly_returns():
    history = load_quota_history()
    if not history:
        return jsonify({"years": []})

    # Load IBOV history (reuse from performance-chart cache)
    cache = load_cache()
    now   = time.time()
    ibov_key = "ibov_history_full"

    ibov_map = {}
    if cache.get(ibov_key) and now < cache[ibov_key].get("expires_at", 0):
        ibov_map = cache[ibov_key]["data"]
    else:
        start  = history[0]["data"]
        end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
        try:
            hist = yf.Ticker("^BVSP").history(
                start=start, end=end_dt.strftime("%Y-%m-%d"), timeout=10
            )
            if not hist.empty:
                ibov_map = {str(d.date()): round(float(v), 2) for d, v in hist["Close"].items()}
        except Exception as e:
            print(f"[monthly-returns] IBOV error: {e}")
            ibov_map = {}
        ttl = HISTORY_TTL if ibov_map else 120
        cache[ibov_key] = {"data": ibov_map, "expires_at": now + ttl}
        save_cache(cache)

    # Build month-end maps: "YYYY-MM" -> last closing value of that month
    month_map_fund = {}
    for e in sorted(history, key=lambda x: x["data"]):
        month_map_fund[e["data"][:7]] = e["cota_fechamento"]

    month_map_ibov = {}
    for date_str in sorted(ibov_map):
        month_map_ibov[date_str[:7]] = ibov_map[date_str]

    inception_date = history[0]["data"]
    inception_cota = history[0]["cota_fechamento"]

    # IBOV value on or before inception date
    inception_ibov = None
    for d in sorted(ibov_map):
        if d <= inception_date:
            inception_ibov = ibov_map[d]

    all_ym = sorted(month_map_fund.keys())
    years  = sorted(set(ym[:4] for ym in all_ym))
    mnums  = ["01","02","03","04","05","06","07","08","09","10","11","12"]

    result = []
    for year in years:
        fund_months = {}
        ibov_months = {}

        for mn in mnums:
            ym      = f"{year}-{mn}"
            m       = int(mn)
            prev_ym = f"{int(year)-1}-12" if m == 1 else f"{year}-{str(m-1).zfill(2)}"

            fc = month_map_fund.get(ym)
            fp = month_map_fund.get(prev_ym)
            ic = month_map_ibov.get(ym)
            ip = month_map_ibov.get(prev_ym)

            fund_months[mn] = round((fc / fp - 1) * 100, 2) if fc and fp else None
            ibov_months[mn] = round((ic / ip - 1) * 100, 2) if ic and ip else None

        # Annual return: last December of previous year as base (inception for first year)
        prev_dec      = f"{int(year)-1}-12"
        fund_yr_start = month_map_fund.get(prev_dec) or inception_cota
        ibov_yr_start = month_map_ibov.get(prev_dec) or inception_ibov

        last_ym     = max((ym for ym in all_ym if ym.startswith(year)), default=None)
        fund_yr_end = month_map_fund.get(last_ym)
        ibov_yr_end = month_map_ibov.get(last_ym)

        fund_year  = round((fund_yr_end / fund_yr_start - 1) * 100, 2) if fund_yr_end and fund_yr_start else None
        ibov_year  = round((ibov_yr_end / ibov_yr_start - 1) * 100, 2) if ibov_yr_end and ibov_yr_start else None
        fund_accum = round((fund_yr_end / inception_cota - 1) * 100, 2) if fund_yr_end else None
        ibov_accum = round((ibov_yr_end / inception_ibov - 1) * 100, 2) if ibov_yr_end and inception_ibov else None

        result.append({
            "year": year,
            "fund_months": fund_months, "ibov_months": ibov_months,
            "fund_year": fund_year, "ibov_year": ibov_year,
            "fund_accum": fund_accum, "ibov_accum": ibov_accum,
        })

    return jsonify({"years": result, "inception_date": inception_date})

@app.route("/api/stock-history/<path:ticker>")
def api_stock_history(ticker):
    """GET /api/stock-history/PRIO3.SA?range=1M"""
    range_key = request.args.get("range", "1M").upper()
    if range_key not in ("1S", "1M", "3M", "6M", "YTD", "1A"):
        range_key = "1M"
    return jsonify(get_cached_stock_history(ticker, range_key))

@app.route("/api/quota-history", methods=["GET"])
def api_get_quota_history():
    return jsonify(load_quota_history())

@app.route("/api/quota-history", methods=["POST"])
@require_admin
def api_add_quota_history():
    payload = request.json
    data_str = payload.get("data", "").strip()
    cota     = payload.get("cota_fechamento")
    if not data_str or cota is None:
        return jsonify({"error": "data e cota_fechamento são obrigatórios"}), 400
    try:
        cota = float(cota)
    except (TypeError, ValueError):
        return jsonify({"error": "cota_fechamento inválida"}), 400
    history = load_quota_history()
    history = [h for h in history if h["data"] != data_str]
    history.append({"data": data_str, "cota_fechamento": cota})
    history.sort(key=lambda x: x["data"])
    save_quota_history(history)
    return jsonify({"ok": True})

@app.route("/api/quota-history/<date>", methods=["DELETE"])
@require_admin
def api_delete_quota_history(date):
    history = load_quota_history()
    new_history = [h for h in history if h["data"] != date]
    if len(new_history) == len(history):
        return jsonify({"error": "entrada não encontrada"}), 404
    save_quota_history(new_history)
    return jsonify({"ok": True})

@app.route("/api/viewer-config", methods=["GET"])
def api_get_viewer_config():
    return jsonify(load_viewer_config())

@app.route("/api/viewer-config", methods=["POST"])
@require_admin
def api_save_viewer_config():
    payload = request.json
    config = load_viewer_config()
    for key in _VIEWER_CONFIG_DEFAULTS:
        if key in payload:
            config[key] = bool(payload[key])
    save_viewer_config(config)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────────────────────
# Watchlist & Screener — constants + helpers
# ─────────────────────────────────────────────────────────────────────────────

WATCHLIST_FILE      = os.path.join(DATA_DIR, "watchlist.json")
SCREENER_CACHE_FILE = os.path.join(DATA_DIR, "screener_cache.json")
SCREENER_TTL = 24 * 3600
MACRO_TTL    = 3600

IBOV_TICKERS = [
    "PETR4.SA","PETR3.SA","VALE3.SA","ITUB4.SA","ITUB3.SA","BBDC4.SA","BBDC3.SA","BBAS3.SA",
    "ABEV3.SA","WEGE3.SA","RENT3.SA","GGBR4.SA","USIM5.SA","CSAN3.SA","PRIO3.SA","CMIG4.SA",
    "EGIE3.SA","SBSP3.SA","RADL3.SA","RAIL3.SA","LREN3.SA","HAPV3.SA","RDOR3.SA","FLRY3.SA",
    "CYRE3.SA","MRVE3.SA","TIMS3.SA","VIVT3.SA","BRFS3.SA","MRFG3.SA","JBSS3.SA","SLCE3.SA",
    "BEEF3.SA","GOLL4.SA","AZUL4.SA","TAEE11.SA","ENGI11.SA","CPFE3.SA","ALUP11.SA","ENEV3.SA",
    "SAPR4.SA","PETZ3.SA","TOTVS3.SA","KLBN11.SA","SUZB3.SA","BBSE3.SA","SANB11.SA","BRSR6.SA",
    "YDUQ3.SA","COGN3.SA","TTEN3.SA","SIMH3.SA","TEND3.SA","MDNE3.SA","BMEB4.SA","VTRU3.SA",
    "CPLE6.SA","LOGG3.SA","SMTO3.SA","EQTL3.SA","ELET3.SA","ELET6.SA","HYPE3.SA","MULT3.SA",
    "GGPS3.SA","BPAN4.SA","IRBR3.SA","CXSE3.SA","CCRO3.SA","CSNA3.SA","EMBR3.SA","B3SA3.SA",
    "BRAV3.SA","CMIN3.SA","MGLU3.SA","CSMG3.SA","ARZZ3.SA","RAIZ4.SA","MRFG3.SA",
]

SMLL_EXTRA = [
    "ARML3.SA","EVEN3.SA","DIRR3.SA","TRIS3.SA","LAVV3.SA","MOVI3.SA","SEER3.SA",
    "BMGB4.SA","FRAS3.SA","POSI3.SA","CSMG3.SA","SEQL3.SA","GMAT3.SA","JHSF3.SA",
    "EZTC3.SA","ORVR3.SA","MBLY3.SA","GRND3.SA","TUPY3.SA","VULC3.SA","PLPL3.SA",
    "OMGE3.SA","INTB3.SA","PARD3.SA","MTRE3.SA","WEST3.SA","DESK3.SA","LAND3.SA",
]

_screener_state = {"running": False, "loaded": 0, "total": 0}
_screener_lock  = threading.Lock()


def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return {"items": []}
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_watchlist(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    github_push_async("data/watchlist.json", content, "chore: update watchlist.json via UI")


def load_screener_cache():
    if not os.path.exists(SCREENER_CACHE_FILE):
        return {}
    try:
        with open(SCREENER_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_screener_cache(data):
    with open(SCREENER_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _fetch_screener_bg(tickers):
    global _screener_state
    try:
        now = time.time()
        for ticker in tickers:
            scache = load_screener_cache()
            entry  = scache.get(ticker, {})
            if now < entry.get("expires_at", 0):
                with _screener_lock:
                    _screener_state["loaded"] += 1
                continue
            try:
                t     = yf.Ticker(ticker)
                info  = t.info
                fast  = t.fast_info
                price = fast.last_price
                prev  = fast.previous_close
                var   = round((price - prev) / prev * 100, 2) if price and prev else None
                dy    = info.get("dividendYield")
                roe   = info.get("returnOnEquity")
                mc    = info.get("marketCap")
                sec   = info.get("sector")
                scache[ticker] = {
                    "ticker":               ticker.replace(".SA", ""),
                    "yahoo_ticker":         ticker,
                    "short_name":           info.get("shortName") or info.get("longName"),
                    "sector":               SECTOR_PT.get(sec, sec) if sec else None,
                    "preco":                round(price, 2) if price else None,
                    "var_dia_pct":          var,
                    "trailing_pe":          _round(info.get("trailingPE"), 2),
                    "forward_pe":           _round(info.get("forwardPE"), 2),
                    "enterprise_to_ebitda": _round(info.get("enterpriseToEbitda"), 1),
                    "return_on_equity":     round(roe * 100, 1) if roe is not None else None,
                    "price_to_book":        _round(info.get("priceToBook"), 1),
                    "dividend_yield":       round(dy if dy > 1 else dy * 100, 2) if dy else None,
                    "beta":                 _round(info.get("beta"), 2),
                    "market_cap_bi":        round(mc / 1e9, 1) if mc else None,
                    "expires_at":           now + SCREENER_TTL,
                }
                save_screener_cache(scache)
            except Exception as e:
                print(f"[screener] {ticker}: {e}")
            with _screener_lock:
                _screener_state["loaded"] += 1
    finally:
        with _screener_lock:
            _screener_state["running"] = False


def start_screener_if_needed(tickers):
    with _screener_lock:
        if _screener_state["running"]:
            return
        # If all tickers are already cached and not expired, skip starting a thread
        scache = load_screener_cache()
        now = time.time()
        stale = [t for t in tickers if now >= scache.get(t, {}).get("expires_at", 0)]
        if not stale:
            _screener_state["loaded"] = len(tickers)
            _screener_state["total"]  = len(tickers)
            return
        _screener_state["running"] = True
        _screener_state["loaded"]  = 0
        _screener_state["total"]   = len(tickers)
    t = threading.Thread(target=_fetch_screener_bg, args=(tickers,), daemon=True)
    t.start()


# ─────────────────────────────────────────────────────────────────────────────
# Attribution
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/attribution")
def api_attribution():
    import pandas as pd
    period    = request.args.get("period", "month")
    portfolio = load_portfolio()
    positions = portfolio["positions"]
    tickers   = [p["yahoo_ticker"] for p in positions]
    prices    = get_cached_prices(tickers)

    total_value = sum(
        (prices.get(p["yahoo_ticker"], {}).get("price") or 0) * p["quantidade"]
        for p in positions
    )

    ibov_ret = None
    rows     = []

    if period == "day":
        ibov_ret = (prices.get("^BVSP", {}).get("change_pct") or 0)
        for pos in positions:
            t    = pos["yahoo_ticker"]
            p    = prices.get(t, {}).get("price") or 0
            vl   = p * pos["quantidade"]
            ret  = prices.get(t, {}).get("change_pct") or 0
            peso = vl / total_value * 100 if total_value > 0 else 0
            rows.append({
                "ticker":          pos["ticker"],
                "retorno_pct":     round(ret, 2),
                "peso_pct":        round(peso, 2),
                "contribuicao_pct": round(ret * peso / 100, 3),
                "contribuicao_bps": round(ret * peso, 1),
            })
    else:
        now_dt = datetime.now()
        if period == "week":
            start_dt = now_dt - timedelta(days=8)
        elif period == "month":
            start_dt = datetime(now_dt.year, now_dt.month, 1) - timedelta(days=1)
        elif period == "ytd":
            start_dt = datetime(now_dt.year, 1, 1) - timedelta(days=1)
        else:
            start_dt = now_dt - timedelta(days=30)
        try:
            all_tick = tickers + ["^BVSP"]
            df = yf.download(all_tick, start=start_dt.strftime("%Y-%m-%d"),
                             end=(now_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                             auto_adjust=True, progress=False)
            if df.empty:
                return jsonify({"rows": [], "error": "sem dados históricos"})
            close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df
            clean = close.dropna(how="all")
            if len(clean) < 2:
                return jsonify({"rows": [], "error": "dados insuficientes"})
            first = clean.iloc[0]
            last  = clean.iloc[-1]
            ibov_s = float(first.get("^BVSP") or 0)
            ibov_e = float(last.get("^BVSP") or 0)
            ibov_ret = round((ibov_e / ibov_s - 1) * 100, 2) if ibov_s > 0 else None
            for pos in positions:
                t    = pos["yahoo_ticker"]
                s    = float(first.get(t) or 0)
                e    = float(last.get(t) or 0)
                ret  = round((e / s - 1) * 100, 2) if s > 0 else 0
                p    = prices.get(t, {}).get("price") or 0
                vl   = p * pos["quantidade"]
                peso = vl / total_value * 100 if total_value > 0 else 0
                rows.append({
                    "ticker":          pos["ticker"],
                    "retorno_pct":     ret,
                    "peso_pct":        round(peso, 2),
                    "contribuicao_pct": round(ret * peso / 100, 3),
                    "contribuicao_bps": round(ret * peso, 1),
                })
        except Exception as e:
            return jsonify({"rows": [], "error": str(e)})

    rows.sort(key=lambda x: x["contribuicao_pct"], reverse=True)
    total_fundo = round(sum(r["contribuicao_pct"] for r in rows), 3)
    alpha = round(total_fundo - ibov_ret, 2) if ibov_ret is not None else None
    return jsonify({
        "rows":            rows,
        "total_fundo_pct": total_fundo,
        "ibov_ret_pct":    round(ibov_ret, 2) if ibov_ret is not None else None,
        "alpha_pct":       alpha,
        "period":          period,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Macro Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/macro")
def api_macro():
    import requests as req
    cache    = load_cache()
    now      = time.time()
    mkey     = "macro_data"
    if cache.get(mkey) and now < cache[mkey].get("expires_at", 0):
        return jsonify(cache[mkey]["data"])

    result  = {}
    today   = datetime.now()
    s60     = (today - timedelta(days=60)).strftime("%d/%m/%Y")
    s14m    = (today - timedelta(days=430)).strftime("%d/%m/%Y")
    today_s = today.strftime("%d/%m/%Y")

    def bcb_series(serie, start):
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
               f"?formato=json&dataInicial={start}&dataFinal={today_s}")
        r = req.get(url, timeout=12)
        r.raise_for_status()
        return r.json()

    try:
        data = bcb_series(432, s60)
        if isinstance(data, list) and data:
            result["selic_meta"] = {
                "valor": float(data[-1]["valor"]),
                "data":  data[-1]["data"],
                "hist":  [{"data": d["data"], "valor": float(d["valor"])} for d in data[-30:]],
            }
    except Exception:
        pass

    try:
        data = bcb_series(433, s14m)
        if isinstance(data, list) and len(data) >= 12:
            last12 = data[-12:]
            acc = 1.0
            for item in last12:
                acc *= (1 + float(item["valor"]) / 100)
            result["ipca_12m"] = {
                "valor": round((acc - 1) * 100, 2),
                "data":  data[-1]["data"],
                "hist":  [{"data": d["data"], "valor": float(d["valor"])} for d in data[-24:]],
            }
    except Exception:
        pass

    for key, ticker in [("usdbrl", "BRL=X"), ("brent", "BZ=F"), ("sp500", "^GSPC")]:
        try:
            fi    = yf.Ticker(ticker).fast_info
            price = fi.last_price
            prev  = fi.previous_close
            var   = round((price - prev) / prev * 100, 2) if price and prev else None
            df_h  = yf.download(ticker, period="2mo", auto_adjust=True, progress=False)
            hist  = []
            if not df_h.empty:
                close = df_h["Close"]
                if hasattr(close, "squeeze"):
                    close = close.squeeze()
                hist = [{"data": str(d.date()), "valor": round(float(v), 2)}
                        for d, v in close.items()][-30:]
            result[key] = {"valor": round(price, 2) if price else None, "var_pct": var, "hist": hist}
        except Exception:
            pass

    cache[mkey] = {"data": result, "expires_at": now + MACRO_TTL}
    save_cache(cache)
    return jsonify(result)


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist
# ─────────────────────────────────────────────────────────────────────────────

def _build_watchlist_rows(watchlist):
    items = watchlist.get("items", [])
    if not items:
        return []
    tickers = [i["yahoo_ticker"] for i in items]
    prices  = get_cached_prices(tickers)
    funds   = get_cached_fundamentals(tickers)
    rows = []
    for item in items:
        t     = item["yahoo_ticker"]
        pd_   = prices.get(t, {})
        fund  = funds.get(t, {})
        price = pd_.get("price")
        pa    = item.get("preco_alvo")
        mc    = fund.get("market_cap")
        upside = round((pa / price - 1) * 100, 2) if price and pa and price > 0 else None
        rows.append({
            "ticker":               item["ticker"],
            "yahoo_ticker":         t,
            "categoria":            item.get("categoria", "Acao"),
            "tese":                 item.get("tese", ""),
            "status":               item.get("status", "Em análise"),
            "gatilho":              item.get("gatilho", ""),
            "preco_alvo":           pa,
            "liq_diaria_mm":        item.get("liq_diaria_mm"),
            "lucro_mi_26":          item.get("lucro_mi_26"),
            "preco":                price,
            "var_dia_pct":          pd_.get("change_pct"),
            "trailing_pe":          fund.get("trailing_pe"),
            "forward_pe":           fund.get("forward_pe"),
            "enterprise_to_ebitda": fund.get("enterprise_to_ebitda"),
            "return_on_equity":     fund.get("return_on_equity"),
            "price_to_book":        fund.get("price_to_book"),
            "dividend_yield":       fund.get("dividend_yield"),
            "market_cap_bi":        round(mc / 1e9, 1) if mc else None,
            "beta":                 fund.get("beta"),
            "sector":               fund.get("sector"),
            "upside_pct":           upside,
        })
    return rows


@app.route("/api/watchlist")
def api_get_watchlist():
    return jsonify({"rows": _build_watchlist_rows(load_watchlist())})


@app.route("/api/watchlist/add", methods=["POST"])
@require_admin
def api_add_watchlist():
    payload = request.json
    ticker  = payload.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    yahoo = ticker + ".SA"
    try:
        price = yf.Ticker(yahoo).fast_info.last_price
        if price is None:
            return jsonify({"error": f"Ticker {yahoo} não encontrado"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    wl = load_watchlist()
    if any(i["ticker"] == ticker for i in wl.get("items", [])):
        return jsonify({"error": "Ticker já está na watchlist"}), 409
    def _f(k):
        v = payload.get(k); return float(v) if v not in (None, "") else None
    wl.setdefault("items", []).append({
        "ticker":        ticker,
        "yahoo_ticker":  yahoo,
        "categoria":     payload.get("categoria", "Acao"),
        "tese":          payload.get("tese", ""),
        "status":        payload.get("status", "Em análise"),
        "gatilho":       payload.get("gatilho", ""),
        "preco_alvo":    _f("preco_alvo"),
        "liq_diaria_mm": _f("liq_diaria_mm"),
        "lucro_mi_26":   _f("lucro_mi_26"),
    })
    save_watchlist(wl)
    return jsonify({"ok": True})


@app.route("/api/watchlist/update", methods=["PUT"])
@require_admin
def api_update_watchlist():
    payload = request.json
    ticker  = payload.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    wl = load_watchlist()
    updated = False
    for item in wl.get("items", []):
        if item["ticker"] == ticker:
            for f in ["tese", "status", "gatilho", "categoria"]:
                if f in payload: item[f] = payload[f]
            for f in ["preco_alvo", "liq_diaria_mm", "lucro_mi_26"]:
                if f in payload:
                    v = payload[f]; item[f] = float(v) if v not in (None, "") else None
            updated = True; break
    if not updated:
        return jsonify({"error": "ticker não encontrado"}), 404
    save_watchlist(wl)
    return jsonify({"ok": True})


@app.route("/api/watchlist/<ticker>", methods=["DELETE"])
@require_admin
def api_delete_watchlist(ticker):
    wl = load_watchlist()
    before = len(wl.get("items", []))
    wl["items"] = [i for i in wl.get("items", []) if i["ticker"] != ticker.upper()]
    if len(wl["items"]) == before:
        return jsonify({"error": "ticker não encontrado"}), 404
    save_watchlist(wl)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# Screener
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/screener")
def api_screener():
    universo = request.args.get("universo", "ibov")
    if universo in ("smll", "todos"):
        tickers = list(dict.fromkeys(IBOV_TICKERS + SMLL_EXTRA))
    else:
        tickers = list(IBOV_TICKERS)

    start_screener_if_needed(tickers)

    scache = load_screener_cache()
    rows   = []
    for t in tickers:
        entry = scache.get(t, {})
        if not entry or not entry.get("preco"):
            continue
        rows.append({k: v for k, v in entry.items() if k != "expires_at"})

    def _flt(key, mn=None, mx=None):
        nonlocal rows
        if mn not in (None, ""):
            try: rows = [r for r in rows if r.get(key) is not None and r[key] >= float(mn)]
            except Exception: pass
        if mx not in (None, ""):
            try: rows = [r for r in rows if r.get(key) is not None and r[key] <= float(mx)]
            except Exception: pass

    _flt("trailing_pe",          mn=request.args.get("pl_min"),       mx=request.args.get("pl_max"))
    _flt("return_on_equity",     mn=request.args.get("roe_min"))
    _flt("dividend_yield",       mn=request.args.get("dy_min"))
    _flt("enterprise_to_ebitda", mx=request.args.get("evebitda_max"))
    _flt("beta",                 mn=request.args.get("beta_min"),      mx=request.args.get("beta_max"))

    setor = request.args.get("setor", "").strip()
    if setor:
        rows = [r for r in rows if r.get("sector") == setor]

    rows.sort(key=lambda x: x.get("return_on_equity") or -9999, reverse=True)

    with _screener_lock:
        state = dict(_screener_state)

    return jsonify({
        "rows":    rows,
        "loading": state["running"],
        "loaded":  state["loaded"],
        "total":   state["total"],
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
