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

from risk_methodology import RISK_METHODOLOGY

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
PORTFOLIO_FILE         = os.path.join(DATA_DIR, "portfolio.json")
CACHE_FILE             = os.path.join(DATA_DIR, "cache.json")
FUND_CONFIG_FILE       = os.path.join(DATA_DIR, "fund_config.json")
QUOTA_HISTORY_FILE     = os.path.join(DATA_DIR, "quota_history.json")
VIEWER_CONFIG_FILE     = os.path.join(DATA_DIR, "viewer_config.json")
PRETRADE_HISTORY_FILE  = os.path.join(DATA_DIR, "pretrade_history.json")
PORTFOLIO_HISTORY_FILE = os.path.join(DATA_DIR, "portfolio_history.json")
INDEX_MEMBERS_FILE     = os.path.join(DATA_DIR, "index_members.json")

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
        "descricao_fundo": "",
        "limite_concentracao_ativo_pct": 20.0,
        "limite_concentracao_setor_pct": 40.0,
        "enable_concentracao_ativo": False,
        "enable_concentracao_setor": False,
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

def load_pretrade_history():
    if not os.path.exists(PRETRADE_HISTORY_FILE):
        return []
    with open(PRETRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_pretrade_history(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(PRETRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    github_push_async("data/pretrade_history.json", content, "chore: update pretrade_history.json via UI")

def load_portfolio_history():
    if not os.path.exists(PORTFOLIO_HISTORY_FILE):
        return []
    with open(PORTFOLIO_HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_portfolio_history(data):
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(PORTFOLIO_HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    github_push_async("data/portfolio_history.json", content, "chore: update portfolio_history.json")

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
    "tab_table":         True,
    "tab_charts":        True,
    "tab_config":        True,
    "tab_history":       True,
    "tab_macro":         True,
    "tab_watchlist":     False,
    "tab_screener":      False,
    "tab_risk":          True,
    "tab_financials":    True,
    "tab_events":        False,
    "tab_research":      False,
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
                "average_volume":      info.get("averageVolume"),
            }
        except Exception as e:
            result[ticker] = {"error": str(e)}
    return result

def get_cached_fundamentals(tickers):
    cache = load_cache()
    now = time.time()
    # Invalida se expirado OU se peg_ratio ainda não está no cache (campo novo)
    if any(now > cache.get(t, {}).get("expires_at", 0) or "peg_ratio" not in cache.get(t, {}) or "average_volume" not in cache.get(t, {}) for t in tickers):
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

    brt_now    = datetime.utcnow() - timedelta(hours=3)
    today_str  = brt_now.strftime("%Y-%m-%d")
    data_fech  = fund_config.get("data_fechamento", "")
    mercado_fechado   = not is_market_open()
    today_is_official = mercado_fechado and (data_fech == today_str)

    # Fechamento oficial já registrado hoje: exibe apenas o fechamento, sem variação intraday
    if today_is_official:
        result = {
            "quota_fechamento":         quota_fech,
            "data_fechamento":          data_fech,
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
    # Se mercado fechado mas fechamento de hoje ainda não registrado, continua calculando
    # com os preços finais do pregão (mesmo comportamento do horário de mercado aberto).

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
        "mercado_fechado":         mercado_fechado,
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
    import math
    _PARTICIPATION_RATE = 0.20  # 20% do ADV — padrão de mercado para fundos

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

        avg_vol = fund.get("average_volume")
        avg_daily_vol_rs = round(avg_vol * price, 2) if avg_vol and price else None
        avg_daily_vol_mm = round(avg_daily_vol_rs / 1e6, 1) if avg_daily_vol_rs else None

        manual_score = pos.get("liq_diaria_mm")
        if manual_score is None and avg_daily_vol_rs and vl and avg_daily_vol_rs > 0:
            effective_daily = avg_daily_vol_rs * _PARTICIPATION_RATE
            days_calc = vl / effective_daily
            liq_score = round(max(-30.0, min(30.0, 10.0 - 10.0 * math.log2(max(days_calc, 0.001)))), 1)
            liq_auto  = True
        else:
            liq_score = manual_score
            liq_auto  = False

        rows.append({
            "ticker": pos["ticker"], "yahoo_ticker": yahoo,
            "categoria": pos.get("categoria", "Acao"), "quantidade": qtde,
            "liq_diaria_mm": liq_score, "liq_auto": liq_auto,
            "avg_daily_vol_mm": avg_daily_vol_mm,
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
            # IMPORTANTE: não cair em `categoria` (Ação/BDR) — isso corrompe
            # o HHI setorial mostrando Ação/BDR como se fossem setores.
            "sector": fund.get("sector") or "Outros",
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

def _build_portfolio_snapshot(data, quota, source="auto"):
    import uuid
    now = datetime.now()
    q, ws = quota or {}, data.get("weighted_stats", {})
    return {
        "id":        str(uuid.uuid4()),
        "date":      now.strftime("%Y-%m-%d"),
        "timestamp": now.isoformat(timespec="seconds"),
        "source":    source,
        "summary": {
            "total_value":            data.get("total_value"),
            "num_positions":          len(data.get("rows", [])),
            "cota_estimada":          q.get("cota_estimada"),
            "variacao_pct":           q.get("variacao_pct"),
            "w_trailing_pe":          ws.get("w_trailing_pe"),
            "w_forward_pe":           ws.get("w_forward_pe"),
            "w_peg_ratio":            ws.get("w_peg_ratio"),
            "w_enterprise_to_ebitda": ws.get("w_enterprise_to_ebitda"),
            "w_return_on_equity":     ws.get("w_return_on_equity"),
            "w_beta":                 ws.get("w_beta"),
            "w_price_to_book":        ws.get("w_price_to_book"),
            "w_dividend_yield":       ws.get("w_dividend_yield"),
            "w_var_dia_pct":          ws.get("w_var_dia_pct"),
            "w_upside_pct":           ws.get("w_upside_pct"),
            "w_lucro_mi_26":          ws.get("w_lucro_mi_26"),
        },
        "rows": data.get("rows", []),
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
    return render_template("index.html",
                           role=session.get("role", "viewer"),
                           viewer_config=load_viewer_config(),
                           risk_methodology=RISK_METHODOLOGY)

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
    _string_keys = {"data_fechamento", "descricao_fundo"}
    for key in ["quota_fechamento","data_fechamento","num_cotas","caixa",
                "proventos_a_receber","custos_provisionados","performance_fee_rate",
                "performance_fee_acumulada_rs","descricao_fundo",
                "limite_concentracao_ativo_pct","limite_concentracao_setor_pct",
                "enable_concentracao_ativo","enable_concentracao_setor"]:
        if key not in payload: continue
        val = payload[key]
        if key in _string_keys:
            config[key] = val
        elif key in ("enable_concentracao_ativo", "enable_concentracao_setor"):
            config[key] = bool(val)
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

@app.route("/api/export/pptx", methods=["POST"])
@require_admin
def api_export_pptx():
    from pptx import Presentation
    from pptx.util import Cm, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    import base64 as _b64, io as _io

    body          = request.json or {}
    images        = body.get("images", {})
    fund_name     = body.get("fund_name", "HARBOUR IAT FIF AÇÕES RL")
    ref_date      = body.get("ref_date", "")
    descricao     = body.get("descricao", "")
    stats         = body.get("stats", {})
    indicators    = body.get("indicators", {})
    annual_years  = body.get("annual_years", [])
    risk          = body.get("risk", {})
    concentration = body.get("concentration", {})
    liquidity     = body.get("liquidity", {})
    dist          = body.get("dist", {})

    prs = Presentation()
    prs.slide_width  = Cm(33.87)
    prs.slide_height = Cm(19.05)
    blank = prs.slide_layouts[6]

    BG     = RGBColor(0x0D, 0x0D, 0x0D)
    ORANGE = RGBColor(0xFF, 0x8C, 0x00)
    WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
    MUTED  = RGBColor(0x88, 0x88, 0x88)
    SURF   = RGBColor(0x1E, 0x1E, 0x1E)
    GREEN_ = RGBColor(0x00, 0xCC, 0x44)
    RED_   = RGBColor(0xFF, 0x33, 0x33)
    BLACK  = RGBColor(0x00, 0x00, 0x00)

    def _bg(slide):
        s = slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
        s.fill.solid(); s.fill.fore_color.rgb = BG; s.line.fill.background()

    def _rect(slide, l, t, w, h, color):
        s = slide.shapes.add_shape(1, l, t, w, h)
        s.fill.solid(); s.fill.fore_color.rgb = color; s.line.fill.background()

    def _txt(slide, text, l, t, w, h, size=11, bold=False, color=WHITE,
             align=PP_ALIGN.LEFT, italic=False):
        tf = slide.shapes.add_textbox(l, t, w, h).text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]; p.alignment = align
        run = p.add_run(); run.text = str(text)
        run.font.size = Pt(size); run.font.bold = bold
        run.font.italic = italic; run.font.color.rgb = color

    def _img(slide, b64str, l, t, w, h):
        if not b64str: return
        raw = _b64.b64decode(b64str.split(",")[-1])
        slide.shapes.add_picture(_io.BytesIO(raw), l, t, w, h)

    def _pct_color(val):
        if not isinstance(val, (int, float)): return MUTED
        return GREEN_ if val >= 0 else RED_

    def _fmt(val, is_pct=True, decimals=2):
        if not isinstance(val, (int, float)): return "—"
        if is_pct:
            sign = "+" if val > 0 else ""
            return f"{sign}{val:.{decimals}f}%"
        return f"{val:.{decimals}f}"

    # ── Slide 1: Capa ────────────────────────────────────────────────
    s1 = prs.slides.add_slide(blank)
    _bg(s1)
    _rect(s1, 0, 0, prs.slide_width, Cm(2.0), ORANGE)
    _txt(s1, fund_name, Cm(0.6), Cm(0.2), Cm(26), Cm(1.6), size=24, bold=True, color=BLACK)
    if ref_date:
        _txt(s1, f"Ref.: {ref_date}", Cm(27), Cm(0.5), Cm(6.2), Cm(1.0),
             size=10, color=BLACK, align=PP_ALIGN.RIGHT)
    stat_items = [
        ("PATRIMÔNIO",  stats.get("aum",       "—")),
        ("COTA",        stats.get("quota",      "—")),
        ("INÍCIO",      stats.get("inception",  "—")),
        ("BENCHMARK",   stats.get("benchmark",  "IBOV")),
        ("ESTRATÉGIA",  stats.get("strategy",   "Long-Only")),
    ]
    bw = Cm(5.8)
    for i, (lbl, val) in enumerate(stat_items):
        x = Cm(0.6 + i * 6.5)
        _rect(s1, x, Cm(2.4), bw, Cm(2.0), SURF)
        _txt(s1, lbl, x+Cm(0.3), Cm(2.5), bw-Cm(0.6), Cm(0.7), size=8, color=ORANGE, bold=True)
        _txt(s1, str(val), x+Cm(0.3), Cm(3.1), bw-Cm(0.6), Cm(1.0), size=11, color=WHITE, bold=True)
    if descricao:
        _txt(s1, descricao, Cm(0.6), Cm(5.0), prs.slide_width-Cm(1.2), Cm(12.0),
             size=11, color=RGBColor(0xCC, 0xCC, 0xCC))

    # ── Slide 2: Performance ─────────────────────────────────────────
    s2 = prs.slides.add_slide(blank)
    _bg(s2)
    _rect(s2, 0, 0, prs.slide_width, Cm(1.2), ORANGE)
    _txt(s2, "PERFORMANCE ACUMULADA", Cm(0.6), Cm(0.1), Cm(20), Cm(1.0), size=14, bold=True, color=BLACK)
    if images.get("perf_chart"):
        _img(s2, images["perf_chart"], Cm(0.5), Cm(1.5), Cm(24), Cm(13))
    metric_items = [
        ("RETORNO TOTAL", indicators.get("total", {}).get("ret"),   True),
        ("NO ANO",        indicators.get("no_ano", {}).get("ret"),  True),
        ("12 MESES",      indicators.get("12m",    {}).get("ret"),  True),
        ("SHARPE TOTAL",  indicators.get("total", {}).get("sharpe"), False),
        ("VOL. ANUAL",    indicators.get("total", {}).get("vol"),   True),
    ]
    for i, (lbl, val, is_pct) in enumerate(metric_items):
        y = Cm(1.8 + i * 3.0)
        _rect(s2, Cm(25.5), y, Cm(7.8), Cm(2.6), SURF)
        _txt(s2, lbl, Cm(25.8), y+Cm(0.1), Cm(7.3), Cm(0.8), size=8, color=MUTED, bold=True)
        c = _pct_color(val) if lbl not in ("SHARPE TOTAL", "VOL. ANUAL") else WHITE
        _txt(s2, _fmt(val, is_pct), Cm(25.8), y+Cm(0.9), Cm(7.3), Cm(1.4),
             size=16, bold=True, color=c)

    # ── Slide 3: Rentabilidade Anual ──────────────────────────────────
    s3 = prs.slides.add_slide(blank)
    _bg(s3)
    _rect(s3, 0, 0, prs.slide_width, Cm(1.2), ORANGE)
    _txt(s3, "RENTABILIDADE HISTÓRICA ANUAL", Cm(0.6), Cm(0.1), Cm(30), Cm(1.0), size=14, bold=True, color=BLACK)
    hdrs = ["ANO", "FUNDO", "IBOV", "CDI", "ALPHA"]
    cws  = [Cm(3.2), Cm(5.0), Cm(5.0), Cm(5.0), Cm(5.0)]
    cx   = [Cm(1.5)]
    for w in cws[:-1]: cx.append(cx[-1] + w)
    rh = Cm(0.88)
    hy = Cm(1.5)
    _rect(s3, Cm(1.0), hy, sum(cws), rh, RGBColor(0x1E, 0x1E, 0x2E))
    for i, h in enumerate(hdrs):
        _txt(s3, h, cx[i], hy+Cm(0.05), cws[i], rh-Cm(0.1), size=9, bold=True, color=ORANGE, align=PP_ALIGN.CENTER)
    for ri, yr in enumerate(annual_years):
        y = hy + rh*(ri+1)
        _rect(s3, Cm(1.0), y, sum(cws), rh,
              RGBColor(0x18,0x18,0x18) if ri%2==0 else RGBColor(0x14,0x14,0x14))
        row_vals = [
            (yr.get("year",""),       WHITE),
            (_fmt(yr.get("fund_year")), _pct_color(yr.get("fund_year"))),
            (_fmt(yr.get("ibov_year")), _pct_color(yr.get("ibov_year"))),
            (_fmt(yr.get("cdi_year")),  _pct_color(yr.get("cdi_year"))),
            (_fmt(yr.get("alpha")),     _pct_color(yr.get("alpha"))),
        ]
        for i, (txt, c) in enumerate(row_vals):
            _txt(s3, txt, cx[i], y+Cm(0.05), cws[i], rh-Cm(0.1), size=9, color=c, align=PP_ALIGN.CENTER)
    if annual_years:
        last = annual_years[-1]
        y = hy + rh*(len(annual_years)+1)
        _rect(s3, Cm(1.0), y, sum(cws), rh, RGBColor(0x22,0x22,0x11))
        acc_vals = [
            ("ACUMULADO",                     ORANGE),
            (_fmt(last.get("fund_accum")),    _pct_color(last.get("fund_accum"))),
            (_fmt(last.get("ibov_accum")),    _pct_color(last.get("ibov_accum"))),
            (_fmt(last.get("cdi_accum")),     _pct_color(last.get("cdi_accum"))),
            ("—",                             MUTED),
        ]
        for i, (txt, c) in enumerate(acc_vals):
            _txt(s3, txt, cx[i], y+Cm(0.05), cws[i], rh-Cm(0.1), size=9, bold=True, color=c, align=PP_ALIGN.CENTER)

    # ── Slide 4: Risco ────────────────────────────────────────────────
    s4 = prs.slides.add_slide(blank)
    _bg(s4)
    _rect(s4, 0, 0, prs.slide_width, Cm(1.2), ORANGE)
    _txt(s4, "ANÁLISE DE RISCO", Cm(0.6), Cm(0.1), Cm(20), Cm(1.0), size=14, bold=True, color=BLACK)
    risk_cards = [
        ("SHARPE (TOTAL)",   risk.get("sharpe"),           False),
        ("VOLATILIDADE ANUAL", risk.get("vol"),            True),
        ("MAX. DRAWDOWN",    risk.get("max_dd"),           False),
        ("VaR 95% (1D)",     risk.get("var_95"),           False),
        ("BETA (vs IBOV)",   risk.get("beta"),             False),
        ("TRACKING ERROR",   risk.get("tracking_error"),   True),
        ("INFORMATION RATIO", risk.get("info_ratio"),      False),
        ("CAPTURE UP",       risk.get("upside_capture"),   False),
        ("CAPTURE DOWN",     risk.get("downside_capture"), True),
    ]
    cw_ = Cm(9.8); ch_ = Cm(4.2)
    for i, (lbl, val, neutral) in enumerate(risk_cards):
        col = i % 3; row = i // 3
        x = Cm(1.0 + col * 10.8); y = Cm(1.5 + row * 4.8)
        _rect(s4, x, y, cw_, ch_, SURF)
        _txt(s4, lbl, x+Cm(0.3), y+Cm(0.2), cw_-Cm(0.6), Cm(0.8), size=8, color=MUTED, bold=True)
        is_ratio = lbl in ("BETA (vs IBOV)", "INFORMATION RATIO", "SHARPE (TOTAL)", "CAPTURE UP", "CAPTURE DOWN")
        txt = _fmt(val, is_pct=not is_ratio)
        c   = WHITE if neutral or val is None else _pct_color(val)
        if lbl in ("VOLATILIDADE ANUAL", "TRACKING ERROR"): c = WHITE
        _txt(s4, txt, x+Cm(0.3), y+Cm(1.0), cw_-Cm(0.6), Cm(2.8), size=22, bold=True, color=c)

    # ── Slide 5: Concentração e Liquidez ──────────────────────────────
    s5 = prs.slides.add_slide(blank)
    _bg(s5)
    _rect(s5, 0, 0, prs.slide_width, Cm(1.2), ORANGE)
    _txt(s5, "CONCENTRAÇÃO E LIQUIDEZ", Cm(0.6), Cm(0.1), Cm(20), Cm(1.0), size=14, bold=True, color=BLACK)
    top5 = concentration.get("top5", [])
    _txt(s5, "TOP POSIÇÕES", Cm(1.0), Cm(1.5), Cm(16), Cm(0.8), size=10, color=ORANGE, bold=True)
    for i, pos in enumerate(top5[:5]):
        y = Cm(2.5 + i * 1.8)
        _rect(s5, Cm(1.0), y, Cm(16), Cm(1.5), SURF if i%2==0 else BG)
        _txt(s5, pos.get("ticker",""), Cm(1.3), y+Cm(0.2), Cm(10), Cm(1.0), size=12, bold=True, color=WHITE)
        pct = pos.get("pct_total", 0)
        _txt(s5, f"{pct:.1f}%", Cm(13), y+Cm(0.2), Cm(3.5), Cm(1.0), size=12, color=ORANGE, align=PP_ALIGN.RIGHT)
    hhi_val = concentration.get("hhi")
    hhi_lbl = concentration.get("hhi_label", "")
    top5_pct = concentration.get("top5_pct")
    liq_items = [
        ("HHI",       f"{hhi_val:.0f} ({hhi_lbl})" if isinstance(hhi_val,(int,float)) else "—"),
        ("TOP 5",     _fmt(top5_pct) if isinstance(top5_pct,(int,float)) else "—"),
        ("LIQ. 1D",   _fmt(liquidity.get("liq_1d_pct"))),
        ("LIQ. 5D",   _fmt(liquidity.get("liq_5d_pct"))),
        ("LIQ. 10D",  _fmt(liquidity.get("liq_10d_pct"))),
    ]
    _txt(s5, "INDICADORES", Cm(19.0), Cm(1.5), Cm(14), Cm(0.8), size=10, color=ORANGE, bold=True)
    for i, (lbl, val) in enumerate(liq_items):
        y = Cm(2.5 + i * 3.0)
        _rect(s5, Cm(19.0), y, Cm(14.0), Cm(2.6), SURF)
        _txt(s5, lbl, Cm(19.3), y+Cm(0.1), Cm(13.5), Cm(0.8), size=8, color=MUTED, bold=True)
        _txt(s5, val, Cm(19.3), y+Cm(0.9), Cm(13.5), Cm(1.4), size=16, bold=True, color=WHITE)

    # ── Slide 6: Distribuição de Retornos ─────────────────────────────
    s6 = prs.slides.add_slide(blank)
    _bg(s6)
    _rect(s6, 0, 0, prs.slide_width, Cm(1.2), ORANGE)
    _txt(s6, "DISTRIBUIÇÃO DE RETORNOS DIÁRIOS", Cm(0.6), Cm(0.1), Cm(30), Cm(1.0), size=14, bold=True, color=BLACK)
    if images.get("dist_chart"):
        _img(s6, images["dist_chart"], Cm(0.5), Cm(1.5), Cm(22), Cm(14))
    dist_stats = [
        ("ASSIMETRIA",     dist.get("skewness"),     False),
        ("CURTOSE",        dist.get("kurtosis"),      False),
        ("DIAS POSITIVOS", dist.get("pct_positive"),  True),
        ("MELHOR DIA",     dist.get("best_day"),      True),
        ("PIOR DIA",       dist.get("worst_day"),     False),
    ]
    for i, (lbl, val, use_pct_color) in enumerate(dist_stats):
        y = Cm(1.8 + i * 3.2)
        _rect(s6, Cm(23.5), y, Cm(9.8), Cm(2.8), SURF)
        _txt(s6, lbl, Cm(23.8), y+Cm(0.1), Cm(9.3), Cm(0.8), size=8, color=MUTED, bold=True)
        txt = _fmt(val) if isinstance(val,(int,float)) else "—"
        c   = _pct_color(val) if use_pct_color else WHITE
        _txt(s6, txt, Cm(23.8), y+Cm(0.9), Cm(9.3), Cm(1.6), size=16, bold=True, color=c)

    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    filename = f"harbour_fia_{datetime.now().strftime('%Y%m%d')}.pptx"
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation")

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

    # ── save portfolio snapshot ──────────────────────────────────────────────
    snap = _build_portfolio_snapshot(data, quota, source="auto")
    ph   = load_portfolio_history()
    ph   = [r for r in ph if not (r.get("date") == snap["date"] and r.get("source") == "auto")]
    ph.append(snap)
    ph.sort(key=lambda x: x["timestamp"])
    save_portfolio_history(ph)
    # ────────────────────────────────────────────────────────────────────────

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

@app.route("/api/annual-returns")
def api_annual_returns():
    history = load_quota_history()
    if not history:
        return jsonify({"years": [], "inception_date": None})

    cache    = load_cache()
    now      = time.time()
    ibov_key = "ibov_history_full"

    ibov_map = {}
    if cache.get(ibov_key) and now < cache[ibov_key].get("expires_at", 0):
        ibov_map = cache[ibov_key]["data"]
    else:
        start  = history[0]["data"]
        end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
        try:
            hist = yf.Ticker("^BVSP").history(
                start=start, end=end_dt.strftime("%Y-%m-%d"), timeout=10)
            if not hist.empty:
                ibov_map = {str(d.date()): round(float(v), 2)
                            for d, v in hist["Close"].items()}
        except Exception as e:
            print(f"[annual-returns] IBOV error: {e}")
        ttl = HISTORY_TTL if ibov_map else 120
        cache[ibov_key] = {"data": ibov_map, "expires_at": now + ttl}
        save_cache(cache)

    cdi_map = load_cdi_map()

    year_end_fund = {}
    for e in sorted(history, key=lambda x: x["data"]):
        year_end_fund[e["data"][:4]] = e["cota_fechamento"]

    year_end_ibov = {}
    for date_str in sorted(ibov_map):
        year_end_ibov[date_str[:4]] = ibov_map[date_str]

    inception_date = history[0]["data"]
    inception_cota = history[0]["cota_fechamento"]
    inception_ibov = None
    for d in sorted(ibov_map):
        if d <= inception_date:
            inception_ibov = ibov_map[d]

    years = sorted(year_end_fund.keys())
    result = []
    for year in years:
        prev_year  = str(int(year) - 1)
        fund_start = year_end_fund.get(prev_year) or inception_cota
        fund_end   = year_end_fund.get(year)
        ibov_start = year_end_ibov.get(prev_year) or inception_ibov
        ibov_end   = year_end_ibov.get(year)

        cdi_rates = [v for d, v in cdi_map.items() if d.startswith(year)]
        if cdi_rates:
            cdi_cum = 1.0
            for r in cdi_rates:
                cdi_cum *= (1 + r / 100)
            cdi_year = round((cdi_cum - 1) * 100, 2)
        else:
            cdi_year = None

        fund_year  = round((fund_end / fund_start - 1) * 100, 2) if fund_end and fund_start else None
        ibov_year  = round((ibov_end / ibov_start - 1) * 100, 2) if ibov_end and ibov_start else None
        fund_accum = round((fund_end / inception_cota - 1) * 100, 2) if fund_end else None
        ibov_accum = round((ibov_end / inception_ibov - 1) * 100, 2) if ibov_end and inception_ibov else None

        cdi_accum_rates = [v for d, v in cdi_map.items() if d >= inception_date and d[:4] <= year]
        if cdi_accum_rates:
            cum = 1.0
            for r in cdi_accum_rates:
                cum *= (1 + r / 100)
            cdi_accum = round((cum - 1) * 100, 2)
        else:
            cdi_accum = None

        alpha = round(fund_year - ibov_year, 2) if fund_year is not None and ibov_year is not None else None

        result.append({
            "year":       year,
            "fund_year":  fund_year,
            "ibov_year":  ibov_year,
            "cdi_year":   cdi_year,
            "alpha":      alpha,
            "fund_accum": fund_accum,
            "ibov_accum": ibov_accum,
            "cdi_accum":  cdi_accum,
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
    s2y     = (today - timedelta(days=730)).strftime("%d/%m/%Y")
    jan1    = datetime(today.year, 1, 1).strftime("%d/%m/%Y")
    today_s = today.strftime("%d/%m/%Y")

    def bcb_series(serie, start):
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
               f"?formato=json&dataInicial={start}&dataFinal={today_s}")
        r = req.get(url, timeout=12)
        r.raise_for_status()
        return r.json()

    def focus_anual(indicador):
        """Busca expectativas anuais do Focus para o indicador dado.
        Retorna dict {ano: {mediana, minimo, maximo, respondentes}} para
        o ano corrente e o seguinte."""
        url = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas"
               "/versao/v1/odata/ExpectativaMercadoAnuais")
        ano_atual = str(today.year)
        ano_prox  = str(today.year + 1)
        params = {
            "$filter":   f"Indicador eq '{indicador}'",
            "$format":   "json",
            "$select":   "DataReferencia,Data,Mediana,Minimo,Maximo,numeroRespondentes",
            "$orderby":  "Data desc",
            "$top":      "40",
        }
        r = req.get(url, params=params, timeout=12)
        r.raise_for_status()
        rows = r.json().get("value", [])
        res = {}
        for ano in [ano_atual, ano_prox]:
            for row in rows:
                if str(row.get("DataReferencia", "")) == ano:
                    res[ano] = {
                        "mediana":      row.get("Mediana"),
                        "minimo":       row.get("Minimo"),
                        "maximo":       row.get("Maximo"),
                        "respondentes": row.get("numeroRespondentes"),
                    }
                    break
        return res

    # ── SELIC Meta (série 432) ────────────────────────────────────────
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

    # ── SELIC Focus ───────────────────────────────────────────────────
    try:
        result["selic_focus"] = focus_anual("Meta para taxa over-selic")
    except Exception:
        pass

    # ── CDI acumulado no ano (série 12 — taxa over anualizada diária) ─
    try:
        data_cdi = bcb_series(12, jan1)
        if isinstance(data_cdi, list) and data_cdi:
            acc_cdi = 1.0
            for item in data_cdi:
                annual = float(item["valor"]) / 100
                daily  = (1 + annual) ** (1 / 252) - 1
                acc_cdi *= (1 + daily)
            result["cdi_ytd"] = {"valor": round((acc_cdi - 1) * 100, 2)}
    except Exception:
        pass

    # ── IPCA 12m (série 433) ──────────────────────────────────────────
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

    # ── IPCA Focus ────────────────────────────────────────────────────
    try:
        result["ipca_focus"] = focus_anual("IPCA")
    except Exception:
        pass

    # ── IPCA Serviços (série 10844) ───────────────────────────────────
    try:
        data = bcb_series(10844, s14m)
        if isinstance(data, list) and data:
            result["ipca_servicos"] = {
                "valor": float(data[-1]["valor"]),
                "data":  data[-1]["data"],
                "hist":  [{"data": d["data"], "valor": float(d["valor"])} for d in data[-24:]],
            }
    except Exception:
        pass

    # ── USD/BRL oficial BCB (série 1) ─────────────────────────────────
    try:
        data = bcb_series(1, s60)
        if isinstance(data, list) and len(data) >= 2:
            val  = float(data[-1]["valor"])
            prev = float(data[-2]["valor"])
            var  = round((val - prev) / prev * 100, 2) if prev else None
            result["usdbrl"] = {
                "valor":   round(val, 4),
                "var_pct": var,
                "data":    data[-1]["data"],
                "hist":    [{"data": d["data"], "valor": float(d["valor"])} for d in data[-30:]],
            }
    except Exception:
        pass

    # ── USD/BRL Focus ─────────────────────────────────────────────────
    try:
        result["usdbrl_focus"] = focus_anual("Câmbio")
    except Exception:
        pass

    # ── PIB Focus ─────────────────────────────────────────────────────
    try:
        result["pib_focus"] = focus_anual("PIB Total")
    except Exception:
        pass

    # ── Dívida Bruta do Governo Geral % PIB (série 13762) ────────────
    try:
        data = bcb_series(13762, s2y)
        if isinstance(data, list) and data:
            result["divida_bruta"] = {
                "valor": float(data[-1]["valor"]),
                "data":  data[-1]["data"],
                "hist":  [{"data": d["data"], "valor": float(d["valor"])} for d in data[-24:]],
            }
    except Exception:
        pass

    # ── Balança Comercial saldo mensal (série 22707) ──────────────────
    try:
        data = bcb_series(22707, s2y)
        if isinstance(data, list) and data:
            result["balanca"] = {
                "valor": float(data[-1]["valor"]),
                "data":  data[-1]["data"],
                "hist":  [{"data": d["data"], "valor": float(d["valor"])} for d in data[-24:]],
            }
    except Exception:
        pass

    # ── Brent e S&P 500 (Yahoo Finance) ──────────────────────────────
    for key, ticker in [("brent", "BZ=F"), ("sp500", "^GSPC")]:
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


# ─────────────────────────────────────────────────────────────────────────────
# Risk Analytics
# ─────────────────────────────────────────────────────────────────────────────

RISK_TTL = 4 * 3600

STRESS_SCENARIOS = {
    "covid":      {"label": "COVID Crash",    "ibov_shock": -0.4566, "brl_shock":  0.255,  "description": "IBOV -45.7%, BRL +25.5% (fev-mar 2020)"},
    "joesley":    {"label": "Joesley Day",    "ibov_shock": -0.088,  "brl_shock":  0.085,  "description": "IBOV -8.8%, BRL +8.5% (17 mai 2017)"},
    "lula_elei":  {"label": "Eleição Lula",   "ibov_shock": -0.061,  "brl_shock":  0.037,  "description": "IBOV -6.1%, BRL +3.7% (30 out 2022)"},
    "dilma":      {"label": "Crise Dilma",    "ibov_shock": -0.128,  "brl_shock":  0.468,  "description": "IBOV -12.8%, BRL +46.8% (jan-set 2015)"},
}


def _liq_days_from_score(score):
    """Convert liq_diaria_mm score (-30 to +30) to estimated days to liquidate full position."""
    import math
    if score is None:
        return None
    return max(0.5, 2 ** ((-float(score) + 10) / 10))


def _compute_component_var_by_beta(rows, total_value, nav, portfolio_var_1d):
    if not total_value or not nav:
        return []
    rows_v = [r for r in rows if r.get("beta") is not None and r.get("valor_liquido")]
    if not rows_v:
        return []
    w_beta = sum(r["beta"] * r["valor_liquido"] / total_value for r in rows_v)
    if not w_beta:
        return []
    out = []
    for r in rows:
        w           = (r.get("valor_liquido") or 0) / total_value
        beta        = r.get("beta") or 0
        contrib_pct = (w * beta / w_beta * 100) if w_beta else 0
        var_rs      = (w * beta / w_beta * portfolio_var_1d * nav) if w_beta else 0
        out.append({
            "ticker":      r["ticker"],
            "weight_pct":  round(w * 100, 2),
            "beta":        beta,
            "contrib_pct": round(contrib_pct, 2),
            "var_1d_rs":   round(var_rs, 2),
        })
    out.sort(key=lambda x: x["contrib_pct"], reverse=True)
    return out


def _calcular_concentracao_pretrade(rows, total_value):
    """Calcula concentração por ativo e por setor a partir de rows já processados."""
    if not total_value:
        return {"por_ativo": {}, "por_setor": {}, "hhi": 0}
    por_ativo = {}
    sector_map = {}
    for r in rows:
        vl     = r.get("valor_liquido") or 0
        ytk    = r.get("yahoo_ticker") or r.get("ticker", "")
        sector = r.get("sector") or "Outros"
        por_ativo[ytk] = round(vl / total_value * 100, 4)
        sector_map[sector] = sector_map.get(sector, 0.0) + vl
    por_setor = {s: round(v / total_value * 100, 4) for s, v in sector_map.items()}
    hhi = int(round(sum((v / total_value) ** 2 for v in sector_map.values()) * 10000))
    return {"por_ativo": por_ativo, "por_setor": por_setor, "hhi": hhi}


@app.route("/api/risk/var")
def api_risk_var():
    import math
    window    = int(request.args.get("window", 252))
    cache     = load_cache()
    now       = time.time()
    cache_key = f"risk_var_{window}"
    if cache.get(cache_key) and now < cache[cache_key].get("expires_at", 0):
        return jsonify(cache[cache_key]["data"])

    history = load_quota_history()
    if len(history) < 22:
        return jsonify({"error": "Histórico insuficiente (< 22 dias)"}), 400

    fund_config = get_effective_fund_config()
    portfolio   = load_portfolio()
    tickers     = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices      = get_cached_prices(tickers)
    funds       = get_cached_fundamentals(tickers)
    pdata       = build_portfolio_response(portfolio, prices, funds)
    nav = (pdata.get("total_value") or 0) + (fund_config.get("caixa") or 0) + (fund_config.get("proventos_a_receber") or 0)

    cotas   = [e["cota_fechamento"] for e in history]
    rets    = [(cotas[i] / cotas[i - 1] - 1) for i in range(1, len(cotas))]
    rets    = rets[-window:]
    n       = len(rets)
    if n < 10:
        return jsonify({"error": "Retornos insuficientes"}), 400

    sorted_r = sorted(rets)
    idx_95   = max(1, int(math.floor(n * 0.05)))
    idx_99   = max(1, int(math.floor(n * 0.01)))

    var_95  = abs(sorted_r[idx_95 - 1])
    var_99  = abs(sorted_r[idx_99 - 1])
    cvar_95 = abs(sum(sorted_r[:idx_95]) / idx_95)
    cvar_99 = abs(sum(sorted_r[:max(1, idx_99)]) / max(1, idx_99))

    def _rs(v):  return round(v * nav, 2)
    def _pct(v): return round(v * 100, 3)

    result = {
        "window_days": window, "n_obs": n, "nav_ref": round(nav, 2),
        "var_95_1d_pct":  _pct(var_95),
        "var_99_1d_pct":  _pct(var_99),
        "cvar_95_1d_pct": _pct(cvar_95),
        "cvar_99_1d_pct": _pct(cvar_99),
        "var_95_10d_pct": _pct(var_95 * math.sqrt(10)),
        "var_99_10d_pct": _pct(var_99 * math.sqrt(10)),
        "var_95_1d_rs":   _rs(var_95),
        "var_99_1d_rs":   _rs(var_99),
        "cvar_95_1d_rs":  _rs(cvar_95),
        "cvar_99_1d_rs":  _rs(cvar_99),
        "var_95_10d_rs":  _rs(var_95 * math.sqrt(10)),
        "var_99_10d_rs":  _rs(var_99 * math.sqrt(10)),
        "component_var": _compute_component_var_by_beta(
            pdata["rows"], pdata.get("total_value", 0), nav, var_95),
        "return_distribution": {
            "mean_pct":           _pct(sum(rets) / n),
            "best_day":           _pct(max(rets)),
            "worst_day":          _pct(min(rets)),
            "positive_days_pct":  round(sum(1 for r in rets if r > 0) / n * 100, 1),
        },
    }
    cache[cache_key] = {"data": result, "expires_at": now + RISK_TTL}
    save_cache(cache)
    return jsonify(result)


@app.route("/api/risk/stress")
def api_risk_stress():
    scenario_key = request.args.get("scenario", "")
    custom_ibov  = request.args.get("ibov_shock")
    custom_brl   = request.args.get("brl_shock")

    portfolio   = load_portfolio()
    tickers     = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices      = get_cached_prices(tickers)
    funds       = get_cached_fundamentals(tickers)
    pdata       = build_portfolio_response(portfolio, prices, funds)
    fund_config = get_effective_fund_config()
    nav         = (pdata.get("total_value") or 0) + (fund_config.get("caixa") or 0) + (fund_config.get("proventos_a_receber") or 0)
    total_value = pdata.get("total_value") or 0

    def run_scenario(ibov_shock, brl_shock, label, description):
        rows_out   = []
        port_impact = 0.0
        for r in pdata["rows"]:
            w        = (r.get("valor_liquido") or 0) / total_value if total_value else 0
            beta     = r.get("beta") or 1.0
            is_bdr   = r.get("categoria", "").upper() == "BDR"
            # BRL depreciation (positive brl_shock) → BDR gains in BRL terms
            stock_imp   = beta * ibov_shock + (brl_shock if is_bdr else 0)
            pos_imp_rs  = stock_imp * (r.get("valor_liquido") or 0)
            port_impact += stock_imp * w
            rows_out.append({
                "ticker":     r["ticker"],
                "categoria":  r.get("categoria"),
                "weight_pct": round(w * 100, 2),
                "beta":       round(beta, 2),
                "impact_pct": round(stock_imp * 100, 2),
                "impact_rs":  round(pos_imp_rs, 2),
            })
        rows_out.sort(key=lambda x: x["impact_rs"])
        return {
            "label": label, "description": description,
            "ibov_shock_pct":       round(ibov_shock * 100, 2),
            "brl_shock_pct":        round(brl_shock * 100, 2),
            "portfolio_impact_pct": round(port_impact * 100, 2),
            "portfolio_impact_rs":  round(port_impact * nav, 2),
            "nav_ref": round(nav, 2),
            "positions": rows_out,
        }

    if custom_ibov is not None:
        try:
            ib  = float(custom_ibov) / 100
            brl = float(custom_brl or 0) / 100
        except ValueError:
            return jsonify({"error": "Valores inválidos"}), 400
        return jsonify(run_scenario(ib, brl, "Cenário Personalizado",
                                    f"IBOV {ib * 100:+.1f}%, BRL {brl * 100:+.1f}%"))

    if not scenario_key or scenario_key not in STRESS_SCENARIOS:
        return jsonify({"scenarios": {k: {"label": v["label"], "description": v["description"]}
                                       for k, v in STRESS_SCENARIOS.items()}})

    sc = STRESS_SCENARIOS[scenario_key]
    return jsonify(run_scenario(sc["ibov_shock"], sc["brl_shock"], sc["label"], sc["description"]))


@app.route("/api/risk/correlation")
def api_risk_correlation():
    import math
    window = int(request.args.get("window", 60))
    cache  = load_cache()
    now    = time.time()
    key    = f"risk_corr_{window}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    portfolio = load_portfolio()
    tickers   = [p["yahoo_ticker"] for p in portfolio["positions"]]
    all_t     = tickers + ["^BVSP"]
    end_dt    = datetime.now()
    start_dt  = end_dt - timedelta(days=int(window * 1.9) + 10)

    try:
        import pandas as pd
        df = yf.download(all_t, start=start_dt.strftime("%Y-%m-%d"),
                         end=end_dt.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        if df.empty:
            return jsonify({"error": "Sem dados"}), 400
        close   = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df
        returns = close.ffill().pct_change().dropna().tail(window)
        if len(returns) < 10:
            return jsonify({"error": "Dados insuficientes"}), 400
        corr    = returns.corr()
        cols    = [t for t in all_t if t in corr.columns]
        lmap    = {**{p["yahoo_ticker"]: p["ticker"] for p in portfolio["positions"]}, "^BVSP": "IBOV"}
        matrix  = []
        for r in cols:
            row = []
            for c in cols:
                v = corr.loc[r, c] if r in corr.index and c in corr.columns else None
                try:
                    row.append(round(float(v), 3) if v is not None and not math.isnan(float(v)) else None)
                except Exception:
                    row.append(None)
            matrix.append(row)
        result = {
            "labels": [lmap.get(t, t) for t in cols],
            "tickers": cols,
            "matrix": matrix,
            "window_days": window,
            "n_obs": len(returns),
        }
        cache[key] = {"data": result, "expires_at": now + RISK_TTL}
        save_cache(cache)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/risk/attribution")
def api_risk_attribution():
    import math
    window = int(request.args.get("window", 60))
    cache  = load_cache()
    now    = time.time()
    key    = f"risk_attr_{window}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    portfolio = load_portfolio()
    tickers   = [p["yahoo_ticker"] for p in portfolio["positions"]]
    qty_map   = {p["yahoo_ticker"]: p["quantidade"] for p in portfolio["positions"]}
    end_dt    = datetime.now()
    start_dt  = end_dt - timedelta(days=int(window * 1.9) + 10)

    try:
        import pandas as pd
        df = yf.download(tickers, start=start_dt.strftime("%Y-%m-%d"),
                         end=end_dt.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
        if df.empty:
            return jsonify({"error": "Sem dados"}), 400
        close   = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df
        returns = close.ffill().pct_change().dropna().tail(window)
        if len(returns) < 10:
            return jsonify({"error": "Dados insuficientes"}), 400

        prices      = get_cached_prices(tickers)
        total_value = sum((prices.get(t, {}).get("price") or 0) * qty_map.get(t, 0) for t in tickers)
        w_map       = {t: ((prices.get(t, {}).get("price") or 0) * qty_map.get(t, 0)) / total_value
                       for t in tickers} if total_value else {t: 0 for t in tickers}

        avail    = [t for t in tickers if t in returns.columns]
        port_ret = sum(returns[t] * w_map.get(t, 0) for t in avail)
        port_vol = float(port_ret.std() * math.sqrt(252) * 100)
        var_p    = float(port_ret.var())
        tlabels  = {p["yahoo_ticker"]: p["ticker"] for p in portfolio["positions"]}

        rows_out = []
        for t in avail:
            s            = returns[t]
            w            = w_map.get(t, 0)
            cov          = float(s.cov(port_ret))
            corr_p       = round(float(s.corr(port_ret)), 3)
            contrib_pct  = round(w * cov / var_p * 100, 2) if var_p > 0 else 0
            rows_out.append({
                "ticker":          tlabels.get(t, t),
                "weight_pct":      round(w * 100, 2),
                "vol_ind_pct":     round(float(s.std() * math.sqrt(252) * 100), 2),
                "corr_port":       corr_p,
                "contrib_risk_pct": contrib_pct,
                "contrib_vol_ppt": round(contrib_pct / 100 * port_vol, 2),
            })
        rows_out.sort(key=lambda x: x["contrib_risk_pct"], reverse=True)
        result = {
            "portfolio_vol_pct": round(port_vol, 2),
            "window_days": window,
            "n_obs": len(returns),
            "rows": rows_out,
        }
        cache[key] = {"data": result, "expires_at": now + RISK_TTL}
        save_cache(cache)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/risk/rolling-beta")
def api_risk_rolling_beta():
    roll_w = int(request.args.get("roll_window", 60))
    cache  = load_cache()
    now    = time.time()
    key    = f"risk_rbeta_{roll_w}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    history = load_quota_history()
    if len(history) < roll_w + 5:
        return jsonify({"error": "Histórico insuficiente"}), 400

    start  = history[0]["data"]
    end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
    try:
        ibov_h = yf.Ticker("^BVSP").history(
            start=start, end=end_dt.strftime("%Y-%m-%d"), timeout=15)
        if ibov_h.empty:
            return jsonify({"error": "Sem dados do IBOV"}), 400
        ibov_map   = {str(d.date()): float(v) for d, v in ibov_h["Close"].items()}
        ibov_dates = sorted(ibov_map)
        ibov_rets  = {ibov_dates[i]: ibov_map[ibov_dates[i]] / ibov_map[ibov_dates[i - 1]] - 1
                      for i in range(1, len(ibov_dates))}

        fund_map = {}
        prev = history[0]["cota_fechamento"]
        for e in history[1:]:
            fund_map[e["data"]] = e["cota_fechamento"] / prev - 1
            prev = e["cota_fechamento"]

        aligned = sorted(d for d in fund_map if d in ibov_rets)
        f_rets  = [fund_map[d] for d in aligned]
        i_rets  = [ibov_rets[d] for d in aligned]

        if len(aligned) < roll_w + 2:
            return jsonify({"error": "Dados insuficientes"}), 400

        series = []
        for i in range(roll_w, len(aligned)):
            sf  = f_rets[i - roll_w: i]
            si  = i_rets[i - roll_w: i]
            mf  = sum(sf) / roll_w
            mi  = sum(si) / roll_w
            cov = sum((sf[j] - mf) * (si[j] - mi) for j in range(roll_w)) / (roll_w - 1)
            var = sum((si[j] - mi) ** 2 for j in range(roll_w)) / (roll_w - 1)
            series.append({"date": aligned[i], "beta": round(cov / var, 3) if var > 0 else None})

        result = {"series": series, "roll_window": roll_w}
        cache[key] = {"data": result, "expires_at": now + RISK_TTL}
        save_cache(cache)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/risk/liquidity")
def api_risk_liquidity():
    portfolio   = load_portfolio()
    tickers     = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices      = get_cached_prices(tickers)
    funds       = get_cached_fundamentals(tickers)
    pdata       = build_portfolio_response(portfolio, prices, funds)
    fund_config = get_effective_fund_config()
    nav         = (pdata.get("total_value") or 0) + (fund_config.get("caixa") or 0) + (fund_config.get("proventos_a_receber") or 0)
    total_value = pdata.get("total_value") or 0

    liq_1d = liq_5d = liq_10d = 0.0
    rows_out = []
    missing_score_value = 0.0
    for r in pdata["rows"]:
        vl        = r.get("valor_liquido") or 0
        score     = r.get("liq_diaria_mm")
        if score is None:
            missing_score_value += vl
        days      = _liq_days_from_score(score)
        daily_pct = (1.0 / days) if days else None
        liq1d_v   = min(vl, vl * daily_pct)      if daily_pct else 0
        liq5d_v   = min(vl, vl * daily_pct * 5)  if daily_pct else 0
        liq10d_v  = min(vl, vl * daily_pct * 10) if daily_pct else 0
        liq_1d  += liq1d_v
        liq_5d  += liq5d_v
        liq_10d += liq10d_v
        rows_out.append({
            "ticker":       r["ticker"],
            "valor_liquido": round(vl, 2),
            "weight_pct":   r.get("pct_total"),
            "liq_score":    score,
            "days_to_liq":  round(days, 1) if days else None,
            "liq_1d_pct":   round(min(100, (daily_pct or 0) * 100), 1),
            "liq_5d_pct":   round(min(100, (daily_pct or 0) * 5 * 100), 1),
            "liq_10d_pct":  round(min(100, (daily_pct or 0) * 10 * 100), 1),
        })
    rows_out.sort(key=lambda x: x.get("days_to_liq") or 9999)

    # Detecta cold cache de fundamentals: sem average_volume, o score de
    # liquidez fica None para a posição e tudo é computado como 0%.
    missing_pct = (missing_score_value / total_value * 100) if total_value else 0
    warning = None
    if missing_pct >= 30:
        warning = (f"Scores de liquidez indisponíveis para {missing_pct:.0f}% do portfólio — "
                   "dados fundamentais ainda carregando. Recarregue a página em alguns segundos.")

    return jsonify({
        "nav_ref":              round(nav, 2),
        "total_equity_rs":      round(total_value, 2),
        "portfolio_liq_1d_pct":  round(liq_1d  / total_value * 100, 1) if total_value else 0,
        "portfolio_liq_5d_pct":  round(liq_5d  / total_value * 100, 1) if total_value else 0,
        "portfolio_liq_10d_pct": round(liq_10d / total_value * 100, 1) if total_value else 0,
        "portfolio_liq_1d_rs":   round(liq_1d,  2),
        "portfolio_liq_5d_rs":   round(liq_5d,  2),
        "portfolio_liq_10d_rs":  round(liq_10d, 2),
        "rows": rows_out,
        "warning": warning,
    })


@app.route("/api/risk/tracking-error")
def api_risk_tracking_error():
    import math
    window = int(request.args.get("window", 252))
    cache  = load_cache()
    now    = time.time()
    key    = f"risk_tracking_error_{window}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    history = load_quota_history()
    if len(history) < 22:
        return jsonify({"error": "Histórico insuficiente"}), 400

    start  = history[0]["data"]
    end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
    try:
        ibov_h = yf.Ticker("^BVSP").history(
            start=start, end=end_dt.strftime("%Y-%m-%d"), timeout=15)
        if ibov_h.empty:
            return jsonify({"error": "Sem dados do IBOV"}), 400
        ibov_map   = {str(d.date()): float(v) for d, v in ibov_h["Close"].items()}
        ibov_dates = sorted(ibov_map)
        ibov_rets  = {ibov_dates[i]: ibov_map[ibov_dates[i]] / ibov_map[ibov_dates[i - 1]] - 1
                      for i in range(1, len(ibov_dates))}

        fund_map = {}
        prev = history[0]["cota_fechamento"]
        for e in history[1:]:
            fund_map[e["data"]] = e["cota_fechamento"] / prev - 1
            prev = e["cota_fechamento"]

        aligned = sorted(d for d in fund_map if d in ibov_rets)
        aligned  = aligned[-window:]
        if len(aligned) < 20:
            return jsonify({"error": "Dados insuficientes"}), 400

        f_rets = [fund_map[d] for d in aligned]
        i_rets = [ibov_rets[d] for d in aligned]
        n      = len(aligned)

        excess  = [f - i for f, i in zip(f_rets, i_rets)]
        mean_ex = sum(excess) / n
        var_ex  = sum((e - mean_ex) ** 2 for e in excess) / (n - 1)
        te      = math.sqrt(var_ex) * math.sqrt(252)
        ret_ativo = mean_ex * 252
        ir      = ret_ativo / te if te > 0 else None

        result = {
            "window":               window,
            "tracking_error":       round(te * 100, 2),
            "information_ratio":    round(ir, 2) if ir is not None else None,
            "retorno_ativo_anual":  round(ret_ativo * 100, 2),
            "n_dias":               n,
        }
        cache[key] = {"data": result, "expires_at": now + RISK_TTL}
        save_cache(cache)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/risk/sortino-calmar")
def api_risk_sortino_calmar():
    import math
    cache = load_cache()
    now   = time.time()
    key   = "risk_sortino_calmar"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    history = load_quota_history()
    if len(history) < 22:
        return jsonify({"error": "Histórico insuficiente"}), 400

    entries   = [(datetime.strptime(e["data"], "%Y-%m-%d"), e["cota_fechamento"]) for e in history]
    last_date = entries[-1][0]
    cdi_map   = load_cdi_map()

    def cdi_ann_for_window(start_dt, end_dt):
        rates = [v for d, v in cdi_map.items()
                 if start_dt < datetime.strptime(d, "%Y-%m-%d") <= end_dt]
        if not rates:
            return None
        compound = 1.0
        for r in rates:
            compound *= (1 + r / 100)
        return (compound ** (252 / len(rates)) - 1) * 100

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

    def compute_sortino_calmar(sl):
        if len(sl) < 5:
            return {"sortino": None, "calmar": None, "downside_vol": None, "max_dd": None}
        cotas = [c for _, c in sl]
        daily = [(cotas[i] / cotas[i - 1] - 1) for i in range(1, len(cotas))]
        if len(daily) < 2:
            return {"sortino": None, "calmar": None, "downside_vol": None, "max_dd": None}
        n       = len(daily)
        ret_ann = (cotas[-1] / cotas[0]) ** (252 / n) - 1
        # Max drawdown
        peak   = cotas[0]
        max_dd = 0.0
        for c in cotas:
            if c > peak:
                peak = c
            dd = c / peak - 1
            if dd < max_dd:
                max_dd = dd
        # Downside deviation (MAR = 0)
        neg = [r for r in daily if r < 0]
        if neg:
            downside_dev = math.sqrt(sum(r ** 2 for r in neg) / n) * math.sqrt(252)
        else:
            downside_dev = 0
        dates = [d for d, _ in sl]
        cdi   = cdi_ann_for_window(dates[0], dates[-1])
        sortino = round((ret_ann * 100 - (cdi or 0)) / (downside_dev * 100), 2) if downside_dev > 0 else None
        calmar  = round(ret_ann / abs(max_dd), 2) if max_dd < 0 else None
        return {
            "sortino":      sortino,
            "calmar":       calmar,
            "downside_vol": round(downside_dev * 100, 2),
            "max_dd":       round(max_dd * 100, 2),
        }

    windows = [
        ("no_mes", get_window(no_mes=True)),
        ("no_ano", get_window(ytd=True)),
        ("3m",     get_window(months_back=3)),
        ("6m",     get_window(months_back=6)),
        ("12m",    get_window(months_back=12)),
        ("24m",    get_window(months_back=24)),
        ("36m",    get_window(months_back=36)),
        ("total",  entries),
    ]
    result = {"windows": {k: compute_sortino_calmar(sl) for k, sl in windows}}
    cache[key] = {"data": result, "expires_at": now + RISK_TTL}
    save_cache(cache)
    return jsonify(result)


@app.route("/api/risk/capture")
def api_risk_capture():
    window = request.args.get("window", "252")
    cache  = load_cache()
    now    = time.time()
    key    = f"risk_capture_{window}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    history = load_quota_history()
    if len(history) < 22:
        return jsonify({"error": "Histórico insuficiente"}), 400

    start  = history[0]["data"]
    end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
    try:
        ibov_h = yf.Ticker("^BVSP").history(
            start=start, end=end_dt.strftime("%Y-%m-%d"), timeout=15)
        if ibov_h.empty:
            return jsonify({"error": "Sem dados do IBOV"}), 400
        ibov_map   = {str(d.date()): float(v) for d, v in ibov_h["Close"].items()}
        ibov_dates = sorted(ibov_map)
        ibov_rets  = {ibov_dates[i]: ibov_map[ibov_dates[i]] / ibov_map[ibov_dates[i - 1]] - 1
                      for i in range(1, len(ibov_dates))}

        fund_map = {}
        prev = history[0]["cota_fechamento"]
        for e in history[1:]:
            fund_map[e["data"]] = e["cota_fechamento"] / prev - 1
            prev = e["cota_fechamento"]

        aligned = sorted(d for d in fund_map if d in ibov_rets)
        if window != "total":
            aligned = aligned[-int(window):]
        if len(aligned) < 10:
            return jsonify({"error": "Dados insuficientes"}), 400

        f_rets = [fund_map[d] for d in aligned]
        i_rets = [ibov_rets[d] for d in aligned]

        up_idx   = [i for i in range(len(aligned)) if i_rets[i] > 0]
        down_idx = [i for i in range(len(aligned)) if i_rets[i] < 0]

        def _capture(indices):
            if not indices:
                return None
            fund_cum = 1.0
            ibov_cum = 1.0
            for idx in indices:
                fund_cum *= (1 + f_rets[idx])
                ibov_cum *= (1 + i_rets[idx])
            ibov_tot = ibov_cum - 1
            if abs(ibov_tot) < 1e-10:
                return None
            return round((fund_cum - 1) / ibov_tot * 100, 1)

        result = {
            "window":           window,
            "upside_capture":   _capture(up_idx),
            "downside_capture": _capture(down_idx),
            "n_dias_up":        len(up_idx),
            "n_dias_down":      len(down_idx),
            "n_total":          len(aligned),
        }
        cache[key] = {"data": result, "expires_at": now + RISK_TTL}
        save_cache(cache)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/risk/concentration")
def api_risk_concentration():
    portfolio   = load_portfolio()
    tickers     = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices      = get_cached_prices(tickers)
    funds       = get_cached_fundamentals(tickers)
    pdata       = build_portfolio_response(portfolio, prices, funds)
    total_value = pdata.get("total_value") or 0
    if not total_value:
        return jsonify({"error": "Sem dados de portfólio"}), 400

    sector_map = {}
    for r in pdata["rows"]:
        vl     = r.get("valor_liquido") or 0
        sector = r.get("sector") or "Outros"
        if sector not in sector_map:
            sector_map[sector] = {"tickers": [], "valor": 0.0}
        sector_map[sector]["tickers"].append(r["ticker"])
        sector_map[sector]["valor"] += vl

    setores = []
    hhi     = 0.0
    for setor, data in sector_map.items():
        peso = data["valor"] / total_value
        hhi += peso ** 2
        setores.append({
            "setor":    setor,
            "peso_pct": round(peso * 100, 2),
            "valor_rs": round(data["valor"], 2),
            "tickers":  data["tickers"],
        })
    setores.sort(key=lambda x: x["peso_pct"], reverse=True)

    hhi_score = int(round(hhi * 10000))
    if hhi_score < 1000:
        hhi_label = "diversificado"
    elif hhi_score < 2500:
        hhi_label = "moderado"
    else:
        hhi_label = "concentrado"

    sorted_rows = sorted(pdata["rows"], key=lambda x: x.get("pct_total") or 0, reverse=True)
    top1 = sum(r.get("pct_total") or 0 for r in sorted_rows[:1])
    top3 = sum(r.get("pct_total") or 0 for r in sorted_rows[:3])
    top5 = sum(r.get("pct_total") or 0 for r in sorted_rows[:5])

    # Sinaliza quando o cache de fundamentals está frio e a maior parte do
    # portfólio caiu em "Outros" — HHI nesse caso não representa concentração
    # setorial real e usuário deve recarregar.
    peso_outros = next((s["peso_pct"] for s in setores if s["setor"] == "Outros"), 0)
    warning = None
    if peso_outros >= 30:
        warning = (f"Setores indisponíveis para {peso_outros:.0f}% do portfólio — "
                   "dados fundamentais ainda carregando. Recarregue a página em alguns segundos.")

    return jsonify({
        "hhi":        hhi_score,
        "hhi_label":  hhi_label,
        "setores":    setores,
        "top1_pct":   round(top1, 2),
        "top3_pct":   round(top3, 2),
        "top5_pct":   round(top5, 2),
        "n_posicoes": len(pdata["rows"]),
        "n_setores":  len(setores),
        "warning":    warning,
    })


@app.route("/api/risk/fx-exposure")
def api_risk_fx_exposure():
    portfolio   = load_portfolio()
    tickers     = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices      = get_cached_prices(tickers)
    funds       = get_cached_fundamentals(tickers)
    pdata       = build_portfolio_response(portfolio, prices, funds)
    fund_config = get_effective_fund_config()
    nav         = (pdata.get("total_value") or 0) + (fund_config.get("caixa") or 0) + (fund_config.get("proventos_a_receber") or 0)
    total_value = pdata.get("total_value") or 0
    if not total_value:
        return jsonify({"error": "Sem dados de portfólio"}), 400

    bdrs     = [r for r in pdata["rows"] if r.get("categoria") == "BDR"]
    total_fx = sum(r.get("valor_liquido") or 0 for r in bdrs)
    fx_pct   = total_fx / total_value

    bdr_rows = sorted([{
        "ticker":   r["ticker"],
        "peso_pct": round((r.get("valor_liquido") or 0) / total_value * 100, 2),
        "valor_rs": round(r.get("valor_liquido") or 0, 2),
        "sector":   r.get("sector") or "—",
    } for r in bdrs], key=lambda x: x["peso_pct"], reverse=True)

    sens = {}
    for shock in [5, 10, -5, -10]:
        k = f"usd_{'plus' if shock > 0 else 'minus'}{abs(shock)}"
        sens[k] = round(fx_pct * shock, 2)

    return jsonify({
        "total_fx_exposure_pct": round(fx_pct * 100, 2),
        "total_fx_exposure_rs":  round(total_fx, 2),
        "nav_ref":               round(nav, 2),
        "bdrs":                  bdr_rows,
        "sensibilidade_pct":     sens,
    })


@app.route("/api/risk/rolling-ratios")
def api_risk_rolling_ratios():
    import math
    roll_w = int(request.args.get("roll_window", 63))
    cache  = load_cache()
    now    = time.time()
    key    = f"risk_rolling_ratios_{roll_w}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    history = load_quota_history()
    if len(history) < roll_w + 5:
        return jsonify({"error": "Histórico insuficiente"}), 400

    cotas       = [e["cota_fechamento"] for e in history]
    dates       = [e["data"] for e in history]
    daily       = [(cotas[i] / cotas[i - 1] - 1) for i in range(1, len(cotas))]
    daily_dates = dates[1:]

    # CDI diário médio como proxy da taxa livre de risco
    cdi_map  = load_cdi_map()
    cdi_vals = list(cdi_map.values())
    cdi_daily = (sum(cdi_vals[-252:]) / min(252, len(cdi_vals))) / 100 if cdi_vals else 0.0

    series       = []
    sharpe_vals  = []
    sortino_vals = []

    for i in range(roll_w, len(daily)):
        sl  = daily[i - roll_w: i]
        n   = len(sl)
        mn  = sum(sl) / n
        var = sum((r - mn) ** 2 for r in sl) / (n - 1) if n > 1 else 0
        std = math.sqrt(var) if var > 0 else 0
        vol_ann = std * math.sqrt(252)
        ret_ann = (1 + mn) ** 252 - 1
        rf_ann  = (1 + cdi_daily) ** 252 - 1

        sharpe  = round((ret_ann - rf_ann) / vol_ann, 2) if vol_ann > 0 else None

        neg = [r for r in sl if r < 0]
        if neg:
            dd_ann = math.sqrt(sum(r ** 2 for r in neg) / n) * math.sqrt(252)
        else:
            dd_ann = 0
        sortino = round((ret_ann - rf_ann) / dd_ann, 2) if dd_ann > 0 else None

        series.append({
            "date":    daily_dates[i],
            "sharpe":  sharpe,
            "sortino": sortino,
        })
        if sharpe is not None:
            sharpe_vals.append(sharpe)
        if sortino is not None:
            sortino_vals.append(sortino)

    current = series[-1] if series else {}
    result  = {
        "roll_window":    roll_w,
        "series":         series,
        "current_sharpe": current.get("sharpe"),
        "current_sortino":current.get("sortino"),
        "avg_sharpe":     round(sum(sharpe_vals)  / len(sharpe_vals),  2) if sharpe_vals  else None,
        "avg_sortino":    round(sum(sortino_vals) / len(sortino_vals), 2) if sortino_vals else None,
    }
    cache[key] = {"data": result, "expires_at": now + RISK_TTL}
    save_cache(cache)
    return jsonify(result)


@app.route("/api/risk/return-distribution")
def api_risk_return_distribution():
    import math
    window = int(request.args.get("window", 252))
    cache  = load_cache()
    now    = time.time()
    key    = f"risk_return_dist_{window}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return jsonify(cache[key]["data"])

    history = load_quota_history()
    if len(history) < 22:
        return jsonify({"error": "Histórico insuficiente"}), 400

    cotas = [e["cota_fechamento"] for e in history]
    rets  = [(cotas[i] / cotas[i - 1] - 1) for i in range(1, len(cotas))]
    rets  = rets[-window:]
    n     = len(rets)

    mean_r   = sum(rets) / n
    variance = sum((r - mean_r) ** 2 for r in rets) / (n - 1) if n > 1 else 0
    std_r    = math.sqrt(variance) if variance > 0 else 0

    skew = (sum((r - mean_r) ** 3 for r in rets) / n) / (std_r ** 3) if std_r > 0 and n > 2 else 0
    kurt = (sum((r - mean_r) ** 4 for r in rets) / n) / (std_r ** 4) - 3 if std_r > 0 and n > 3 else 0

    min_r    = min(rets)
    max_r    = max(rets)
    n_bins   = 20
    bin_size = (max_r - min_r) / n_bins if max_r > min_r else 0.001
    bins     = [min_r + i * bin_size for i in range(n_bins + 1)]
    counts   = [0] * n_bins
    for r in rets:
        idx = min(int((r - min_r) / bin_size), n_bins - 1)
        counts[idx] += 1

    sorted_r = sorted(rets)
    def pct(p): return sorted_r[max(0, int(p * n / 100) - 1)]

    # IBOV comparison
    start_h    = history[-min(window + 5, len(history))]["data"]
    end_dt     = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
    ibov_counts = None
    ibov_mean   = None
    ibov_std    = None
    try:
        ibov_h = yf.Ticker("^BVSP").history(
            start=start_h, end=end_dt.strftime("%Y-%m-%d"), timeout=15)
        if not ibov_h.empty:
            ic    = list(ibov_h["Close"])
            ir    = [(ic[i] / ic[i - 1] - 1) for i in range(1, len(ic))]
            ir    = ir[-window:]
            ni    = len(ir)
            mi    = sum(ir) / ni
            vi    = sum((r - mi) ** 2 for r in ir) / ni if ni > 1 else 0
            ibov_mean   = round(mi * 100, 3)
            ibov_std    = round(math.sqrt(vi) * 100, 3)
            ibov_counts = [0] * n_bins
            for r in ir:
                idx = min(int((r - min_r) / bin_size), n_bins - 1)
                if 0 <= idx < n_bins:
                    ibov_counts[idx] += 1
    except Exception:
        pass

    bin_centers = [round((bins[i] + bins[i + 1]) / 2 * 100, 3) for i in range(n_bins)]

    result = {
        "window":       window,
        "n_obs":        n,
        "bin_centers":  bin_centers,
        "counts":       counts,
        "ibov_counts":  ibov_counts,
        "mean_pct":     round(mean_r * 100, 3),
        "std_pct":      round(std_r * 100, 3),
        "skewness":     round(skew, 3),
        "kurtosis":     round(kurt, 3),
        "pct_positive": round(sum(1 for r in rets if r > 0) / n * 100, 1),
        "best_day":     round(max(rets) * 100, 3),
        "worst_day":    round(min(rets) * 100, 3),
        "p5":           round(pct(5) * 100, 3),
        "p95":          round(pct(95) * 100, 3),
        "ibov_mean_pct":ibov_mean,
        "ibov_std_pct": ibov_std,
    }
    cache[key] = {"data": result, "expires_at": now + RISK_TTL}
    save_cache(cache)
    return jsonify(result)


FINANCIALS_TTL = 6 * 3600  # 6 hours

_INCOME_ROWS = [
    "Total Revenue",
    "Cost Of Revenue",
    "Gross Profit",
    "Operating Expense",
    "Selling General Administrative",
    "General Administrative Expense",
    "Selling Expense",
    "Other Operating Expenses",
    "Operating Income",
    "Net Non Operating Interest Income Expense",
    "Interest Income Non Operating",
    "Interest Expense Non Operating",
    "Total Other Finance Cost",
    "Pretax Income",
    "Tax Provision",
    "Net Income",
    "Basic EPS",
    "Diluted EPS",
    "EBITDA",
]

def _df_to_rows(df, row_order=None):
    """Convert a yfinance financial DataFrame to JSON-serializable structure."""
    if df is None or df.empty:
        return None, None
    # Columns are datetime objects → format as strings
    cols = [c.strftime("%d/%m/%y") if hasattr(c, "strftime") else str(c) for c in df.columns]
    if row_order:
        present = [r for r in row_order if r in df.index]
        extra   = [r for r in df.index if r not in row_order]
        ordered = present + extra
    else:
        ordered = list(df.index)
    rows = []
    for label in ordered:
        if label not in df.index:
            continue
        values = []
        for val in df.loc[label]:
            if val is None or (isinstance(val, float) and (val != val)):  # NaN check
                values.append(None)
            else:
                try:
                    values.append(int(val))
                except (TypeError, ValueError):
                    values.append(None)
        rows.append({"label": label, "values": values})
    return cols, rows


@app.route("/api/financials/<ticker>")
def get_financials(ticker):
    period    = request.args.get("period",    "annual")    # annual | quarterly
    statement = request.args.get("statement", "income")    # income | balance | cashflow

    cache = load_cache()
    key   = f"financials_{ticker}_{period}_{statement}"
    now   = time.time()

    if key in cache and cache[key].get("expires_at", 0) > now:
        return jsonify(cache[key]["data"])

    try:
        t = yf.Ticker(ticker)
        if period == "quarterly":
            if statement == "income":
                df = t.quarterly_income_stmt
            elif statement == "balance":
                df = t.quarterly_balance_sheet
            else:
                df = t.quarterly_cashflow
        else:
            if statement == "income":
                df = t.income_stmt
            elif statement == "balance":
                df = t.balance_sheet
            else:
                df = t.cashflow

        row_order = _INCOME_ROWS if statement == "income" else None
        cols, rows = _df_to_rows(df, row_order)

        if cols is None:
            result = {"available": False, "ticker": ticker, "period": period, "statement": statement}
        else:
            result = {
                "available": True,
                "ticker":    ticker,
                "period":    period,
                "statement": statement,
                "columns":   cols,
                "rows":      rows,
            }
    except Exception as e:
        result = {"available": False, "ticker": ticker, "period": period, "statement": statement, "error": str(e)}

    cache[key] = {"data": result, "expires_at": now + FINANCIALS_TTL}
    save_cache(cache)
    return jsonify(result)


# ─── PRÉ-TRADE ────────────────────────────────────────────────────────────────

@app.route("/api/pretrade/simulate", methods=["POST"])
@require_admin
def api_pretrade_simulate():
    import copy
    payload = request.json or {}

    # Aceita basket {operacoes: [...]} ou formato legado {ticker, quantidade, ...}
    if "operacoes" in payload:
        ops_input = payload["operacoes"]
    else:
        ops_input = [{
            "ticker":        payload.get("ticker", "").strip(),
            "quantidade":    payload.get("quantidade", 0),
            "direcao":       payload.get("direcao", "compra"),
            "preco":         payload.get("preco", 0),
            "corretagem_rs": payload.get("corretagem_rs", 0),
        }]

    if not ops_input:
        return jsonify({"error": "Informe ao menos uma operação"}), 400

    # Validar e normalizar tickers
    for op in ops_input:
        t = str(op.get("ticker") or "").strip()
        if not t:
            return jsonify({"error": "ticker é obrigatório em todas as operações"}), 400
        if "." not in t:
            t += ".SA"
        op["ticker"] = t.upper()
        op["preco"]      = float(op.get("preco") or 0)
        op["quantidade"] = float(op.get("quantidade") or 0)
        op["direcao"]    = str(op.get("direcao") or "compra").lower()
        op["corretagem_rs"] = float(op.get("corretagem_rs") or 0)
        if op["preco"] <= 0:
            return jsonify({"error": f"Preço inválido para {op['ticker']}"}), 400
        if op["direcao"] not in ("compra", "venda", "zerar"):
            return jsonify({"error": f"Direção inválida para {op['ticker']}"}), 400

    portfolio    = load_portfolio()
    fund_config  = get_effective_fund_config()
    tickers_cart = [p["yahoo_ticker"] for p in portfolio["positions"]]

    tickers_all = list(tickers_cart)
    for op in ops_input:
        if op["ticker"] not in tickers_all:
            tickers_all.append(op["ticker"])

    prices       = get_cached_prices(tickers_all)
    fundamentals = get_cached_fundamentals(tickers_all)

    # ── ESTADO ANTES ──
    pdata_antes = build_portfolio_response(portfolio, prices, fundamentals)
    total_antes = pdata_antes.get("total_value") or 0
    quota_antes = calculate_quota(pdata_antes["rows"], fund_config, prices)
    conc_antes  = _calcular_concentracao_pretrade(pdata_antes["rows"], total_antes)

    # Grupo I antes (ações + BDRs — Res. CVM 175)
    _GRUPO1_CATS = {"Acao", "BDR", "Acao BDR"}
    nav_antes = quota_antes.get("nav_total") or total_antes
    valor_g1_antes = sum(
        (r.get("valor_liquido") or 0)
        for r in pdata_antes["rows"]
        if (r.get("categoria") or "Acao") in _GRUPO1_CATS
    )
    pct_g1_antes = (valor_g1_antes / nav_antes * 100) if nav_antes else 0

    # ── CLONAR ──
    portfolio_sim   = copy.deepcopy(portfolio)
    fund_config_sim = copy.deepcopy(fund_config)
    prices_sim      = copy.deepcopy(prices)

    ops_processadas = []
    custo_basket    = 0.0

    for op in ops_input:
        ticker     = op["ticker"]
        quantidade = op["quantidade"]
        direcao    = op["direcao"]
        preco      = op["preco"]
        corretagem = op["corretagem_rs"]

        # Atualizar preço simulado
        if ticker in prices_sim:
            prices_sim[ticker] = dict(prices_sim[ticker])
            prices_sim[ticker]["price"] = preco
        else:
            prices_sim[ticker] = {"price": preco, "change_pct": 0.0}

        pos_existente = next((p for p in portfolio["positions"] if p["yahoo_ticker"] == ticker), None)
        pos_sim       = next((p for p in portfolio_sim["positions"] if p["yahoo_ticker"] == ticker), None)
        valor_op      = preco * quantidade

        if direcao == "compra":
            if pos_sim:
                pos_sim["quantidade"] = (pos_sim.get("quantidade") or 0) + quantidade
            else:
                portfolio_sim["positions"].append({
                    "ticker": ticker.replace(".SA", ""), "yahoo_ticker": ticker,
                    "categoria": "Acao", "quantidade": quantidade,
                    "liq_diaria_mm": None, "lucro_mi_26": None, "preco_alvo": None,
                })
            fund_config_sim["caixa"] = (fund_config_sim.get("caixa") or 0) - valor_op - corretagem
            custo_op = valor_op + corretagem
        elif direcao == "venda":
            if pos_sim:
                pos_sim["quantidade"] = max(0, (pos_sim.get("quantidade") or 0) - quantidade)
            fund_config_sim["caixa"] = (fund_config_sim.get("caixa") or 0) + valor_op - corretagem
            custo_op = -(valor_op - corretagem)
        else:  # zerar
            qtd_atual  = (pos_sim or {}).get("quantidade") or 0
            portfolio_sim["positions"] = [p for p in portfolio_sim["positions"] if p["yahoo_ticker"] != ticker]
            fund_config_sim["caixa"] = (fund_config_sim.get("caixa") or 0) + preco * qtd_atual - corretagem
            quantidade = qtd_atual
            valor_op   = preco * quantidade
            custo_op   = -(valor_op - corretagem)

        custo_basket += custo_op
        sector_ativo  = (fundamentals.get(ticker) or {}).get("sector") or "Outros"
        ops_processadas.append({
            "ticker":       ticker.replace(".SA", ""),
            "yahoo_ticker": ticker,
            "is_novo":      pos_existente is None and direcao == "compra",
            "sector":       sector_ativo,
            "direcao":      direcao,
            "quantidade":   quantidade,
            "preco":        preco,
            "valor_total_rs": round(valor_op, 2),
            "corretagem_rs":  corretagem,
            "custo_op_rs":    round(custo_op, 2),
        })

    # Remover posições zeradas
    portfolio_sim["positions"] = [p for p in portfolio_sim["positions"] if (p.get("quantidade") or 0) > 0]

    # ── ESTADO DEPOIS ──
    pdata_depois = build_portfolio_response(portfolio_sim, prices_sim, fundamentals)
    total_depois = pdata_depois.get("total_value") or 0
    quota_depois = calculate_quota(pdata_depois["rows"], fund_config_sim, prices_sim)
    conc_depois  = _calcular_concentracao_pretrade(pdata_depois["rows"], total_depois) if total_depois else {"por_ativo": {}, "por_setor": {}, "hhi": 0}

    nav_depois = quota_depois.get("nav_total") or total_depois
    valor_g1_depois = sum(
        (r.get("valor_liquido") or 0)
        for r in pdata_depois["rows"]
        if (r.get("categoria") or "Acao") in _GRUPO1_CATS
    )
    pct_g1_depois = (valor_g1_depois / nav_depois * 100) if nav_depois else 0

    cota_antes_v  = quota_antes.get("cota_estimada") or quota_antes.get("quota_fechamento") or 0
    cota_depois_v = quota_depois.get("cota_estimada") or quota_depois.get("quota_fechamento") or 0
    imp_por_cota  = round(cota_depois_v - cota_antes_v, 8)
    caixa_depois  = fund_config_sim.get("caixa") or 0

    # ── COMPLIANCE — Resolução CVM 175 + limites internos (condicionais) ──
    lim_ativo  = float(fund_config.get("limite_concentracao_ativo_pct") or 20.0)
    lim_setor  = float(fund_config.get("limite_concentracao_setor_pct") or 40.0)
    ativo_on   = bool(fund_config.get("enable_concentracao_ativo", False))
    setor_on   = bool(fund_config.get("enable_concentracao_setor", False))

    def _status_max(valor, limite):
        if valor > limite:          return "violacao"
        if valor > limite * 0.85:   return "alerta"
        return "ok"

    def _status_min(valor, minimo):
        if valor < minimo * 0.85:   return "violacao"
        if valor < minimo:          return "alerta"
        return "ok"

    compliance = [
        # Regra regulatória obrigatória: mínimo 67% Grupo I (Res. CVM 175)
        {
            "regra": "Mín. 67% em Ações/BDRs — Grupo I (Res. CVM 175)",
            "limite_pct": 67.0,
            "valor_antes_pct": round(pct_g1_antes, 2),
            "valor_depois_pct": round(pct_g1_depois, 2),
            "status": _status_min(pct_g1_depois, 67.0),
            "tipo": "minimo",
        },
    ]

    # Limites internos por ativo (apenas se habilitado)
    if ativo_on:
        tickers_tocados = {op["yahoo_ticker"] for op in ops_processadas}
        for ytk in sorted(tickers_tocados):
            pct_d = conc_depois["por_ativo"].get(ytk, 0.0)
            pct_a = conc_antes["por_ativo"].get(ytk, 0.0)
            compliance.append({
                "regra": f"Conc. por Ativo — {ytk.replace('.SA','')} (interno)",
                "limite_pct": lim_ativo,
                "valor_antes_pct": round(pct_a, 2),
                "valor_depois_pct": round(pct_d, 2),
                "status": _status_max(pct_d, lim_ativo),
                "tipo": "maximo",
            })

    # Limites internos por setor (apenas se habilitado)
    if setor_on:
        setores_tocados = {op["sector"] for op in ops_processadas}
        for setor in sorted(setores_tocados):
            pct_d = conc_depois["por_setor"].get(setor, 0.0)
            pct_a = conc_antes["por_setor"].get(setor, 0.0)
            compliance.append({
                "regra": f"Conc. por Setor — {setor} (interno)",
                "limite_pct": lim_setor,
                "valor_antes_pct": round(pct_a, 2),
                "valor_depois_pct": round(pct_d, 2),
                "status": _status_max(pct_d, lim_setor),
                "tipo": "maximo",
            })

    # Caixa disponível
    if caixa_depois < 0:
        compliance.append({
            "regra": "Caixa Disponível",
            "limite_pct": 0,
            "valor_antes_pct": round(fund_config.get("caixa") or 0, 2),
            "valor_depois_pct": round(caixa_depois, 2),
            "status": "alerta",
            "tipo": "caixa",
        })

    return jsonify({
        "operacoes": ops_processadas,
        "basket": {
            "custo_total_rs": round(custo_basket, 2),
            "num_operacoes":  len(ops_processadas),
        },
        "antes": {
            "nav_total":       round(nav_antes, 2),
            "cota_estimada":   round(cota_antes_v, 8),
            "weighted_beta":   round(pdata_antes.get("weighted_beta") or 0, 4),
            "weighted_upside": round(pdata_antes.get("weighted_upside") or 0, 2),
            "hhi":   conc_antes["hhi"],
            "caixa": round(fund_config.get("caixa") or 0, 2),
            "pct_grupo1": round(pct_g1_antes, 2),
        },
        "depois": {
            "nav_total":       round(nav_depois, 2),
            "cota_estimada":   round(cota_depois_v, 8),
            "weighted_beta":   round(pdata_depois.get("weighted_beta") or 0, 4),
            "weighted_upside": round(pdata_depois.get("weighted_upside") or 0, 2),
            "hhi":   conc_depois["hhi"],
            "caixa": round(caixa_depois, 2),
            "pct_grupo1": round(pct_g1_depois, 2),
        },
        "impactos": {
            "variacao_cota_pct":  round((cota_depois_v / cota_antes_v - 1) * 100, 4) if cota_antes_v else 0,
            "variacao_nav_rs":    round(nav_depois - nav_antes, 2),
            "variacao_beta":      round((pdata_depois.get("weighted_beta") or 0) - (pdata_antes.get("weighted_beta") or 0), 4),
            "variacao_upside_pp": round((pdata_depois.get("weighted_upside") or 0) - (pdata_antes.get("weighted_upside") or 0), 2),
            "variacao_hhi":       conc_depois["hhi"] - conc_antes["hhi"],
            "impacto_por_cota_rs": imp_por_cota,
        },
        "compliance": compliance,
        "parametros_compliance": {
            "grupo1_minimo_pct":             67.0,
            "enable_concentracao_ativo":     ativo_on,
            "limite_concentracao_ativo_pct": lim_ativo,
            "enable_concentracao_setor":     setor_on,
            "limite_concentracao_setor_pct": lim_setor,
        },
        "rows_depois": [
            {
                "ticker":        r["ticker"],
                "yahoo_ticker":  r.get("yahoo_ticker", ""),
                "pct_total":     round(r.get("pct_total") or 0, 2),
                "valor_liquido": round(r.get("valor_liquido") or 0, 2),
            }
            for r in sorted(pdata_depois["rows"], key=lambda x: x.get("pct_total") or 0, reverse=True)
        ],
        "rows_antes": [
            {
                "ticker":        r["ticker"],
                "yahoo_ticker":  r.get("yahoo_ticker", ""),
                "pct_total":     round(r.get("pct_total") or 0, 2),
                "valor_liquido": round(r.get("valor_liquido") or 0, 2),
            }
            for r in sorted(pdata_antes["rows"], key=lambda x: x.get("pct_total") or 0, reverse=True)
        ],
    })


# ─── EVENTOS CORPORATIVOS ──────────────────────────────────────────────────────

EVENTS_TTL = 24 * 3600

def _evento_descricao(tipo, confirmado):
    mapa = {
        "RESULTADO": "Earnings Date" if confirmado else "Earnings Date (estimado)",
        "DIVIDENDO": "Proventos declarados" if confirmado else "Proventos pagos",
        "EX-DIV":   "Data ex-dividendo",
        "SPLIT":    "Desdobramento de ações",
    }
    return mapa.get(tipo, tipo)

def fetch_events(tickers):
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed
    hoje = datetime.now().date()

    def _fetch_one(yticker):
        eventos = []
        try:
            t = yf.Ticker(yticker)

            # Earnings date via calendar
            try:
                cal = t.calendar
                if cal:
                    earnings = cal.get("Earnings Date") or cal.get("earnings_date")
                    if earnings is not None:
                        datas = earnings if isinstance(earnings, (list, tuple)) else [earnings]
                        for d in datas[:1]:  # só o primeiro (mais provável)
                            try:
                                dstr = str(d.date()) if hasattr(d, "date") else str(d)[:10]
                                eventos.append({"tipo": "RESULTADO", "data": dstr, "valor": None, "confirmado": False})
                            except Exception:
                                pass
            except Exception:
                pass

            # Dividendos históricos (últimos 180 dias)
            try:
                divs = t.dividends
                if divs is not None and len(divs) > 0:
                    corte = pd.Timestamp(hoje) - pd.Timedelta(days=180)
                    divs_rec = divs[divs.index >= corte]
                    for ts, valor in divs_rec.items():
                        try:
                            dstr = str(ts.date()) if hasattr(ts, "date") else str(ts)[:10]
                            eventos.append({"tipo": "DIVIDENDO", "data": dstr, "valor": _round(float(valor), 4), "confirmado": True})
                        except Exception:
                            pass
            except Exception:
                pass

            # Ex-dividend date via info
            try:
                info = t.info or {}
                ex_div_ts = info.get("exDividendDate")
                if ex_div_ts:
                    import datetime as _dt
                    if isinstance(ex_div_ts, (int, float)):
                        ex_date = _dt.date.fromtimestamp(ex_div_ts)
                    elif hasattr(ex_div_ts, "date"):
                        ex_date = ex_div_ts.date()
                    else:
                        ex_date = None
                    if ex_date:
                        last_div = info.get("lastDividendValue") or info.get("dividendRate")
                        eventos.append({"tipo": "EX-DIV", "data": str(ex_date), "valor": _round(float(last_div), 4) if last_div else None, "confirmado": True})
            except Exception:
                pass

        except Exception:
            pass

        return yticker, eventos

    result = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_fetch_one, t): t for t in tickers}
        for f in as_completed(futures):
            try:
                yticker, evs = f.result()
                result[yticker] = evs
            except Exception:
                pass
    return result

def get_cached_events(tickers):
    cache = load_cache()
    now   = time.time()
    key   = "events_v1"
    if key in cache and now < cache[key].get("expires_at", 0):
        return cache[key]["data"]
    fresh = fetch_events(tickers)
    cache[key] = {"data": fresh, "expires_at": now + EVENTS_TTL}
    save_cache(cache)
    return fresh

@app.route("/api/events")
def api_events():
    portfolio   = load_portfolio()
    positions   = portfolio["positions"]
    tickers     = [p["yahoo_ticker"] for p in positions]
    ticker_map  = {p["yahoo_ticker"]: p["ticker"] for p in positions}

    dias_futuro      = int(request.args.get("dias_futuro", 90))
    incl_historico   = request.args.get("incluir_historico", "1") != "0"
    force            = request.args.get("force", "0") == "1"

    if force:
        cache = load_cache()
        cache.pop("events_v1", None)
        save_cache(cache)

    eventos_por_ticker = get_cached_events(tickers)
    hoje = datetime.now().date()

    todos_eventos = []
    for yahoo_ticker, eventos in eventos_por_ticker.items():
        for ev in eventos:
            try:
                from datetime import date as _date
                data_ev = datetime.strptime(ev["data"], "%Y-%m-%d").date()
            except Exception:
                continue
            dias = (data_ev - hoje).days
            eh_futuro = 0 <= dias <= dias_futuro
            eh_hist   = incl_historico and -180 <= dias < 0
            if not (eh_futuro or eh_hist):
                continue
            todos_eventos.append({
                "ticker":         ticker_map.get(yahoo_ticker, yahoo_ticker.replace(".SA", "")),
                "yahoo_ticker":   yahoo_ticker,
                "tipo":           ev["tipo"],
                "data":           ev["data"],
                "dias_ate_evento": dias,
                "valor":          ev.get("valor"),
                "confirmado":     ev.get("confirmado", False),
                "descricao":      _evento_descricao(ev["tipo"], ev.get("confirmado", False)),
            })

    todos_eventos.sort(key=lambda x: x["data"])

    por_ativo = {}
    for ev in todos_eventos:
        por_ativo.setdefault(ev["yahoo_ticker"], []).append(ev)

    return jsonify({
        "eventos":    todos_eventos,
        "por_ativo":  por_ativo,
        "gerado_em":  datetime.now().isoformat(),
    })


# ---------------------------------------------------------------------------
# PRÉ-TRADE HISTORY — persistência e PDF
# ---------------------------------------------------------------------------

def _generate_pretrade_pdf(record):
    """Gera PDF de auditoria de uma simulação de pré-trade. Retorna bytes."""
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    # ── Cores ──
    C_BG      = colors.HexColor("#0d0d1a")
    C_HDR     = colors.HexColor("#1a1a2e")
    C_HDR_TXT = colors.white
    C_OK      = colors.HexColor("#00cc88")
    C_ALERTA  = colors.HexColor("#f5a623")
    C_VIOL    = colors.HexColor("#cc3333")
    C_COMPRA  = colors.HexColor("#f5a623")
    C_VENDA   = colors.HexColor("#00cc88")
    C_ZERAR   = colors.HexColor("#cc3333")
    C_BODY    = colors.HexColor("#cccccc")
    C_MUTED   = colors.HexColor("#888888")
    C_LINE    = colors.HexColor("#333333")

    def status_color(s):
        return C_OK if s == "ok" else C_ALERTA if s == "alerta" else C_VIOL

    def dir_color(d):
        return C_COMPRA if d == "compra" else C_VENDA if d == "venda" else C_ZERAR

    styles = getSampleStyleSheet()
    mono   = "Courier"

    st_title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=14,
                               textColor=C_HDR_TXT, spaceAfter=4)
    st_sub   = ParagraphStyle("sub",   fontName="Helvetica",      fontSize=9,
                               textColor=C_MUTED,   spaceAfter=2)
    st_sec   = ParagraphStyle("sec",   fontName="Helvetica-Bold", fontSize=10,
                               textColor=C_HDR_TXT, spaceBefore=10, spaceAfter=4)
    st_foot  = ParagraphStyle("foot",  fontName="Helvetica",      fontSize=8,
                               textColor=C_MUTED,   alignment=1, spaceBefore=6)

    def tbl_style(header_rows=1, extra=None):
        base = [
            ("BACKGROUND",  (0, 0), (-1, header_rows - 1), C_HDR),
            ("TEXTCOLOR",   (0, 0), (-1, header_rows - 1), C_HDR_TXT),
            ("FONTNAME",    (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 8),
            ("FONTNAME",    (0, header_rows), (-1, -1), mono),
            ("TEXTCOLOR",   (0, header_rows), (-1, -1), C_BODY),
            ("BACKGROUND",  (0, header_rows), (-1, -1), C_BG),
            ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [C_BG, colors.HexColor("#0f0f22")]),
            ("GRID",        (0, 0), (-1, -1), 0.3, C_LINE),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]
        if extra:
            base.extend(extra)
        return TableStyle(base)

    def fmt(v, dec=2):
        try:
            return f"{float(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(v) if v is not None else "—"

    def fmtR(v, dec=2):
        return f"R$ {fmt(v, dec)}" if v is not None else "—"

    # ── Timestamp e label ──
    ts_raw = record.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts_raw)
        data_str = dt.strftime("%d/%m/%Y")
        hora_str = dt.strftime("%H:%M:%S")
    except Exception:
        data_str = hora_str = ts_raw

    rec_id    = record.get("id", "")[:8]
    label_str = record.get("label", "") or ""
    antes     = record.get("antes", {})
    depois    = record.get("depois", {})
    impactos  = record.get("impactos", {})
    operacoes = record.get("operacoes", [])
    basket    = record.get("basket", {})
    compliance = record.get("compliance", [])
    rows_antes  = {r["ticker"]: r for r in record.get("rows_antes", [])}
    rows_depois = record.get("rows_depois", [])

    story = []

    # ── Cabeçalho ──
    story.append(Paragraph("HARBOUR IAT FIF AÇÕES RL — RELATÓRIO PRÉ-TRADE", st_title))
    story.append(Paragraph(
        f"Data: {data_str}  |  Hora: {hora_str}  |  ID: {rec_id}" +
        (f"  |  Ref: {label_str}" if label_str else ""),
        st_sub
    ))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LINE, spaceAfter=6))

    # ── Basket de Operações ──
    # ── Seção 0: Parâmetros de Compliance Utilizados ──
    params = record.get("parametros_compliance", {})
    if params:
        story.append(Paragraph("0. PARÂMETROS DE COMPLIANCE UTILIZADOS", st_sec))
        param_rows = [["REGRA", "STATUS", "VALOR"]]
        param_rows.append([
            "Grupo I Mín. (CVM 175)",
            "SEMPRE ATIVO",
            f"mín {fmt(params.get('grupo1_minimo_pct', 67.0))}%",
        ])
        param_rows.append([
            "Conc. por Ativo (interno)",
            "ATIVO" if params.get("enable_concentracao_ativo") else "INATIVO",
            f"máx {fmt(params.get('limite_concentracao_ativo_pct', 20.0))}%",
        ])
        param_rows.append([
            "Conc. por Setor (interno)",
            "ATIVO" if params.get("enable_concentracao_setor") else "INATIVO",
            f"máx {fmt(params.get('limite_concentracao_setor_pct', 40.0))}%",
        ])
        param_extra = [
            ("TEXTCOLOR", (1, 1), (1, 1), C_OK),    # Grupo I sempre ativo → verde
        ]
        for i, row in enumerate(param_rows[1:], start=1):
            status = row[1]
            if status == "ATIVO":
                param_extra.append(("TEXTCOLOR", (1, i), (1, i), C_OK))
            elif status == "INATIVO":
                param_extra.append(("TEXTCOLOR", (1, i), (1, i), C_MUTED))
        param_tbl = Table(param_rows, colWidths=[6*cm, 3.5*cm, 3.5*cm])
        param_tbl.setStyle(tbl_style(extra=param_extra))
        story.append(param_tbl)
        story.append(Spacer(1, 6))

    story.append(Paragraph("1. BASKET DE OPERAÇÕES", st_sec))
    dir_label = {"compra": "COMPRA", "venda": "VENDA", "zerar": "ZERAR"}
    op_data = [["ATIVO", "DIREÇÃO", "QTDE", "PREÇO", "VALOR TOTAL", "CORRETAGEM"]]
    for op in operacoes:
        op_data.append([
            op.get("ticker", ""),
            dir_label.get(op.get("direcao", ""), op.get("direcao", "")),
            fmt(op.get("quantidade", 0), 0),
            fmtR(op.get("preco")),
            fmtR(op.get("valor_total_rs")),
            fmtR(op.get("corretagem_rs", 0)),
        ])
    # Linha total
    op_data.append([
        f"CUSTO LÍQUIDO TOTAL: {fmtR(basket.get('custo_total_rs'))}",
        "", "", "", "", "",
    ])

    # Cores por direção nas linhas de operações
    op_extra = []
    for i, op in enumerate(operacoes, start=1):
        c = dir_color(op.get("direcao", ""))
        op_extra.append(("TEXTCOLOR", (1, i), (1, i), c))
    op_extra.append(("SPAN",       (0, len(operacoes) + 1), (-1, len(operacoes) + 1)))
    op_extra.append(("TEXTCOLOR",  (0, len(operacoes) + 1), (-1, len(operacoes) + 1), C_ALERTA))
    op_extra.append(("FONTNAME",   (0, len(operacoes) + 1), (-1, len(operacoes) + 1), "Helvetica-Bold"))
    op_extra.append(("BACKGROUND", (0, len(operacoes) + 1), (-1, len(operacoes) + 1), C_HDR))

    op_tbl = Table(op_data, colWidths=[3.5*cm, 1.8*cm, 1.8*cm, 2.2*cm, 2.8*cm, 2.8*cm])
    op_tbl.setStyle(tbl_style(extra=op_extra))
    story.append(op_tbl)
    story.append(Spacer(1, 6))

    # ── Impacto no Fundo ──
    story.append(Paragraph("2. IMPACTO NO FUNDO", st_sec))
    metrics = [
        ("Cota Estimada",     fmt(antes.get("cota_estimada"), 8), fmt(depois.get("cota_estimada"), 8), f"{fmt(impactos.get('variacao_cota_pct'), 4)}%"),
        ("NAV Total",         fmtR(antes.get("nav_total")),        fmtR(depois.get("nav_total")),        fmtR(impactos.get("variacao_nav_rs"))),
        ("Caixa Resultante",  fmtR(antes.get("caixa")),            fmtR(depois.get("caixa")),            fmtR((depois.get("caixa") or 0) - (antes.get("caixa") or 0))),
        ("Grupo I (Ações/BDRs)", f"{fmt(antes.get('pct_grupo1'))}%", f"{fmt(depois.get('pct_grupo1'))}%", f"{fmt((depois.get('pct_grupo1') or 0) - (antes.get('pct_grupo1') or 0))} pp"),
        ("Beta Pond.",        fmt(antes.get("weighted_beta"), 4),  fmt(depois.get("weighted_beta"), 4),  fmt(impactos.get("variacao_beta"), 4)),
        ("Upside Pond.",      f"{fmt(antes.get('weighted_upside'))}%", f"{fmt(depois.get('weighted_upside'))}%", f"{fmt(impactos.get('variacao_upside_pp'))} pp"),
        ("HHI Concentração",  str(antes.get("hhi", "—")),          str(depois.get("hhi", "—")),          str(impactos.get("variacao_hhi", "—"))),
    ]
    imp_data = [["MÉTRICA", "ANTES", "DEPOIS", "Δ"]] + [list(m) for m in metrics]

    # Cor vermelha para caixa negativo
    imp_extra = []
    for i, m in enumerate(metrics, start=1):
        nome = m[0]
        if nome == "Caixa Resultante":
            try:
                val = float(str(depois.get("caixa") or 0))
                if val < 0:
                    imp_extra.append(("TEXTCOLOR", (2, i), (2, i), C_VIOL))
            except Exception:
                pass
        if nome == "Grupo I (Ações/BDRs)":
            try:
                val = float(str(depois.get("pct_grupo1") or 0))
                if val < 67:
                    imp_extra.append(("TEXTCOLOR", (2, i), (2, i), C_VIOL))
            except Exception:
                pass

    imp_tbl = Table(imp_data, colWidths=[4.2*cm, 3.8*cm, 3.8*cm, 2.9*cm])
    imp_tbl.setStyle(tbl_style(extra=imp_extra))
    story.append(imp_tbl)
    story.append(Spacer(1, 6))

    # ── Checklist de Compliance ──
    story.append(Paragraph("3. CHECKLIST DE COMPLIANCE — RESOLUÇÃO CVM 175", st_sec))
    comp_data = [["REGRA", "LIMITE", "ANTES", "DEPOIS", "STATUS"]]
    comp_extra = []
    for i, c in enumerate(compliance, start=1):
        s = c.get("status", "ok")
        sc = status_color(s)
        sl = "OK" if s == "ok" else "ALERTA" if s == "alerta" else "VIOLAÇÃO"
        tipo = c.get("tipo", "")
        lim_str = f"mín {fmt(c.get('limite_pct'))}%" if tipo == "minimo" else \
                  f"máx {fmt(c.get('limite_pct'))}%" if tipo != "caixa" else "—"
        if tipo == "caixa":
            antes_str  = fmtR(c.get("valor_antes_pct"))
            depois_str = fmtR(c.get("valor_depois_pct"))
        else:
            antes_str  = f"{fmt(c.get('valor_antes_pct'))}%"
            depois_str = f"{fmt(c.get('valor_depois_pct'))}%"
        comp_data.append([c.get("regra", ""), lim_str, antes_str, depois_str, sl])
        comp_extra.append(("TEXTCOLOR", (4, i), (4, i), sc))
        comp_extra.append(("FONTNAME",  (4, i), (4, i), "Helvetica-Bold"))
        if s != "ok":
            comp_extra.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#1a0a0a")))

    comp_tbl = Table(comp_data, colWidths=[5.5*cm, 2.2*cm, 2.5*cm, 2.5*cm, 2*cm])
    comp_tbl.setStyle(tbl_style(extra=comp_extra))
    story.append(comp_tbl)
    story.append(Spacer(1, 6))

    # ── Carteira Antes vs Depois ──
    story.append(Paragraph("4. CARTEIRA — ANTES vs DEPOIS", st_sec))
    cart_data = [["ATIVO", "ANTES %", "DEPOIS %", "Δ pp"]]
    tickers_ops = {op.get("ticker") for op in operacoes}
    for r in rows_depois:
        tk  = r.get("ticker", "")
        ra  = rows_antes.get(tk, {"pct_total": 0})
        d_pp = (r.get("pct_total") or 0) - (ra.get("pct_total") or 0)
        cart_data.append([tk, f"{fmt(ra.get('pct_total'))}%", f"{fmt(r.get('pct_total'))}%", f"{'+' if d_pp > 0 else ''}{fmt(d_pp)}"])
    # Ativos zerados
    for tk, ra in rows_antes.items():
        if not any(r.get("ticker") == tk for r in rows_depois):
            cart_data.append([f"{tk} [ZERADO]", f"{fmt(ra.get('pct_total'))}%", "0,00%", f"-{fmt(ra.get('pct_total'))}"])

    cart_extra = []
    for i, row in enumerate(cart_data[1:], start=1):
        tk = row[0].split(" ")[0]
        if tk in tickers_ops:
            cart_extra.append(("TEXTCOLOR", (0, i), (0, i), C_ALERTA))
        if "[ZERADO]" in row[0]:
            cart_extra.append(("TEXTCOLOR", (0, i), (-1, i), C_VIOL))

    cart_tbl = Table(cart_data, colWidths=[4*cm, 3*cm, 3*cm, 3*cm])
    cart_tbl.setStyle(tbl_style(extra=cart_extra))
    story.append(cart_tbl)

    # ── Rodapé de auditoria ──
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LINE, spaceAfter=4))
    story.append(Paragraph(
        f"Este relatório foi gerado automaticamente para fins de auditoria e compliance conforme "
        f"Resolução CVM 175. ID: {record.get('id', '')} | Gerado em: {data_str} {hora_str}",
        st_foot
    ))

    doc.build(story)
    return buf.getvalue()


@app.route("/api/pretrade/history", methods=["GET"])
@require_admin
def api_pretrade_history_list():
    history = load_pretrade_history()
    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(history)


@app.route("/api/pretrade/history/save", methods=["POST"])
@require_admin
def api_pretrade_history_save():
    import uuid
    payload = request.json or {}
    required = ["antes", "depois", "operacoes", "compliance"]
    for k in required:
        if k not in payload:
            return jsonify({"error": f"Campo obrigatório ausente: {k}"}), 400

    record = {
        "id":        str(uuid.uuid4()),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label":     (payload.get("label") or "").strip()[:120],
        "operacoes": payload.get("operacoes", []),
        "basket":    payload.get("basket", {}),
        "antes":     payload.get("antes", {}),
        "depois":    payload.get("depois", {}),
        "impactos":  payload.get("impactos", {}),
        "compliance": payload.get("compliance", []),
        "rows_antes": payload.get("rows_antes", []),
        "rows_depois": payload.get("rows_depois", []),
        "parametros_compliance": payload.get("parametros_compliance", {}),
    }

    history = load_pretrade_history()
    history.append(record)
    save_pretrade_history(history)

    return jsonify({"id": record["id"], "timestamp": record["timestamp"]}), 201


@app.route("/api/pretrade/history/<record_id>", methods=["DELETE"])
@require_admin
def api_pretrade_history_delete(record_id):
    history = load_pretrade_history()
    new_history = [r for r in history if r.get("id") != record_id]
    if len(new_history) == len(history):
        return jsonify({"error": "Registro não encontrado"}), 404
    save_pretrade_history(new_history)
    return jsonify({"ok": True})


@app.route("/api/pretrade/history/<record_id>/pdf", methods=["GET"])
@require_admin
def api_pretrade_history_pdf(record_id):
    history = load_pretrade_history()
    record  = next((r for r in history if r.get("id") == record_id), None)
    if not record:
        return jsonify({"error": "Registro não encontrado"}), 404

    try:
        pdf_bytes = _generate_pretrade_pdf(record)
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar PDF: {str(e)}"}), 500

    ts = record.get("timestamp", "")[:10].replace("-", "")
    filename = f"pretrade_{ts}_{record_id[:8]}.pdf"

    from flask import make_response
    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"]        = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# ---------------------------------------------------------------------------
# Portfolio History
# ---------------------------------------------------------------------------

@app.route("/api/portfolio-history", methods=["GET"])
@require_admin
def api_portfolio_history_list():
    history = load_portfolio_history()
    result  = [{k: v for k, v in r.items() if k != "rows"} for r in history]
    result.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(result)

@app.route("/api/portfolio-history/save", methods=["POST"])
@require_admin
def api_portfolio_history_save():
    portfolio   = load_portfolio()
    tickers     = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices      = fetch_prices(tickers)
    funds       = get_cached_fundamentals(tickers)
    data        = build_portfolio_response(portfolio, prices, funds)
    fund_config = get_effective_fund_config()
    quota       = calculate_quota(data["rows"], fund_config, prices)
    if not quota.get("cota_estimada"):
        return jsonify({"error": "Cota estimada indisponível — preços não carregados"}), 500
    snap = _build_portfolio_snapshot(data, quota, source="manual")
    ph   = load_portfolio_history()
    ph.append(snap)
    ph.sort(key=lambda x: x["timestamp"])
    save_portfolio_history(ph)
    return jsonify({"id": snap["id"], "timestamp": snap["timestamp"]}), 201

@app.route("/api/portfolio-history/<record_id>", methods=["GET"])
@require_admin
def api_portfolio_history_detail(record_id):
    history = load_portfolio_history()
    record  = next((r for r in history if r.get("id") == record_id), None)
    if not record:
        return jsonify({"error": "Registro não encontrado"}), 404
    return jsonify(record)

@app.route("/api/portfolio-history/<record_id>", methods=["DELETE"])
@require_admin
def api_portfolio_history_delete(record_id):
    history     = load_portfolio_history()
    new_history = [r for r in history if r.get("id") != record_id]
    if len(new_history) == len(history):
        return jsonify({"error": "Registro não encontrado"}), 404
    save_portfolio_history(new_history)
    return jsonify({"ok": True})

@app.route("/api/portfolio-history/<record_id>/pdf", methods=["GET"])
@require_admin
def api_portfolio_history_pdf(record_id):
    history = load_portfolio_history()
    record  = next((r for r in history if r.get("id") == record_id), None)
    if not record:
        return jsonify({"error": "Registro não encontrado"}), 404
    try:
        pdf_bytes = _generate_portfolio_snapshot_pdf(record)
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar PDF: {str(e)}"}), 500
    ts = record.get("date", record.get("timestamp", ""))[:10].replace("-", "")
    filename = f"carteira_{ts}_{record_id[:8]}.pdf"
    from flask import make_response
    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"]        = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _generate_portfolio_snapshot_pdf(record):
    """Gera PDF de auditoria de um snapshot da carteira. Retorna bytes."""
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

    buf = BytesIO()
    PAGE = landscape(A4)
    doc = SimpleDocTemplate(
        buf, pagesize=PAGE,
        leftMargin=1.4*cm, rightMargin=1.4*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm,
    )

    C_BG      = colors.HexColor("#0d0d1a")
    C_ALT     = colors.HexColor("#0f0f22")
    C_HDR     = colors.HexColor("#1a1a2e")
    C_HDR_TXT = colors.white
    C_OK      = colors.HexColor("#00cc88")
    C_NEG     = colors.HexColor("#cc3333")
    C_WARN    = colors.HexColor("#f5a623")
    C_BODY    = colors.HexColor("#cccccc")
    C_MUTED   = colors.HexColor("#888888")
    C_LINE    = colors.HexColor("#333333")
    C_MANUAL  = colors.HexColor("#00aacc")

    mono = "Courier"

    st_title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=13,
                               textColor=C_HDR_TXT, spaceAfter=3)
    st_sub   = ParagraphStyle("sub",   fontName="Helvetica",      fontSize=8,
                               textColor=C_MUTED,   spaceAfter=2)
    st_sec   = ParagraphStyle("sec",   fontName="Helvetica-Bold", fontSize=9,
                               textColor=C_HDR_TXT, spaceBefore=8, spaceAfter=3)
    st_foot  = ParagraphStyle("foot",  fontName="Helvetica",      fontSize=7,
                               textColor=C_MUTED,   alignment=1, spaceBefore=4)

    def tbl_style(extra=None):
        base = [
            ("BACKGROUND",    (0, 0), (-1, 0), C_HDR),
            ("TEXTCOLOR",     (0, 0), (-1, 0), C_HDR_TXT),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 7),
            ("FONTNAME",      (0, 1), (-1, -1), mono),
            ("TEXTCOLOR",     (0, 1), (-1, -1), C_BODY),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_BG, C_ALT]),
            ("GRID",          (0, 0), (-1, -1), 0.25, C_LINE),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            ("ALIGN",         (0, 0), (-1, -1), "RIGHT"),
            ("ALIGN",         (0, 0), (0, -1),  "LEFT"),
        ]
        if extra:
            base.extend(extra)
        return TableStyle(base)

    def fmt(v, dec=2):
        try:
            return f"{float(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(v) if v is not None else "—"

    def fmtpct(v):
        return fmt(v) + "%" if v is not None else "—"

    def fmtmm(v):
        return "R$" + fmt(v/1e6, 1) + "MM" if v is not None else "—"

    # ── Metadados ──
    ts_raw = record.get("timestamp", "")
    try:
        dt       = datetime.fromisoformat(ts_raw)
        data_str = dt.strftime("%d/%m/%Y")
        hora_str = dt.strftime("%H:%M:%S")
    except Exception:
        data_str = hora_str = ts_raw

    rec_id  = record.get("id", "")[:8]
    source  = record.get("source", "auto")
    s       = record.get("summary", {})
    rows    = record.get("rows", [])

    story = []

    # ── Cabeçalho ──
    src_label = "MANUAL" if source == "manual" else "AUTO (FECHAMENTO)"
    story.append(Paragraph("HARBOUR IAT FIF AÇÕES RL — SNAPSHOT DA CARTEIRA", st_title))
    story.append(Paragraph(
        f"Data: {data_str}  |  Hora: {hora_str}  |  ID: {rec_id}  |  Origem: {src_label}",
        st_sub
    ))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LINE, spaceAfter=5))

    # ── Bloco de resumo (uma linha de métricas) ──
    nav_val  = s.get("total_value")
    cota_val = s.get("cota_estimada")
    var_val  = s.get("variacao_pct")
    n_pos    = s.get("num_positions", len(rows))

    sum_data = [[
        "NAV TOTAL", "COTA ESTIMADA", "VAR. DIA", "POSIÇÕES",
        "UPSIDE POND.", "BETA POND.", "P/L FWD POND.", "ROE POND.",
    ], [
        fmtmm(nav_val),
        fmt(cota_val, 8) if cota_val else "—",
        fmtpct(var_val),
        str(n_pos),
        fmtpct(s.get("w_upside_pct")),
        fmt(s.get("w_beta"), 2) if s.get("w_beta") is not None else "—",
        fmt(s.get("w_forward_pe"), 1) if s.get("w_forward_pe") is not None else "—",
        fmtpct(s.get("w_return_on_equity")),
    ]]

    sum_extra = [("ALIGN", (0, 1), (-1, 1), "CENTER")]
    if var_val is not None:
        c = C_OK if float(var_val) >= 0 else C_NEG
        sum_extra.append(("TEXTCOLOR", (2, 1), (2, 1), c))

    W = PAGE[0] - 2.8*cm
    sum_tbl = Table(sum_data, colWidths=[W/8]*8)
    sum_tbl.setStyle(tbl_style(extra=sum_extra))
    story.append(sum_tbl)
    story.append(Spacer(1, 6))

    # ── Tabela 1: Composição & Preços ──
    story.append(Paragraph("1. COMPOSIÇÃO E PREÇOS", st_sec))
    t1_hdr = ["ATIVO", "CATEG.", "SETOR", "% TOTAL", "VALOR LÍQ.", "PREÇO", "VAR. DIA", "QTDE", "P. ALVO", "UPSIDE"]
    t1_rows = [t1_hdr]
    for r in sorted(rows, key=lambda x: (x.get("pct_total") or 0), reverse=True):
        vd = r.get("var_dia_pct")
        up = r.get("upside_pct")
        t1_rows.append([
            r.get("ticker", ""),
            r.get("categoria", ""),
            (r.get("sector") or "")[:18],
            fmtpct(r.get("pct_total")),
            fmtmm(r.get("valor_liquido")),
            fmt(r.get("preco"), 2) if r.get("preco") is not None else "—",
            fmtpct(vd),
            fmt(r.get("quantidade"), 0) if r.get("quantidade") is not None else "—",
            fmt(r.get("preco_alvo"), 2) if r.get("preco_alvo") is not None else "—",
            fmtpct(up),
        ])

    # Linha de totais
    total_nav = s.get("total_value")
    t1_rows.append([
        "TOTAL", "", "", "100,00%",
        fmtmm(total_nav), "", "", "", "", fmtpct(s.get("w_upside_pct")),
    ])

    t1_extra = []
    for i, r in enumerate(rows, start=1):
        vd = r.get("var_dia_pct")
        up = r.get("upside_pct")
        if vd is not None:
            t1_extra.append(("TEXTCOLOR", (6, i), (6, i), C_OK if float(vd) >= 0 else C_NEG))
        if up is not None:
            t1_extra.append(("TEXTCOLOR", (9, i), (9, i), C_OK if float(up) >= 0 else C_NEG))
    # Total row
    ti = len(rows) + 1
    t1_extra += [
        ("BACKGROUND", (0, ti), (-1, ti), C_HDR),
        ("TEXTCOLOR",  (0, ti), (-1, ti), C_WARN),
        ("FONTNAME",   (0, ti), (-1, ti), "Helvetica-Bold"),
    ]

    cw1 = [2.0*cm, 1.6*cm, 3.2*cm, 1.5*cm, 2.2*cm, 1.6*cm, 1.6*cm, 2.0*cm, 1.6*cm, 1.6*cm]
    t1_tbl = Table(t1_rows, colWidths=cw1)
    t1_tbl.setStyle(tbl_style(extra=t1_extra))
    story.append(t1_tbl)
    story.append(Spacer(1, 6))

    # ── Tabela 2: Valuation & Fundamentos ──
    story.append(Paragraph("2. VALUATION E FUNDAMENTOS", st_sec))
    t2_hdr = ["ATIVO", "P/L TRAIL.", "P/L FWD.", "PEG", "EV/EBITDA", "ROE %", "BETA", "P/VPA", "DIV. YIELD", "MKT CAP", "LUCRO MI 26"]
    t2_rows = [t2_hdr]
    for r in sorted(rows, key=lambda x: (x.get("pct_total") or 0), reverse=True):
        t2_rows.append([
            r.get("ticker", ""),
            fmt(r.get("trailing_pe"), 1)    if r.get("trailing_pe")    is not None else "—",
            fmt(r.get("forward_pe"), 1)     if r.get("forward_pe")     is not None else "—",
            fmt(r.get("peg_ratio"), 2)      if r.get("peg_ratio")      is not None else "—",
            fmt(r.get("enterprise_to_ebitda"), 1) if r.get("enterprise_to_ebitda") is not None else "—",
            fmtpct(r.get("return_on_equity")),
            fmt(r.get("beta"), 2)           if r.get("beta")           is not None else "—",
            fmt(r.get("price_to_book"), 2)  if r.get("price_to_book")  is not None else "—",
            fmtpct(r.get("dividend_yield")),
            fmt(r.get("market_cap_bi"), 1) + "bi" if r.get("market_cap_bi") is not None else "—",
            fmt(r.get("lucro_mi_26"), 0)    if r.get("lucro_mi_26")    is not None else "—",
        ])

    # Linha de médias ponderadas
    t2_rows.append([
        "POND.",
        fmt(s.get("w_trailing_pe"), 1)          if s.get("w_trailing_pe")          is not None else "—",
        fmt(s.get("w_forward_pe"), 1)            if s.get("w_forward_pe")           is not None else "—",
        fmt(s.get("w_peg_ratio"), 2)             if s.get("w_peg_ratio")            is not None else "—",
        fmt(s.get("w_enterprise_to_ebitda"), 1)  if s.get("w_enterprise_to_ebitda") is not None else "—",
        fmtpct(s.get("w_return_on_equity")),
        fmt(s.get("w_beta"), 2)                  if s.get("w_beta")                 is not None else "—",
        fmt(s.get("w_price_to_book"), 2)         if s.get("w_price_to_book")        is not None else "—",
        fmtpct(s.get("w_dividend_yield")),
        "—",
        fmt(s.get("w_lucro_mi_26"), 0)           if s.get("w_lucro_mi_26")          is not None else "—",
    ])

    ti2 = len(rows) + 1
    t2_extra = [
        ("BACKGROUND", (0, ti2), (-1, ti2), C_HDR),
        ("TEXTCOLOR",  (0, ti2), (-1, ti2), C_WARN),
        ("FONTNAME",   (0, ti2), (-1, ti2), "Helvetica-Bold"),
    ]

    cw2 = [2.0*cm, 1.8*cm, 1.8*cm, 1.5*cm, 2.2*cm, 1.8*cm, 1.5*cm, 1.5*cm, 2.0*cm, 2.0*cm, 2.2*cm]
    t2_tbl = Table(t2_rows, colWidths=cw2)
    t2_tbl.setStyle(tbl_style(extra=t2_extra))
    story.append(t2_tbl)

    # ── Rodapé ──
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LINE, spaceAfter=3))
    story.append(Paragraph(
        f"Relatório gerado automaticamente para fins de auditoria interna. "
        f"ID: {record.get('id', '')}  |  Gerado em: {data_str} {hora_str}  |  Origem: {src_label}",
        st_foot
    ))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Index Members (Bloomberg-style Leaders / Laggards)
# ---------------------------------------------------------------------------

INDEX_TICKER_MAP = {
    "IBOV":    "^BVSP",
    "IBRX100": "BRAX11.SA",
    "SMLL":    "SMAL11.SA",
}
INDEX_MEMBERS_TTL = 3600  # 1 hour cache

@app.route("/api/index-members")
def api_index_members():
    """GET /api/index-members?index=IBOV&start=2026-01-01&end=2026-04-02"""
    import pandas as pd

    index_name = request.args.get("index", "IBOV").upper()
    start_str  = request.args.get("start", "")
    end_str    = request.args.get("end", "")

    if index_name not in INDEX_TICKER_MAP:
        return jsonify({"error": f"Índice inválido: {index_name}"}), 400

    if not os.path.exists(INDEX_MEMBERS_FILE):
        return jsonify({"error": "index_members.json não encontrado"}), 404

    with open(INDEX_MEMBERS_FILE, "r", encoding="utf-8") as f:
        all_members = json.load(f)

    members = all_members.get(index_name, [])
    if not members:
        return jsonify({"error": f"Índice {index_name} sem constituintes"}), 404

    # Parse dates
    try:
        dt_start = datetime.strptime(start_str, "%Y-%m-%d") if start_str else datetime(datetime.now().year, 1, 1)
        dt_end   = datetime.strptime(end_str,   "%Y-%m-%d") if end_str   else datetime.now()
    except ValueError:
        return jsonify({"error": "Formato de data inválido (use AAAA-MM-DD)"}), 400

    # Cache lookup
    cache_key = f"idx_members_{index_name}_{dt_start.date()}_{dt_end.date()}"
    cache = load_cache()
    now   = time.time()
    if cache.get(cache_key) and now < cache[cache_key].get("expires_at", 0):
        return jsonify(cache[cache_key]["data"])

    # Normalise weights to sum to 100
    total_w = sum(m.get("weight_pct", 0) for m in members)
    if total_w > 0:
        for m in members:
            m["weight_pct"] = round(m.get("weight_pct", 0) / total_w * 100, 4)

    # Build tickers list (members + index level)
    index_ticker = INDEX_TICKER_MAP[index_name]
    member_tickers = [m["ticker"] for m in members]
    all_tickers = member_tickers + [index_ticker]

    # Portfolio tickers for cross-reference
    try:
        portfolio = load_portfolio()
        portfolio_tickers = set(
            p.get("yahoo_ticker") or p.get("ticker", "")
            for p in portfolio.get("positions", [])
        )
    except Exception:
        portfolio_tickers = set()

    # Fetch price history in bulk
    try:
        df = yf.download(
            all_tickers,
            start=dt_start,
            end=dt_end + timedelta(days=1),
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao buscar dados: {str(e)}"}), 500

    # Extract Close prices
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"] if "Close" in df.columns.get_level_values(0) else df.iloc[:, :]
    else:
        close = df

    def get_series(ticker):
        if ticker in close.columns:
            return close[ticker].dropna()
        return pd.Series(dtype=float)

    # Index level start/end
    idx_series = get_series(index_ticker)
    idx_start_val = float(idx_series.iloc[0])  if len(idx_series) >= 2 else None
    idx_end_val   = float(idx_series.iloc[-1]) if len(idx_series) >= 2 else None
    idx_change    = (idx_end_val - idx_start_val) if idx_start_val and idx_end_val else None
    idx_return_pct = ((idx_end_val / idx_start_val) - 1) * 100 if idx_start_val and idx_end_val else None

    results = []
    for m in members:
        ticker = m["ticker"]
        name   = m["name"]
        weight = m["weight_pct"]

        series = get_series(ticker)
        if len(series) < 2:
            continue

        start_price = float(series.iloc[0])
        end_price   = float(series.iloc[-1])
        if start_price == 0:
            continue
        change_pct = (end_price / start_price - 1) * 100

        # Points contributed to index (in index units)
        if idx_start_val and idx_start_val > 0:
            points = (change_pct / 100) * (weight / 100) * idx_start_val
        else:
            points = 0.0

        # % of total index move from this stock
        if idx_return_pct and idx_return_pct != 0:
            idx_mv_pct = ((change_pct / 100) * (weight / 100)) / (idx_return_pct / 100) * 100
        else:
            idx_mv_pct = 0.0

        results.append({
            "ticker":      ticker,
            "name":        name,
            "weight_pct":  round(weight, 2),
            "end_price":   round(end_price, 2),
            "change_pct":  round(change_pct, 2),
            "points":      round(points, 3),
            "idx_mv_pct":  round(idx_mv_pct, 2),
            "in_portfolio": ticker in portfolio_tickers,
        })

    results.sort(key=lambda x: x["change_pct"], reverse=True)
    max_rows = 35
    leaders  = results[:max_rows]
    laggards = sorted(results, key=lambda x: x["change_pct"])[:max_rows]

    data = {
        "index":        index_name,
        "start":        dt_start.strftime("%Y-%m-%d"),
        "end":          dt_end.strftime("%Y-%m-%d"),
        "idx_start":    round(idx_start_val, 2)  if idx_start_val  else None,
        "idx_end":      round(idx_end_val, 2)    if idx_end_val    else None,
        "idx_change":   round(idx_change, 2)     if idx_change     else None,
        "idx_return_pct": round(idx_return_pct, 2) if idx_return_pct else None,
        "n_total":      len(results),
        "n_up":         sum(1 for r in results if r["change_pct"] > 0),
        "n_down":       sum(1 for r in results if r["change_pct"] < 0),
        "n_unch":       sum(1 for r in results if r["change_pct"] == 0),
        "leaders":      leaders,
        "laggards":     laggards,
    }

    cache[cache_key] = {"data": data, "expires_at": now + INDEX_MEMBERS_TTL}
    save_cache(cache)
    return jsonify(data)


# =============================================================================
# RESEARCH (212) — routes
# =============================================================================

import research_db as _rdb
import research_claude as _claude

# Initialise DB and sync from portfolio/watchlist on startup
_rdb.init_db()
_rdb.sync_from_portfolio(PORTFOLIO_FILE, WATCHLIST_FILE, user="system")
_rdb.ensure_portfolio_thesis_seed(user="system")

def _research_user():
    return session.get("role", "viewer")

def _require_team(f):
    """Allow admin and equipe (any logged-in non-viewer) to write."""
    @wraps(f)
    def decorated(*args, **kwargs):
        role = session.get("role")
        if role not in ("admin", "equipe"):
            return jsonify({"error": "forbidden"}), 403
        return f(*args, **kwargs)
    return decorated


# ── Companies ──────────────────────────────────────────────────────────────

@app.route("/api/research/companies", methods=["GET"])
def api_research_companies():
    companies = _rdb.get_companies()
    pending   = _rdb.get_pending_by_ticker()
    thesis_st = _rdb.get_thesis_status_by_ticker()
    for c in companies:
        c["pending"] = pending.get(c["ticker"], 0)
        ts = thesis_st.get(c["ticker"], {})
        c["has_active_thesis"] = ts.get("has_active", False)
        c["has_pending_draft"] = ts.get("has_draft", False)
    return jsonify({"companies": companies})


@app.route("/api/research/companies", methods=["POST"])
@_require_team
def api_research_companies_create():
    payload = request.json or {}
    ticker  = (payload.get("ticker") or "").upper().strip()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    _rdb.upsert_company(
        ticker,
        name=payload.get("name"),
        market=payload.get("market", "BR"),
        status=payload.get("status", "UNIVERSO"),
        sector=payload.get("sector"),
        user=_research_user(),
    )
    return jsonify({"ok": True})


@app.route("/api/research/companies/<ticker>", methods=["DELETE"])
@require_admin
def api_research_companies_delete(ticker):
    ok = _rdb.delete_company(ticker.upper(), user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/research/sync", methods=["POST"])
@require_admin
def api_research_sync():
    """Re-sync companies from portfolio.json and watchlist.json."""
    _rdb.sync_from_portfolio(PORTFOLIO_FILE, WATCHLIST_FILE, user=_research_user())
    return jsonify({"ok": True})


# ── Theses ─────────────────────────────────────────────────────────────────

@app.route("/api/research/theses/<ticker>", methods=["GET"])
def api_research_theses_get(ticker):
    return jsonify({"theses": _rdb.get_theses(ticker.upper())})


@app.route("/api/research/theses/<ticker>", methods=["POST"])
@_require_team
def api_research_theses_create(ticker):
    payload = request.json or {}
    content = payload.get("content", "")
    new_id  = _rdb.create_thesis(ticker.upper(), content, user=_research_user())
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/research/theses/<int:thesis_id>/approve", methods=["POST"])
@require_admin
def api_research_thesis_approve(thesis_id):
    ok = _rdb.approve_thesis(thesis_id, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/research/theses/<int:thesis_id>/dismiss", methods=["POST"])
@require_admin
def api_research_thesis_dismiss(thesis_id):
    """Archive an auto-generated draft thesis (user ignored the suggestion)."""
    with _rdb.get_conn() as conn:
        row = conn.execute("SELECT * FROM theses WHERE id=?", (thesis_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        old = dict(row)
        conn.execute("UPDATE theses SET status='ARQUIVADA' WHERE id=?", (thesis_id,))
        _rdb.audit(conn, "thesis", thesis_id, old["ticker"], "UPDATE",
                   _research_user(), old, {**old, "status": "ARQUIVADA"})
    return jsonify({"ok": True})


@app.route("/api/research/theses/<int:thesis_id>", methods=["PUT"])
@_require_team
def api_research_thesis_update(thesis_id):
    payload = request.json or {}
    content = payload.get("content", "")
    ok = _rdb.update_thesis_content(thesis_id, content, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── Notes ──────────────────────────────────────────────────────────────────

@app.route("/api/research/notes/<ticker>", methods=["GET"])
def api_research_notes_get(ticker):
    return jsonify({"notes": _rdb.get_notes(ticker.upper())})


@app.route("/api/research/notes/<ticker>", methods=["POST"])
@_require_team
def api_research_notes_create(ticker):
    payload   = request.json or {}
    content   = payload.get("content", "")
    note_type = payload.get("note_type", "OBSERVACAO")
    if not content.strip():
        return jsonify({"error": "content required"}), 400
    new_id = _rdb.create_note(ticker.upper(), content, note_type, user=_research_user())
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/research/notes/<int:note_id>", methods=["PUT"])
@_require_team
def api_research_note_update(note_id):
    payload   = request.json or {}
    content   = payload.get("content", "")
    note_type = payload.get("note_type")
    ok = _rdb.update_note(note_id, content, note_type, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/research/notes/<int:note_id>", methods=["DELETE"])
@_require_team
def api_research_note_delete(note_id):
    ok = _rdb.delete_note(note_id, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── Valuations ─────────────────────────────────────────────────────────────

@app.route("/api/research/valuations/<ticker>", methods=["GET"])
def api_research_valuations_get(ticker):
    return jsonify({"valuations": _rdb.get_valuations(ticker.upper())})


@app.route("/api/research/valuations/<ticker>", methods=["POST"])
@_require_team
def api_research_valuations_create(ticker):
    payload = request.json or {}
    try:
        target_price = float(payload["target_price"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "target_price required"}), 400
    methodology = payload.get("methodology", "DCF")
    upside_pct  = payload.get("upside_pct")
    assumptions = payload.get("assumptions")
    notes       = payload.get("notes")
    new_id = _rdb.create_valuation(
        ticker.upper(), target_price, methodology,
        upside_pct=float(upside_pct) if upside_pct is not None else None,
        assumptions=assumptions, notes=notes, user=_research_user()
    )
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/research/valuations/<int:valuation_id>", methods=["DELETE"])
@_require_team
def api_research_valuation_delete(valuation_id):
    ok = _rdb.delete_valuation(valuation_id, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── Filings ────────────────────────────────────────────────────────────────

@app.route("/api/research/filings/<ticker>", methods=["GET"])
def api_research_filings_get(ticker):
    review_status = request.args.get("status")
    return jsonify({"filings": _rdb.get_filings(ticker=ticker.upper(), review_status=review_status)})


def _trigger_thesis_suggestion(ticker, trigger_summary, trigger_type, trigger_id):
    """Background helper: gera rascunho de tese via Claude e salva como RASCUNHO auto_generated."""
    try:
        active = _rdb.get_active_thesis(ticker)
        current_content = active["content"] if active else ""
        draft = _claude.suggest_thesis_update(current_content, trigger_summary, trigger_type)
        if draft:
            _rdb.create_thesis(
                ticker, draft, user="claude",
                auto_generated=1, trigger_type=trigger_type, trigger_id=trigger_id
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("_trigger_thesis_suggestion [%s]: %s", ticker, e)


@app.route("/api/research/filings/<int:filing_id>/review", methods=["POST"])
@require_admin
def api_research_filing_review(filing_id):
    payload = request.json or {}
    action  = payload.get("action", "").upper()
    if action not in ("APPROVE", "REJECT"):
        return jsonify({"error": "action must be APPROVE or REJECT"}), 400
    ok = _rdb.review_filing(filing_id, action, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    if action == "APPROVE":
        filing = _rdb.get_filing(filing_id)
        if filing and filing.get("update_thesis") and filing.get("ticker"):
            _trigger_thesis_suggestion(
                filing["ticker"], filing.get("summary", ""), "filing", filing_id
            )
    return jsonify({"ok": True})


# ── News ───────────────────────────────────────────────────────────────────

@app.route("/api/research/news/<ticker>", methods=["GET"])
def api_research_news_get(ticker):
    review_status = request.args.get("status")
    return jsonify({"news": _rdb.get_news(ticker=ticker.upper(), review_status=review_status)})


@app.route("/api/research/news/<int:news_id>/review", methods=["POST"])
@require_admin
def api_research_news_review(news_id):
    payload = request.json or {}
    action  = payload.get("action", "").upper()
    if action not in ("APPROVE", "REJECT"):
        return jsonify({"error": "action must be APPROVE or REJECT"}), 400
    ok = _rdb.review_news(news_id, action, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    if action == "APPROVE":
        news = _rdb.get_news_item(news_id)
        if news and news.get("update_thesis") and news.get("ticker"):
            _trigger_thesis_suggestion(
                news["ticker"], news.get("summary", ""), "news", news_id
            )
    return jsonify({"ok": True})


# ── Audit log ──────────────────────────────────────────────────────────────

@app.route("/api/research/audit/<ticker>", methods=["GET"])
def api_research_audit_get(ticker):
    limit = int(request.args.get("limit", 100))
    return jsonify({"audit": _rdb.get_audit_log(ticker=ticker.upper(), limit=limit)})


# ── Pending counts ─────────────────────────────────────────────────────────

@app.route("/api/research/pending", methods=["GET"])
def api_research_pending():
    return jsonify(_rdb.get_pending_counts())


# ── Full-text search ───────────────────────────────────────────────────────

@app.route("/api/research/search", methods=["GET"])
def api_research_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    results = _rdb.fts_search(q, limit=50)
    return jsonify({"results": results})


# ── Q&A ────────────────────────────────────────────────────────────────────

@app.route("/api/research/qa", methods=["GET"])
def api_research_qa_get():
    ticker = (request.args.get("ticker") or "").strip().upper() or None
    messages = _rdb.get_qa_messages(ticker=ticker)
    return jsonify({"messages": messages})


@app.route("/api/research/qa", methods=["POST"])
def api_research_qa_post():
    data    = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    ticker   = (data.get("ticker") or "").strip().upper() or None
    if not question:
        return jsonify({"error": "question required"}), 400

    user = _research_user()
    context_chunks = _rdb.build_rag_context(question, ticker=ticker)
    _rdb.save_qa_message(ticker, "user", question, None, user)

    result = _claude.answer_question(question, ticker, context_chunks)
    if result is None:
        return jsonify({"error": "Claude API error"}), 500

    _rdb.save_qa_message(ticker, "assistant", result["answer"], result.get("sources"), "claude")
    return jsonify(result)


# ── Markdown export ────────────────────────────────────────────────────────

@app.route("/api/research/export/<ticker>", methods=["GET"])
def api_research_export(ticker):
    md = _rdb.export_company_markdown(ticker.upper())
    if md is None:
        return jsonify({"error": "company not found"}), 404
    filename = f"{ticker.upper()}_research_{datetime.now().strftime('%Y%m%d')}.md"
    return Response(md, mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ── Company full data (single request for all sub-tabs) ────────────────────

@app.route("/api/research/company/<ticker>", methods=["GET"])
def api_research_company_full(ticker):
    ticker = ticker.upper()
    company = _rdb.get_company(ticker)
    if not company:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "company":    company,
        "theses":     _rdb.get_theses(ticker),
        "notes":      _rdb.get_notes(ticker),
        "valuations": _rdb.get_valuations(ticker),
        "filings":    _rdb.get_filings(ticker=ticker),
        "news":       _rdb.get_news(ticker=ticker),
        "audit":      _rdb.get_audit_log(ticker=ticker, limit=50),
    })


# =============================================================================
# RESEARCH — Portfólio Global (tese, decisões, histórico, snapshot)
# =============================================================================

def _portfolio_snapshot(tickers=None):
    """Snapshot dos pesos/preços reais agora — usado ao salvar uma decisão.
    Se `tickers` for fornecido, inclui só esses; senão, todas as posições."""
    try:
        data = get_export_data()
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("portfolio snapshot failed: %s", e)
        return None
    rows = data.get("rows", []) or []
    wanted = set(t.upper() for t in (tickers or []))
    per_ticker = {}
    for r in rows:
        t = (r.get("ticker") or "").upper()
        if not t: continue
        if wanted and t not in wanted: continue
        per_ticker[t] = {
            "peso_pct":      r.get("pct_total"),
            "preco":         r.get("preco"),
            "valor_liquido": r.get("valor_liquido"),
            "var_dia_pct":   r.get("var_dia_pct"),
        }
    return {
        "date":        datetime.now().strftime("%Y-%m-%d"),
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
        "total_value": data.get("total_value"),
        "tickers":     per_ticker,
    }


@app.route("/api/research/portfolio/thesis", methods=["GET"])
def api_research_portfolio_thesis_get():
    """Retorna versão ATIVA + lista de versões (resumida)."""
    active   = _rdb.get_active_portfolio_thesis()
    versions = [
        {k: t[k] for k in ("id","version","status","title","created_by",
                           "created_at","published_at")}
        for t in _rdb.get_portfolio_theses()
    ]
    return jsonify({"active": active, "versions": versions})


@app.route("/api/research/portfolio/thesis/<int:version_id>", methods=["GET"])
def api_research_portfolio_thesis_get_one(version_id):
    t = _rdb.get_portfolio_thesis(version_id)
    if not t:
        return jsonify({"error": "not found"}), 404
    return jsonify(t)


@app.route("/api/research/portfolio/thesis", methods=["POST"])
@_require_team
def api_research_portfolio_thesis_create():
    """Cria nova versão (RASCUNHO). Admin pode pedir publish=true."""
    payload = request.get_json(force=True) or {}
    title   = (payload.get("title") or "").strip() or "Tese de Portfólio"
    body    = payload.get("body_md") or ""
    user    = _research_user()
    new_id  = _rdb.create_portfolio_thesis(title, body, user=user)
    if payload.get("publish") and user == "admin":
        _rdb.approve_portfolio_thesis(new_id, user=user)
    return jsonify({"ok": True, "id": new_id})


@app.route("/api/research/portfolio/thesis/<int:version_id>", methods=["PATCH"])
@_require_team
def api_research_portfolio_thesis_update(version_id):
    payload = request.get_json(force=True) or {}
    ok = _rdb.update_portfolio_thesis(
        version_id,
        title=payload.get("title"),
        body_md=payload.get("body_md"),
        user=_research_user(),
    )
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/research/portfolio/thesis/<int:version_id>/approve",
           methods=["POST"])
@require_admin
def api_research_portfolio_thesis_approve(version_id):
    ok = _rdb.approve_portfolio_thesis(version_id, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/research/portfolio/decisions", methods=["GET"])
def api_research_portfolio_decisions_list():
    args = request.args
    decisions = _rdb.list_portfolio_decisions(
        ticker=(args.get("ticker") or "").strip().upper() or None,
        tipo=(args.get("tipo") or "").strip().upper() or None,
        date_from=args.get("date_from") or None,
        date_to=args.get("date_to") or None,
        author=args.get("author") or None,
        include_archived=args.get("include_archived") in ("1","true","yes"),
        limit=int(args.get("limit") or 200),
    )
    return jsonify({"decisions": decisions})


@app.route("/api/research/portfolio/decisions", methods=["POST"])
@_require_team
def api_research_portfolio_decisions_create():
    p = request.get_json(force=True) or {}
    titulo = (p.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"error": "titulo required"}), 400
    date = p.get("date") or datetime.now().strftime("%Y-%m-%d")
    tipo = (p.get("tipo") or "DECISAO").upper()
    tickers = p.get("tickers") or []
    snapshot = _portfolio_snapshot(tickers if tickers else None)

    # Auto-preenche peso_antes do primeiro ticker se não veio explicito
    peso_antes = p.get("peso_antes")
    if peso_antes is None and tickers and snapshot:
        first = tickers[0].upper()
        peso_antes = (snapshot.get("tickers", {}).get(first) or {}).get("peso_pct")

    try:
        new_id = _rdb.create_portfolio_decision(
            date=date, tipo=tipo, titulo=titulo,
            rationale_md=p.get("rationale_md") or "",
            subtipo=p.get("subtipo"),
            tickers=tickers,
            peso_antes=peso_antes,
            peso_depois=p.get("peso_depois"),
            snapshot=snapshot,
            author=_research_user(),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "id": new_id, "snapshot": snapshot,
                    "peso_antes": peso_antes})


@app.route("/api/research/portfolio/decisions/<int:decision_id>/archive",
           methods=["POST"])
@require_admin
def api_research_portfolio_decisions_archive(decision_id):
    ok = _rdb.archive_portfolio_decision(decision_id, user=_research_user())
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/research/portfolio/history", methods=["GET"])
def api_research_portfolio_history():
    limit = int(request.args.get("limit") or 200)
    return jsonify({"events": _rdb.get_portfolio_audit_log(limit=limit)})


def _build_portfolio_qa_context(months=12, per_company_news=3, company_limit=30):
    """Monta o contexto textual do Q&A de portfólio global.

    Inclui: tese macro ativa, regras (tipo='REGRA'), decisões recentes,
    e por empresa INVESTIDA: tese ATIVA + últimas N notícias/filings aprovados.
    Retorna (context_text, sources_list).
    """
    parts   = []
    sources = []

    def _cite(ref, body):
        parts.append(f"[{ref}]\n{body.strip()}")

    # 1) Tese macro
    thesis = _rdb.get_active_portfolio_thesis()
    if thesis:
        ref = f"Tese do Portfólio v{thesis.get('version')}"
        _cite(ref, f"{thesis.get('title') or ''}\n{thesis.get('body_md') or ''}")
        sources.append({"type": "portfolio_thesis", "id": thesis["id"],
                        "ticker": None,
                        "snippet": (thesis.get("title") or "Tese do Portfólio")[:200]})

    # 2) Regras ativas
    for r in _rdb.list_portfolio_rules(limit=30):
        ref = f"Regra #{r['id']}"
        body = f"{r.get('titulo','')}\n{r.get('rationale_md','') or ''}"
        _cite(ref, body)
        sources.append({"type": "portfolio_rule", "id": r["id"], "ticker": None,
                        "snippet": (r.get("titulo") or "")[:200]})

    # 3) Decisões recentes
    for d in _rdb.list_recent_portfolio_decisions(months=months, limit=40):
        tickers_str = ""
        try:
            tks = json.loads(d.get("tickers_json") or "[]")
            if tks: tickers_str = " " + ",".join(tks)
        except Exception:
            pass
        subtipo = f" {d.get('subtipo')}" if d.get("subtipo") else ""
        ref = f"Decisão #{d['id']}: {d.get('tipo','')}{subtipo}{tickers_str}"
        pa = d.get("peso_antes"); pd = d.get("peso_depois")
        peso_line = ""
        if pa is not None or pd is not None:
            peso_line = f"\nPeso: {pa if pa is not None else '?'}% → {pd if pd is not None else '?'}%"
        body = (f"Data: {d.get('date','')}\n"
                f"{d.get('titulo','')}{peso_line}\n"
                f"{d.get('rationale_md','') or ''}")
        _cite(ref, body)
        sources.append({"type": "portfolio_decision", "id": d["id"], "ticker": None,
                        "snippet": (d.get("titulo") or "")[:200]})

    # 4) Empresas investidas — tese ativa + últimas inteligências
    investidas = [c for c in _rdb.get_companies() if (c.get("status") or "").upper() == "INVESTIDO"]
    investidas = investidas[:company_limit]
    for c in investidas:
        tkr = c["ticker"]
        t = _rdb.get_active_thesis(tkr)
        if t and (t.get("content") or "").strip():
            ref = f"Tese {tkr} v{t.get('version')}"
            _cite(ref, t["content"])
            sources.append({"type": "thesis", "id": t["id"], "ticker": tkr,
                            "snippet": (t.get("content") or "")[:200]})
        # últimas notícias aprovadas
        for n in _rdb.get_news(ticker=tkr, review_status="APROVADO")[:per_company_news]:
            ref = f"Notícia {tkr} #{n['id']}"
            body = f"{n.get('title','')} — {n.get('summary') or ''}"
            _cite(ref, body)
            sources.append({"type": "news", "id": n["id"], "ticker": tkr,
                            "snippet": (n.get("title") or "")[:200]})
        # últimos filings aprovados
        for f in _rdb.get_filings(ticker=tkr, review_status="APROVADO")[:2]:
            ref = f"Filing {tkr} #{f['id']}"
            body = f"{f.get('title','')} — {f.get('summary') or ''}"
            _cite(ref, body)
            sources.append({"type": "filing", "id": f["id"], "ticker": tkr,
                            "snippet": (f.get("title") or "")[:200]})

    context_text = "\n\n---\n\n".join(parts) if parts \
        else "Nenhuma informação disponível na base do portfólio."
    return context_text, sources


@app.route("/api/research/portfolio/qa", methods=["GET"])
def api_research_portfolio_qa_get():
    messages = _rdb.get_portfolio_qa_messages(limit=100)
    return jsonify({"messages": messages})


@app.route("/api/research/portfolio/qa", methods=["POST"])
def api_research_portfolio_qa_post():
    data     = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question required"}), 400

    months = int(data.get("months") or 12)
    context_text, sources = _build_portfolio_qa_context(months=months)

    user = _research_user()
    _rdb.save_portfolio_qa_message("user", question, None, user)

    result = _claude.answer_portfolio_question(question, context_text, sources=sources)
    if result is None:
        return jsonify({"error": "Claude API error"}), 500

    _rdb.save_portfolio_qa_message("assistant", result["answer"],
                                   result.get("sources"), "claude")
    return jsonify(result)


@app.route("/api/research/portfolio/export", methods=["GET"])
def api_research_portfolio_export():
    md = _rdb.export_portfolio_markdown()
    filename = f"portfolio_global_{datetime.now().strftime('%Y%m%d')}.md"
    return Response(md, mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route("/api/research/portfolio/overview", methods=["GET"])
def api_research_portfolio_overview():
    """Coverage card: tese ativa + contadores + snapshot resumido."""
    active = _rdb.get_active_portfolio_thesis()
    year   = datetime.now().year
    return jsonify({
        "active_thesis": active,
        "year":          year,
        "decisions_year":    _rdb.count_portfolio_decisions_year(year),
        "rules_active":      _rdb.count_portfolio_rules_active(),
    })


# =============================================================================
# RESEARCH PIPELINE (Fase 2) — routes + scheduler init
# =============================================================================

import research_pipeline as _pipeline

# Start background scheduler (first run is deferred by interval_hours)
_pipeline.scheduler.start()


# ── Pipeline status & manual trigger ──────────────────────────────────────

@app.route("/api/research/pipeline/status", methods=["GET"])
def api_pipeline_status():
    return jsonify(_pipeline.scheduler.get_status())


@app.route("/api/research/pipeline/run", methods=["POST"])
def api_pipeline_run():
    """Manually trigger the ingestion pipeline (admin only)."""
    if session.get("role") != "admin":
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    days_back = int(data.get("days_back", 30))
    _pipeline.scheduler.run_now(days_back=days_back)
    return jsonify({"ok": True, "message": "Pipeline iniciado em background"})


@app.route("/api/research/pipeline/interval", methods=["POST"])
def api_pipeline_set_interval():
    """Change the scheduler interval (admin only)."""
    if session.get("role") != "admin":
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    hours = float(data.get("hours", 6))
    _pipeline.scheduler.set_interval(hours)
    return jsonify({"ok": True, "interval_hours": hours})


# ── CNPJ mapping management ───────────────────────────────────────────────

@app.route("/api/research/pipeline/cnpj", methods=["GET"])
def api_pipeline_cnpj_get():
    if session.get("role") != "admin":
        return jsonify({"error": "forbidden"}), 403
    return jsonify(_pipeline.get_cnpj_map())


@app.route("/api/research/pipeline/cnpj", methods=["POST"])
def api_pipeline_cnpj_set():
    """Add or update a ticker→CNPJ mapping (admin only)."""
    if session.get("role") != "admin":
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    ticker = (data.get("ticker") or "").upper().strip()
    cnpj   = (data.get("cnpj") or "").strip()
    if not ticker or not cnpj:
        return jsonify({"error": "ticker e cnpj obrigatórios"}), 400
    _pipeline.upsert_cnpj(ticker, cnpj)
    return jsonify({"ok": True, "ticker": ticker, "cnpj": cnpj})


# ── Manual ingestor ────────────────────────────────────────────────────────

@app.route("/api/research/ingest", methods=["POST"])
def api_research_ingest():
    """
    Accept a manually pasted article/report and process it with Claude.
    Body: { ticker, text, source? }
    """
    if session.get("role") not in ("admin", "equipe"):
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json(silent=True) or {}
    ticker = (data.get("ticker") or "").upper().strip()
    text   = (data.get("text") or "").strip()
    source = (data.get("source") or "Manual").strip()
    if not ticker or not text:
        return jsonify({"error": "ticker e text obrigatórios"}), 400

    user = session.get("role", "equipe")
    news_id, analysis = _pipeline.manual_ingestor.ingest(
        ticker=ticker, text=text, source=source, user=user
    )
    if news_id is None:
        return jsonify({"error": "Falha ao processar com Claude (verifique ANTHROPIC_API_KEY)"}), 500

    return jsonify({
        "ok":      True,
        "news_id": news_id,
        "analysis": analysis,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
