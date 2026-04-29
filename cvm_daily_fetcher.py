"""
cvm_daily_fetcher.py — Ingestão do Informe Diário (FI-DOC INF_DIARIO) e do
cadastro de fundos (FI-CAD) direto da CVM para o HARBOUR IAT FIF AÇÕES RL.

Fonte: https://dados.cvm.gov.br/dataset/fi-doc-inf_diario
       https://dados.cvm.gov.br/dataset/fi-cad

Exposed:
    fetch_month(year_month)      -> list[dict]  # records do fundo no mês
    fetch_cadastro()             -> dict|None    # linha do cadastro do fundo
    refresh_current()            -> dict         # upsert mês atual + M-1
    backfill_since(start="2022-04") -> dict      # recarrega todo o histórico
    load_storage()               -> dict         # lê cvm_daily.json
    load_cadastro()              -> dict         # lê cvm_cadastro.json
    get_status()                 -> dict         # info do último refresh

A linha do fundo é filtrada em memória por HARBOUR_CNPJ — baixamos o mensal
inteiro mas só gravamos ~20 linhas/mês (dias úteis do fundo).

O refresh diário é orquestrado pelo GitHub Actions (.github/workflows/cvm-daily.yml),
que roda refresh_current() no runner e dá commit do JSON. O Flask só serve o
arquivo pronto — sem thread daemon dentro do worker do Render (memória apertada).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DAILY_FILE = os.path.join(DATA_DIR, "cvm_daily.json")
CAD_FILE = os.path.join(DATA_DIR, "cvm_cadastro.json")

HARBOUR_CNPJ = "29599391000194"
COTA_INICIO = "2022-04-18"

# URLs oficiais CVM (verificadas 20/04/2026)
# INF_DIARIO: schema antigo usa coluna `CNPJ_FUNDO`; a partir de 2024, schema novo
# (Res. CVM 175) usa `CNPJ_FUNDO_CLASSE` + `TP_FUNDO_CLASSE` + `ID_SUBCLASSE`.
INF_DIARIO_URL = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{ym}.zip"
INF_DIARIO_CSV = "inf_diario_fi_{ym}.csv"

# Cadastro novo (Res. CVM 175) — substitui o antigo cad_fi.csv para fundos adaptados.
# Contém 3 CSVs: registro_fundo.csv, registro_classe.csv, registro_subclasse.csv
CAD_REGISTRO_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"
CAD_FI_URL = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv"  # fallback (pré-Res.175)

BRT_OFFSET = timezone(timedelta(hours=-3))

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "harbour-fia-tracker/1.0 cvm-daily (contact: admin@harbourcapital.com.br)"
})

_io_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cnpj_digits(cnpj: str) -> str:
    return "".join(c for c in (cnpj or "") if c.isdigit())


def _parse_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(v) -> int | None:
    f = _parse_float(v)
    return int(f) if f is not None else None


def _iter_months(start_ym: str, end_ym: str):
    """Yield YYYYMM from start to end inclusive."""
    y, m = int(start_ym[:4]), int(start_ym[4:])
    ey, em = int(end_ym[:4]), int(end_ym[4:])
    while (y, m) <= (ey, em):
        yield f"{y:04d}{m:02d}"
        m += 1
        if m > 12:
            m = 1
            y += 1


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _empty_storage() -> dict:
    return {
        "cnpj": HARBOUR_CNPJ,
        "cota_inicio": COTA_INICIO,
        "last_refresh": None,
        "records": [],
    }


def load_storage() -> dict:
    if not os.path.exists(DAILY_FILE):
        return _empty_storage()
    try:
        with open(DAILY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("cnpj", HARBOUR_CNPJ)
        data.setdefault("cota_inicio", COTA_INICIO)
        data.setdefault("last_refresh", None)
        data.setdefault("records", [])
        return data
    except Exception as e:
        logger.error("cvm_daily load_storage: %s", e)
        return _empty_storage()


def _save_storage(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with _io_lock:
        with open(DAILY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_cadastro() -> dict | None:
    if not os.path.exists(CAD_FILE):
        return None
    try:
        with open(CAD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("cvm_daily load_cadastro: %s", e)
        return None


def _save_cadastro(row: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with _io_lock:
        with open(CAD_FILE, "w", encoding="utf-8") as f:
            json.dump(row, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Fetch — Informe Diário (mensal)
# ---------------------------------------------------------------------------

def fetch_month(year_month: str, cnpj: str = HARBOUR_CNPJ) -> list[dict]:
    """Baixa o ZIP mensal do INF_DIARIO e devolve só as linhas do CNPJ alvo.

    Suporta os dois schemas:
      - Pré-2024:  CNPJ_FUNDO
      - Pós-Res. CVM 175:  CNPJ_FUNDO_CLASSE + TP_FUNDO_CLASSE + ID_SUBCLASSE
    """
    ym = year_month.replace("-", "")[:6]
    url = INF_DIARIO_URL.format(ym=ym)

    try:
        r = _SESSION.get(url, timeout=60)
        r.raise_for_status()
    except Exception as e:
        logger.warning("cvm_daily fetch_month %s: %s", ym, e)
        return []

    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile as e:
        logger.warning("cvm_daily fetch_month %s bad zip: %s", ym, e)
        return []

    csv_name = INF_DIARIO_CSV.format(ym=ym)
    names = z.namelist()
    target = csv_name if csv_name in names else next((n for n in names if n.endswith(".csv")), None)
    if not target:
        logger.warning("cvm_daily fetch_month %s: CSV não encontrado no zip", ym)
        return []

    target_cnpj = _cnpj_digits(cnpj)
    rows: list[dict] = []
    try:
        with z.open(target) as f:
            text = io.TextIOWrapper(f, encoding="latin-1", errors="replace", newline="")
            reader = csv.DictReader(text, delimiter=";")
            fields = reader.fieldnames or []
            cnpj_col = "CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in fields else "CNPJ_FUNDO"
            only_main_class = "ID_SUBCLASSE" in fields
            for row in reader:
                if _cnpj_digits(row.get(cnpj_col, "")) != target_cnpj:
                    continue
                # Se existir ID_SUBCLASSE preenchido, é registro de subclasse; ignoramos
                # (queremos o record da classe principal, que vem com ID_SUBCLASSE vazio)
                if only_main_class and (row.get("ID_SUBCLASSE") or "").strip():
                    continue
                rec = {
                    "dt_comptc": (row.get("DT_COMPTC") or "")[:10],
                    "vl_quota": _parse_float(row.get("VL_QUOTA")),
                    "vl_patrim_liq": _parse_float(row.get("VL_PATRIM_LIQ")),
                    "vl_total": _parse_float(row.get("VL_TOTAL")),
                    "captc_dia": _parse_float(row.get("CAPTC_DIA")) or 0.0,
                    "resg_dia": _parse_float(row.get("RESG_DIA")) or 0.0,
                    "nr_cotst": _parse_int(row.get("NR_COTST")),
                }
                if not rec["dt_comptc"] or rec["vl_quota"] is None:
                    continue
                rows.append(rec)
    except Exception as e:
        logger.error("cvm_daily fetch_month %s parse: %s", ym, e)
        return []

    rows.sort(key=lambda r: r["dt_comptc"])
    logger.info("cvm_daily fetch_month %s: %d linhas para %s", ym, len(rows), cnpj)
    return rows


# ---------------------------------------------------------------------------
# Fetch — Cadastro (registro_fundo_classe.zip, Res. CVM 175)
# ---------------------------------------------------------------------------

# Campos preservados do registro_fundo.csv (fundo — estrutura jurídica)
FUNDO_FIELDS = (
    "ID_Registro_Fundo", "CNPJ_Fundo", "Codigo_CVM", "Data_Registro",
    "Data_Constituicao", "Tipo_Fundo", "Denominacao_Social", "Situacao",
    "Data_Inicio_Situacao", "Data_Adaptacao_RCVM175", "Patrimonio_Liquido",
    "Data_Patrimonio_Liquido", "Diretor", "CNPJ_Administrador",
    "Administrador", "Tipo_Pessoa_Gestor", "CPF_CNPJ_Gestor", "Gestor",
)

# Campos preservados do registro_classe.csv (classe — onde o CNPJ público mora)
CLASSE_FIELDS = (
    "ID_Registro_Fundo", "ID_Registro_Classe", "CNPJ_Classe", "Codigo_CVM",
    "Data_Registro", "Data_Constituicao", "Data_Inicio", "Tipo_Classe",
    "Denominacao_Social", "Situacao", "Data_Inicio_Situacao",
    "Classificacao", "Indicador_Desempenho", "Classificacao_Anbima",
    "Tributacao_Longo_Prazo", "Forma_Condominio", "Publico_Alvo",
    "Patrimonio_Liquido", "Data_Patrimonio_Liquido",
    "CNPJ_Auditor", "Auditor", "CNPJ_Custodiante", "Custodiante",
)


def _read_zip_csv(zip_bytes: bytes, filename: str) -> list[dict]:
    """Lê um CSV dentro de um ZIP, tentando UTF-8 e depois latin-1."""
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    if filename not in z.namelist():
        return []
    raw = z.read(filename)
    for enc in ("utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            return list(csv.DictReader(io.StringIO(text), delimiter=";"))
        except UnicodeDecodeError:
            continue
    return list(csv.DictReader(io.StringIO(raw.decode("latin-1", errors="replace")), delimiter=";"))


def fetch_cadastro(cnpj: str = HARBOUR_CNPJ) -> dict | None:
    """Baixa registro_fundo_classe.zip e devolve dict com dados do fundo+classe.
       Fallback: cad_fi.csv antigo se o novo falhar.
    """
    target = _cnpj_digits(cnpj)

    # Tenta o cadastro novo (Res. CVM 175)
    try:
        r = _SESSION.get(CAD_REGISTRO_URL, timeout=90)
        r.raise_for_status()
    except Exception as e:
        logger.warning("cvm_daily fetch_cadastro (novo): %s", e)
        return _fetch_cadastro_legacy(cnpj)

    try:
        classe_rows = _read_zip_csv(r.content, "registro_classe.csv")
        fundo_rows = _read_zip_csv(r.content, "registro_fundo.csv")
    except Exception as e:
        logger.error("cvm_daily fetch_cadastro parse: %s", e)
        return _fetch_cadastro_legacy(cnpj)

    classe = next(
        (row for row in classe_rows if _cnpj_digits(row.get("CNPJ_Classe", "")) == target),
        None,
    )
    if not classe:
        logger.info("cvm_daily fetch_cadastro: CNPJ %s não encontrado no registro_classe", cnpj)
        return _fetch_cadastro_legacy(cnpj)

    id_fundo = classe.get("ID_Registro_Fundo", "")
    fundo = next(
        (row for row in fundo_rows if row.get("ID_Registro_Fundo") == id_fundo),
        None,
    )

    out = {"source": "registro_fundo_classe"}
    out["classe"] = {k: (classe.get(k) or "").strip() for k in CLASSE_FIELDS if k in classe}
    if fundo:
        out["fundo"] = {k: (fundo.get(k) or "").strip() for k in FUNDO_FIELDS if k in fundo}
    out["fetched_at"] = datetime.now(BRT_OFFSET).isoformat(timespec="seconds")
    return out


def _fetch_cadastro_legacy(cnpj: str) -> dict | None:
    """Fallback para o cad_fi.csv antigo (fundos não adaptados à Res. 175)."""
    try:
        r = _SESSION.get(CAD_FI_URL, timeout=60)
        r.raise_for_status()
    except Exception as e:
        logger.warning("cvm_daily fetch_cadastro_legacy: %s", e)
        return None

    target = _cnpj_digits(cnpj)
    try:
        text = r.content.decode("latin-1", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for row in reader:
            if _cnpj_digits(row.get("CNPJ_FUNDO", "")) != target:
                continue
            return {
                "source": "cad_fi_legacy",
                "fundo": {k.lower(): (row.get(k) or "").strip() for k in row},
                "fetched_at": datetime.now(BRT_OFFSET).isoformat(timespec="seconds"),
            }
    except Exception as e:
        logger.error("cvm_daily fetch_cadastro_legacy parse: %s", e)
    return None


# ---------------------------------------------------------------------------
# Upsert logic
# ---------------------------------------------------------------------------

def _upsert_records(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge by dt_comptc (new rows override existing)."""
    idx = {r["dt_comptc"]: r for r in existing}
    for r in new:
        idx[r["dt_comptc"]] = r
    merged = list(idx.values())
    merged.sort(key=lambda r: r["dt_comptc"])
    return merged


def refresh_current() -> dict:
    """Baixa mês atual + mês anterior e faz upsert."""
    now = datetime.now(BRT_OFFSET)
    cur = now.strftime("%Y%m")
    prev_dt = (now.replace(day=1) - timedelta(days=1))
    prev = prev_dt.strftime("%Y%m")

    storage = load_storage()
    total_new = 0
    months_done = []
    errors = []

    for ym in (prev, cur):
        try:
            rows = fetch_month(ym)
            if rows:
                before = len(storage["records"])
                storage["records"] = _upsert_records(storage["records"], rows)
                total_new += len(storage["records"]) - before
                months_done.append(ym)
        except Exception as e:
            errors.append(f"{ym}: {e}")
            logger.error("cvm_daily refresh_current %s: %s", ym, e)

    # Cadastro — refaz só se nunca foi baixado ou >7 dias
    cad = load_cadastro()
    cad_age = None
    if cad and cad.get("fetched_at"):
        try:
            fetched = datetime.fromisoformat(cad["fetched_at"])
            cad_age = (datetime.now(BRT_OFFSET) - fetched).total_seconds() / 86400
        except Exception:
            cad_age = None
    if cad is None or (cad_age is not None and cad_age > 7):
        new_cad = fetch_cadastro()
        if new_cad:
            _save_cadastro(new_cad)

    storage["last_refresh"] = datetime.now(BRT_OFFSET).isoformat(timespec="seconds")
    _save_storage(storage)

    return {
        "mode": "refresh",
        "months": months_done,
        "new_rows": total_new,
        "total_rows": len(storage["records"]),
        "errors": errors,
        "last_refresh": storage["last_refresh"],
    }


def backfill_since(start: str = "2022-04", end: str | None = None) -> dict:
    """Recarrega histórico completo desde `start` (YYYY-MM)."""
    start_ym = start.replace("-", "")[:6]
    if end:
        end_ym = end.replace("-", "")[:6]
    else:
        end_ym = datetime.now(BRT_OFFSET).strftime("%Y%m")

    all_rows: list[dict] = []
    months_done = []
    errors = []

    for ym in _iter_months(start_ym, end_ym):
        try:
            rows = fetch_month(ym)
            if rows:
                all_rows.extend(rows)
                months_done.append(ym)
            time.sleep(0.3)   # gentileza com o servidor CVM
        except Exception as e:
            errors.append(f"{ym}: {e}")
            logger.error("cvm_daily backfill %s: %s", ym, e)

    # Dedup por data
    merged = _upsert_records([], all_rows)

    # Filtra por data de início da cota pública
    merged = [r for r in merged if r["dt_comptc"] >= COTA_INICIO]

    storage = _empty_storage()
    storage["records"] = merged
    storage["last_refresh"] = datetime.now(BRT_OFFSET).isoformat(timespec="seconds")
    _save_storage(storage)

    # Cadastro — sempre refaz no backfill
    cad = fetch_cadastro()
    if cad:
        _save_cadastro(cad)

    return {
        "mode": "backfill",
        "months": months_done,
        "total_rows": len(merged),
        "errors": errors,
        "last_refresh": storage["last_refresh"],
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_status() -> dict:
    """Retorna info do último refresh. Lê do JSON em disco (fonte de verdade
    cross-process — refresh roda no GitHub Actions, não no worker do Flask)."""
    storage = load_storage()
    return {
        "last_refresh": storage.get("last_refresh"),
        "total_rows":   len(storage.get("records") or []),
        "cnpj":         storage.get("cnpj"),
        "cota_inicio":  storage.get("cota_inicio"),
    }
