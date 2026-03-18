import csv
import io
import json
import os
import time
from datetime import datetime, timedelta

import yfinance as yf
from flask import Flask, Response, jsonify, render_template, request, send_file

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
CACHE_FILE = os.path.join(DATA_DIR, "cache.json")

# In-memory price cache (30 seconds TTL)
_price_cache = {"data": {}, "expires_at": 0}

FUNDAMENTALS_TTL = 7 * 24 * 3600   # 7 days
HISTORY_TTL = 4 * 3600              # 4 hours

SECTOR_PT = {
    "Energy": "Energia",
    "Financial Services": "Serv. Financeiros",
    "Real Estate": "Imobiliário",
    "Consumer Cyclical": "Consumo Cíclico",
    "Consumer Defensive": "Consumo Básico",
    "Healthcare": "Saúde",
    "Technology": "Tecnologia",
    "Industrials": "Industriais",
    "Basic Materials": "Mat. Básicos",
    "Communication Services": "Comunicação",
    "Utilities": "Utilidades",
}


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def load_portfolio():
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_portfolio(data):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(data):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Price fetching (real-time, 30s cache)
# ---------------------------------------------------------------------------

def fetch_prices(tickers):
    result = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).fast_info
            price = info.last_price
            prev = info.previous_close
            result[ticker] = {
                "price": round(price, 2) if price else None,
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
# Fundamentals fetching (weekly cache)
# ---------------------------------------------------------------------------

def fetch_fundamentals(tickers):
    result = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            dy = info.get("dividendYield")
            roe = info.get("returnOnEquity")
            beta = info.get("beta")
            ev_ebitda = info.get("enterpriseToEbitda")
            sector_en = info.get("sector")
            result[ticker] = {
                "trailing_pe": _round(info.get("trailingPE"), 1),
                "forward_pe": _round(info.get("forwardPE"), 1),
                "price_to_book": _round(info.get("priceToBook"), 1),
                "dividend_yield": round(dy * 100, 2) if dy else None,
                "market_cap": info.get("marketCap"),
                "fifty_two_week_high": _round(info.get("fiftyTwoWeekHigh"), 2),
                "fifty_two_week_low": _round(info.get("fiftyTwoWeekLow"), 2),
                "short_name": info.get("shortName") or info.get("longName"),
                "beta": _round(beta, 2),
                "enterprise_to_ebitda": _round(ev_ebitda, 1),
                "return_on_equity": round(roe * 100, 1) if roe is not None else None,
                "sector": SECTOR_PT.get(sector_en, sector_en) if sector_en else None,
            }
        except Exception as e:
            result[ticker] = {"error": str(e)}
    return result


def _round(val, decimals):
    if val is None:
        return None
    try:
        return round(float(val), decimals)
    except Exception:
        return None


def get_cached_fundamentals(tickers):
    cache = load_cache()
    now = time.time()
    needs_refresh = any(now > cache.get(t, {}).get("expires_at", 0) for t in tickers)
    if needs_refresh:
        fresh = fetch_fundamentals(tickers)
        for ticker, data in fresh.items():
            cache[ticker] = {**data, "expires_at": now + FUNDAMENTALS_TTL}
        save_cache(cache)
    return {t: {k: v for k, v in cache.get(t, {}).items() if k != "expires_at"} for t in tickers}


# ---------------------------------------------------------------------------
# Portfolio history vs IBOV (4h cache)
# ---------------------------------------------------------------------------

def compute_portfolio_history(positions, days=90):
    """Compute normalized portfolio performance vs IBOV."""
    import pandas as pd

    tickers = [p["yahoo_ticker"] for p in positions]
    qty_map = {p["yahoo_ticker"]: p["quantidade"] for p in positions}
    all_tickers = tickers + ["^BVSP"]

    end = datetime.now()
    start = end - timedelta(days=days + 45)

    try:
        df = yf.download(
            all_tickers,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        return {"series": [], "error": str(e)}

    if df.empty:
        return {"series": []}

    # Extract Close prices — handle MultiIndex (multiple tickers) or flat (single)
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"]
    else:
        close = df[["Close"]].copy()
        close.columns = [all_tickers[0]]

    close = close.ffill()

    # Portfolio value per day
    port = pd.Series(0.0, index=close.index)
    for ticker in tickers:
        if ticker in close.columns:
            port += close[ticker] * qty_map.get(ticker, 0)

    ibov = close["^BVSP"] if "^BVSP" in close.columns else None

    valid = port.dropna()
    valid = valid[valid > 0].tail(days)
    if len(valid) == 0:
        return {"series": []}

    base_port = float(valid.iloc[0])
    base_ibov = float(ibov.loc[valid.index[0]]) if ibov is not None and valid.index[0] in ibov.index else None

    series = []
    for dt in valid.index:
        pv = float(valid[dt])
        ibov_norm = None
        if ibov is not None and base_ibov and dt in ibov.index:
            iv = ibov[dt]
            if not (iv != iv):  # not NaN
                ibov_norm = round(float(iv) / base_ibov * 100, 2)
        series.append({
            "date": dt.strftime("%Y-%m-%d"),
            "portfolio": round(pv / base_port * 100, 2) if base_port else None,
            "portfolio_abs": round(pv, 2),
            "ibov": ibov_norm,
        })
    return {"series": series}


def get_cached_history(positions, days=90):
    cache = load_cache()
    now = time.time()
    key = f"history_{days}"
    if cache.get(key) and now < cache[key].get("expires_at", 0):
        return cache[key]["data"]
    data = compute_portfolio_history(positions, days)
    cache[key] = {"data": data, "expires_at": now + HISTORY_TTL}
    save_cache(cache)
    return data


def invalidate_history_cache():
    cache = load_cache()
    for key in list(cache.keys()):
        if key.startswith("history_"):
            del cache[key]
    save_cache(cache)


# ---------------------------------------------------------------------------
# Portfolio response builder
# ---------------------------------------------------------------------------

def build_portfolio_response(portfolio, prices, fundamentals):
    positions = portfolio["positions"]
    rows = []
    total_value = 0.0

    for pos in positions:
        yahoo = pos["yahoo_ticker"]
        price_data = prices.get(yahoo, {})
        fund = fundamentals.get(yahoo, {})

        price = price_data.get("price")
        qtde = pos["quantidade"]
        valor_liquido = round(price * qtde, 2) if price else None
        if valor_liquido:
            total_value += valor_liquido

        preco_alvo = pos.get("preco_alvo")
        upside = round((preco_alvo / price - 1) * 100, 2) if price and preco_alvo and price > 0 else None

        mc = fund.get("market_cap")
        rows.append({
            "ticker": pos["ticker"],
            "yahoo_ticker": yahoo,
            "categoria": pos.get("categoria", "Acao"),
            "quantidade": qtde,
            "liq_diaria_mm": pos.get("liq_diaria_mm"),
            "lucro_mi_25": pos.get("lucro_mi_25"),
            "pl_alvo_25": pos.get("pl_alvo_25"),
            "preco_alvo": preco_alvo,
            # Real-time
            "preco": price,
            "var_dia_pct": price_data.get("change_pct"),
            # Calculated
            "valor_liquido": valor_liquido,
            "upside_pct": upside,
            # Fundamentals (weekly)
            "trailing_pe": fund.get("trailing_pe"),
            "forward_pe": fund.get("forward_pe"),
            "price_to_book": fund.get("price_to_book"),
            "dividend_yield": fund.get("dividend_yield"),
            "market_cap_bi": round(mc / 1e9, 1) if mc else None,
            "week_high": fund.get("fifty_two_week_high"),
            "week_low": fund.get("fifty_two_week_low"),
            "short_name": fund.get("short_name"),
            # New fields
            "beta": fund.get("beta"),
            "enterprise_to_ebitda": fund.get("enterprise_to_ebitda"),
            "return_on_equity": fund.get("return_on_equity"),
            "sector": fund.get("sector") or pos.get("categoria", "Outros"),
        })

    # % / Total
    for row in rows:
        if row["valor_liquido"] and total_value > 0:
            row["pct_total"] = round(row["valor_liquido"] / total_value * 100, 2)
        else:
            row["pct_total"] = None

    # Weighted average upside
    weighted_upside = None
    if total_value > 0:
        ws = sum(
            r["upside_pct"] * (r["valor_liquido"] / total_value)
            for r in rows
            if r["upside_pct"] is not None and r["valor_liquido"]
        )
        weighted_upside = round(ws, 2)

    # Portfolio beta (weighted average)
    weighted_beta = None
    beta_rows = [r for r in rows if r["beta"] is not None and r["valor_liquido"]]
    if beta_rows and total_value > 0:
        wb = sum(r["beta"] * r["valor_liquido"] / total_value for r in beta_rows)
        weighted_beta = round(wb, 2)

    return {
        "fund_name": portfolio["fund_name"],
        "total_value": round(total_value, 2),
        "weighted_upside": weighted_upside,
        "weighted_beta": weighted_beta,
        "last_price_update": datetime.now().isoformat(),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

EXPORT_HEADERS = [
    "Ativo", "Categoria", "Setor", "% Total", "Valor Líquido (R$)", "Preço (R$)",
    "Var. Dia %", "Quantidade", "Liq. Diária (mm)",
    "P/L Trailing", "P/L Forward", "EV/EBITDA", "ROE %", "Beta",
    "Lucro mi 25", "P/L Alvo 25", "P/VPA", "Div. Yield %",
    "Mkt Cap (Bi R$)", "Preço Alvo (R$)", "Upside %",
]


def row_to_export(row):
    return [
        row["ticker"], row["categoria"], row.get("sector"),
        row["pct_total"], row["valor_liquido"], row["preco"],
        row["var_dia_pct"], row["quantidade"], row["liq_diaria_mm"],
        row["trailing_pe"], row["forward_pe"],
        row.get("enterprise_to_ebitda"), row.get("return_on_equity"), row.get("beta"),
        row["lucro_mi_25"], row["pl_alvo_25"], row["price_to_book"],
        row["dividend_yield"], row["market_cap_bi"],
        row["preco_alvo"], row["upside_pct"],
    ]


def get_export_data():
    portfolio = load_portfolio()
    tickers = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices = get_cached_prices(tickers)
    fundamentals = get_cached_fundamentals(tickers)
    return build_portfolio_response(portfolio, prices, fundamentals)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/portfolio")
def api_portfolio():
    portfolio = load_portfolio()
    tickers = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices = get_cached_prices(tickers)
    fundamentals = get_cached_fundamentals(tickers)
    return jsonify(build_portfolio_response(portfolio, prices, fundamentals))


@app.route("/api/prices")
def api_prices():
    portfolio = load_portfolio()
    tickers = [p["yahoo_ticker"] for p in portfolio["positions"]]
    prices = get_cached_prices(tickers)
    return jsonify({"prices": prices, "timestamp": datetime.now().isoformat()})


@app.route("/api/fundamentals")
def api_fundamentals():
    portfolio = load_portfolio()
    tickers = [p["yahoo_ticker"] for p in portfolio["positions"]]
    fundamentals = get_cached_fundamentals(tickers)
    return jsonify({"fundamentals": fundamentals})


@app.route("/api/history")
def api_history():
    days = int(request.args.get("days", 90))
    days = max(10, min(days, 365))
    portfolio = load_portfolio()
    data = get_cached_history(portfolio["positions"], days)
    return jsonify(data)


@app.route("/api/export/csv")
def api_export_csv():
    data = get_export_data()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPORT_HEADERS)
    for row in data["rows"]:
        writer.writerow(row_to_export(row))
    output.seek(0)
    filename = f"harbour_fia_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        "\ufeff" + output.getvalue(),  # BOM for Excel UTF-8
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/export/excel")
def api_export_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, numbers

    data = get_export_data()

    wb = Workbook()
    ws = wb.active
    ws.title = "Portfólio"

    # Header styles
    hdr_font = Font(bold=True, color="E0E3F0", name="Calibri")
    hdr_fill = PatternFill(start_color="1A1D27", end_color="1A1D27", fill_type="solid")
    hdr_align = Alignment(horizontal="center", vertical="center")

    ws.append(EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = hdr_align

    # Data rows
    for row in data["rows"]:
        ws.append(row_to_export(row))

    # Column widths
    col_widths = [8, 9, 18, 8, 16, 10, 9, 12, 15, 11, 11, 9, 7, 7, 11, 11, 7, 10, 13, 14, 9]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w

    # Header row height
    ws.row_dimensions[1].height = 22

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"harbour_fia_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/portfolio/update", methods=["POST"])
def api_update_position():
    payload = request.json
    ticker = payload.get("ticker")
    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    portfolio = load_portfolio()
    updated = False
    for pos in portfolio["positions"]:
        if pos["ticker"] == ticker:
            for field in ["quantidade", "liq_diaria_mm", "lucro_mi_25", "pl_alvo_25", "preco_alvo"]:
                if field in payload:
                    val = payload[field]
                    pos[field] = float(val) if val not in (None, "") else None
            updated = True
            break

    if not updated:
        return jsonify({"error": "ticker not found"}), 404

    save_portfolio(portfolio)
    invalidate_price_cache()
    invalidate_history_cache()
    return jsonify({"ok": True})


@app.route("/api/portfolio/add", methods=["POST"])
def api_add_position():
    payload = request.json
    ticker = payload.get("ticker", "").upper().strip()
    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    yahoo_ticker = ticker + ".SA"
    try:
        price = yf.Ticker(yahoo_ticker).fast_info.last_price
        if price is None:
            return jsonify({"error": f"Ticker {yahoo_ticker} não encontrado no Yahoo Finance"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    portfolio = load_portfolio()
    if any(p["ticker"] == ticker for p in portfolio["positions"]):
        return jsonify({"error": "Ticker já existe na carteira"}), 409

    def _f(key):
        v = payload.get(key)
        return float(v) if v not in (None, "") else None

    portfolio["positions"].append({
        "ticker": ticker,
        "yahoo_ticker": yahoo_ticker,
        "categoria": payload.get("categoria", "Acao"),
        "quantidade": float(payload.get("quantidade", 0)),
        "liq_diaria_mm": _f("liq_diaria_mm"),
        "lucro_mi_25": _f("lucro_mi_25"),
        "pl_alvo_25": _f("pl_alvo_25"),
        "preco_alvo": _f("preco_alvo"),
    })
    save_portfolio(portfolio)
    invalidate_price_cache()
    invalidate_history_cache()
    return jsonify({"ok": True})


@app.route("/api/portfolio/<ticker>", methods=["DELETE"])
def api_delete_position(ticker):
    portfolio = load_portfolio()
    before = len(portfolio["positions"])
    portfolio["positions"] = [p for p in portfolio["positions"] if p["ticker"] != ticker.upper()]
    if len(portfolio["positions"]) == before:
        return jsonify({"error": "ticker not found"}), 404
    save_portfolio(portfolio)
    invalidate_price_cache()
    invalidate_history_cache()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
