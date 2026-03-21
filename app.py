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
FUNDAMENTALS_TTL = 7 * 24 * 3600
HISTORY_TTL      = 4 * 3600

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
    "tab_table": True,
    "tab_charts": True,
    "tab_config": True,
    "tab_history": True,
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

def fetch_fundamentals(tickers):
    result = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            dy, roe, beta, ev_ebitda = info.get("dividendYield"), info.get("returnOnEquity"), info.get("beta"), info.get("enterpriseToEbitda")
            sector_en = info.get("sector")
            result[ticker] = {
                "trailing_pe":         _round(info.get("trailingPE"), 1),
                "forward_pe":          _round(info.get("forwardPE"), 1),
                "price_to_book":       _round(info.get("priceToBook"), 1),
                "dividend_yield":      round(dy * 100, 2) if dy else None,
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
    if any(now > cache.get(t, {}).get("expires_at", 0) for t in tickers):
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

    valid = [r for r in rows if r.get("pct_total") and r.get("var_dia_pct") is not None]
    retorno_carteira = sum((r["var_dia_pct"] / 100) * (r["pct_total"] / 100) for r in valid) if valid else 0.0

    ibov_data    = prices.get("^BVSP", {})
    ibov_ret_pct = ibov_data.get("change_pct") or 0
    ibov_ret     = ibov_ret_pct / 100

    alpha        = retorno_carteira - ibov_ret
    provisao_pct = max(0.0, alpha * fee_rate)

    nav_carteira = sum(r.get("valor_liquido") or 0 for r in rows)
    nav_total    = nav_carteira + caixa + proventos - custos
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
            "lucro_mi_25":   pos.get("lucro_mi_25"),
            "pl_alvo_25":    pos.get("pl_alvo_25"),
            "preco_alvo": pa, "preco": price,
            "var_dia_pct": pd_.get("change_pct"),
            "valor_liquido": vl, "upside_pct": upside,
            "trailing_pe": fund.get("trailing_pe"), "forward_pe": fund.get("forward_pe"),
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

    return {
        "fund_name": portfolio["fund_name"], "total_value": round(total_value, 2),
        "weighted_upside": weighted_upside, "weighted_beta": weighted_beta,
        "last_price_update": datetime.now().isoformat(), "rows": rows,
    }

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

EXPORT_HEADERS = [
    "Ativo","Categoria","Setor","% Total","Valor Líquido (R$)","Preço (R$)",
    "Var. Dia %","Quantidade","Liq. Diária (mm)",
    "P/L Trailing","P/L Forward","EV/EBITDA","ROE %","Beta",
    "Lucro mi 25","P/L Alvo 25","P/VPA","Div. Yield %","Mkt Cap (Bi R$)","Preço Alvo (R$)","Upside %",
]

def row_to_export(r):
    return [r["ticker"],r["categoria"],r.get("sector"),r["pct_total"],r["valor_liquido"],r["preco"],
            r["var_dia_pct"],r["quantidade"],r["liq_diaria_mm"],
            r["trailing_pe"],r["forward_pe"],r.get("enterprise_to_ebitda"),r.get("return_on_equity"),r.get("beta"),
            r["lucro_mi_25"],r["pl_alvo_25"],r["price_to_book"],r["dividend_yield"],r["market_cap_bi"],r["preco_alvo"],r["upside_pct"]]

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
    return jsonify({"prices": prices, "timestamp": datetime.now().isoformat()})

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
            for field in ["quantidade","liq_diaria_mm","lucro_mi_25","pl_alvo_25","preco_alvo"]:
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
        "liq_diaria_mm": _f("liq_diaria_mm"), "lucro_mi_25": _f("lucro_mi_25"),
        "pl_alvo_25": _f("pl_alvo_25"), "preco_alvo": _f("preco_alvo"),
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

    # ── IBOV (existing logic) ──
    ibov_map = {}
    if cache.get(ibov_key) and now < cache[ibov_key].get("expires_at", 0):
        ibov_map = cache[ibov_key]["data"]
    else:
        import pandas as pd
        start   = history[0]["data"]
        end_dt  = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
        try:
            df = yf.download("^BVSP", start=start, end=end_dt.strftime("%Y-%m-%d"),
                             progress=False, auto_adjust=True)
            if not df.empty:
                close = df["Close"]
                if hasattr(close, "squeeze"):
                    close = close.squeeze()
                ibov_map = {str(d.date()): round(float(v), 2) for d, v in close.items()}
        except Exception as e:
            ibov_map = {}
        cache[ibov_key] = {"data": ibov_map, "expires_at": now + HISTORY_TTL}
        save_cache(cache)

    # ── Additional benchmarks: SMLL, IDIV, S&P500, NASDAQ, CDI ──
    benchmark_maps = {}
    if cache.get(benchmarks_key) and now < cache[benchmarks_key].get("expires_at", 0):
        benchmark_maps = cache[benchmarks_key]["data"]
    else:
        import pandas as pd
        start  = history[0]["data"]
        end_dt = datetime.strptime(history[-1]["data"], "%Y-%m-%d") + timedelta(days=5)
        # SMLL11.SA = iShares Small Cap ETF (proxy SMLL index)
        # DIVO11.SA = iShares IDIV ETF (proxy IDIV index)
        extra_tickers = {
            "^SMLL":  "^SMLL",
            "^IDIV":  "DIVO11.SA",
            "^GSPC":  "^GSPC",
            "^IXIC":  "^IXIC",
        }
        try:
            df = yf.download(list(extra_tickers.values()), start=start,
                             end=end_dt.strftime("%Y-%m-%d"),
                             progress=False, auto_adjust=True)
            if not df.empty:
                close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df
                for out_key, yf_ticker in extra_tickers.items():
                    if yf_ticker in close.columns:
                        s = close[yf_ticker].dropna()
                        if not s.empty:
                            benchmark_maps[out_key] = {
                                str(d.date()): round(float(v), 2)
                                for d, v in s.items()
                            }
        except Exception:
            pass
        # CDI cumulative index (starts at 100 on inception date, compounds daily)
        try:
            cdi_daily = load_cdi_map()
            if cdi_daily:
                cumulative = 100.0
                cdi_cum = {}
                for d in sorted(cdi_daily.keys()):
                    cumulative *= (1 + cdi_daily[d] / 100)
                    cdi_cum[d] = round(cumulative, 6)
                benchmark_maps["cdi"] = cdi_cum
        except Exception:
            pass
        cache[benchmarks_key] = {"data": benchmark_maps, "expires_at": now + HISTORY_TTL}
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
            df = yf.download("^BVSP", start=start, end=end_dt.strftime("%Y-%m-%d"),
                             progress=False, auto_adjust=True)
            if not df.empty:
                close = df["Close"]
                if hasattr(close, "squeeze"):
                    close = close.squeeze()
                ibov_map = {str(d.date()): round(float(v), 2) for d, v in close.items()}
        except Exception:
            ibov_map = {}
        cache[ibov_key] = {"data": ibov_map, "expires_at": now + HISTORY_TTL}
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

if __name__ == "__main__":
    app.run(debug=True, port=5000)
