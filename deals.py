"""Official NSE + BSE large-deal fetch, validate, and store. No invented rows."""

from __future__ import annotations

import csv
import io
import re
import time
from datetime import date, datetime, timedelta
from threading import Lock, Thread
from urllib.parse import quote

from bs4 import BeautifulSoup
from psycopg.types.json import Jsonb

from config import (
    BSE_BLOCK_PAGE,
    BSE_BULK_PAGE,
    BSE_HOME,
    IST,
    NSE_BLOCK_CSV,
    NSE_BULK_CSV,
    NSE_INDEX_LIST,
    NSE_LARGE_DEAL_HIST,
    NSE_LARGE_DEAL_PAGE,
    NSE_LARGE_DEAL_SNAP,
    NSE_PREOPEN_FO,
    NSE_QUOTE_EQUITY,
    NSE_SHORT_CSV,
    SECTORS,
)
from db import connect, init_db, insert_ignore_count, now_iso, upsert
from net import Http

LOCK = Lock()
DEAL_CONFLICT = "trade_date, exchange, symbol, deal_type, buy_sell, client_name, quantity, price"
EXCHANGES = ("NSE", "BSE")
DEAL_TYPES = ("BULK", "BLOCK", "SHORT_SELLING")

_SECTOR_LOAD_ORDER = [
    "Private Bank",
    "PSU Bank",
    "Bank",
    "Pharma",
    "Healthcare",
    "Oil & Gas",
    "Energy",
    "IT",
    "Auto",
    "FMCG",
    "Metal",
    "Realty",
    "Consumer Durables",
    "Media",
    "Infra",
    "Commodities",
    "Consumption",
    "Financial Services",
]


def today_ist() -> date:
    return datetime.now(IST).date()


def _f(val):
    if val is None or val == "" or val == "-":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").replace("₹", "").replace(" ", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if s.startswith("."):
        s = "0" + s
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(text) -> str | None:
    if text is None:
        return None
    if isinstance(text, date) and not isinstance(text, datetime):
        return text.isoformat()
    raw = str(text).strip()
    for fmt in (
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d-%b-%y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d-%b-%Y %H:%M:%S",
        "%d-%B-%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.match(r"(\d{1,2})[-/ ]([A-Za-z]{3,})[-/ ](\d{2,4})", raw)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "%d-%b-%Y").date().isoformat()
        except ValueError:
            try:
                return datetime.strptime(
                    f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "%d-%B-%Y"
                ).date().isoformat()
            except ValueError:
                return None
    return None


def _buy_sell(val) -> str:
    s = (str(val or "")).strip().upper()
    if s in ("B", "BUY", "PURCHASE"):
        return "BUY"
    if s in ("S", "SELL", "SALE"):
        return "SELL"
    if s in ("SHORT", "SS"):
        return "SELL"
    return s[:10] if s else ""


def _text(val) -> str:
    return re.sub(r"\s+", " ", str(val or "")).strip()


def _row(raw: dict, **fields) -> dict:
    qty = fields.get("quantity")
    price = fields.get("price")
    value = fields.get("deal_value")
    if value is None and qty not in (None, 0) and price not in (None, 0):
        value = float(qty) * float(price)
    return {
        "trade_date": fields.get("trade_date"),
        "exchange": fields.get("exchange"),
        "symbol": _text(fields.get("symbol")).upper()[:100],
        "company_name": _text(fields.get("company_name"))[:255] or None,
        "isin": _text(fields.get("isin"))[:20] or None,
        "deal_type": fields.get("deal_type"),
        "buy_sell": _buy_sell(fields.get("buy_sell")),
        "client_name": _text(fields.get("client_name")),
        "quantity": int(qty) if qty is not None else None,
        "price": price,
        "deal_value": value,
        "source": fields.get("source"),
        "source_url": fields.get("source_url"),
        "raw_data": raw,
    }


def validate(rec: dict) -> str | None:
    if not rec.get("trade_date") or not _parse_date(rec["trade_date"]):
        return "invalid date"
    if rec.get("exchange") not in EXCHANGES:
        return "unknown exchange"
    if rec.get("deal_type") not in DEAL_TYPES:
        return "unknown deal type"
    if not rec.get("symbol") and not rec.get("company_name"):
        return "missing symbol and company"
    qty = rec.get("quantity")
    if qty is None or qty <= 0:
        return "quantity <= 0"
    price = rec.get("price")
    if rec["deal_type"] == "SHORT_SELLING":
        return None
    if price is None or price <= 0:
        return "price <= 0"
    return None


def _prepare(rec: dict) -> dict:
    trade_date = _parse_date(rec.get("trade_date"))
    price = rec.get("price")
    if rec.get("deal_type") == "SHORT_SELLING" and (price is None or price <= 0):
        price = 0
    qty = rec.get("quantity")
    value = rec.get("deal_value")
    if value is None and qty and price:
        value = float(qty) * float(price)
    raw = rec.get("raw_data") if isinstance(rec.get("raw_data"), dict) else {"raw": rec.get("raw_data")}
    return {
        "trade_date": trade_date,
        "exchange": rec["exchange"],
        "symbol": (rec.get("symbol") or "")[:100],
        "company_name": rec.get("company_name"),
        "isin": rec.get("isin"),
        "deal_type": rec["deal_type"],
        "buy_sell": rec.get("buy_sell") or ("SELL" if rec["deal_type"] == "SHORT_SELLING" else ""),
        "client_name": rec.get("client_name") or "",
        "quantity": int(qty),
        "price": round(float(price or 0), 4),
        "deal_value": round(float(value), 4) if value is not None else None,
        "source": rec.get("source"),
        "source_url": rec.get("source_url"),
        "raw_data": Jsonb(raw),
        "updated_at": datetime.now(IST).replace(tzinfo=None),
    }


def _csv_rows(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        out.append({(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return out


def _nse_hist_csv(http: Http, option: str, start: date, end: date) -> list[dict]:
    if (end - start).days > 365:
        raise RuntimeError("NSE historical range cannot exceed one year")
    url = (
        f"{NSE_LARGE_DEAL_HIST}?optionType={option}"
        f"&from={start.strftime('%d-%m-%Y')}&to={end.strftime('%d-%m-%Y')}&csv=true"
    )
    http.nse_json(NSE_LARGE_DEAL_SNAP)
    r = http.get(
        url,
        headers={
            "Accept": "text/csv,*/*",
            "Referer": NSE_LARGE_DEAL_PAGE,
        },
    )
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"NSE historical {option} HTTP {r.status_code}")
    ctype = r.headers.get("content-type", "")
    if "csv" not in ctype and b"Date" not in r.content[:80]:
        raise RuntimeError(f"NSE historical {option} did not return CSV")
    return _csv_rows(r.content)


def fetch_nse_bulk(http: Http, start: date, end: date) -> list[dict]:
    url = NSE_BULK_CSV
    rows = []
    errors = []
    ok = False
    if start == end == today_ist() or (end - start).days <= 3:
        try:
            snap = http.nse_json(NSE_LARGE_DEAL_SNAP)
            ok = True
            for item in snap.get("BULK_DEALS_DATA") or []:
                if isinstance(item, dict):
                    rows.append(
                        _row(
                            item,
                            trade_date=_parse_date(item.get("date")),
                            exchange="NSE",
                            symbol=item.get("symbol"),
                            company_name=item.get("name"),
                            deal_type="BULK",
                            buy_sell=item.get("buySell"),
                            client_name=item.get("clientName"),
                            quantity=_f(item.get("qty")),
                            price=_f(item.get("watp")),
                            source="NSE",
                            source_url=NSE_LARGE_DEAL_SNAP,
                        )
                    )
        except Exception as exc:
            errors.append(str(exc))
        r = http.get(url, headers={"Referer": "https://www.nseindia.com/"})
        if r.status_code == 200 and r.content:
            ok = True
            for item in _csv_rows(r.content):
                rows.append(
                    _row(
                        item,
                        trade_date=_parse_date(item.get("Date")),
                        exchange="NSE",
                        symbol=item.get("Symbol"),
                        company_name=item.get("Security Name"),
                        deal_type="BULK",
                        buy_sell=item.get("Buy/Sell"),
                        client_name=item.get("Client Name"),
                        quantity=_f(item.get("Quantity Traded")),
                        price=_f(item.get("Trade Price / Wght. Avg. Price")),
                        source="NSE",
                        source_url=url,
                    )
                )
        elif r.status_code >= 400:
            errors.append(f"NSE bulk archive HTTP {r.status_code}")
    try:
        for item in _nse_hist_csv(http, "bulk_deals", start, end):
            ok = True
            rows.append(
                _row(
                    item,
                    trade_date=_parse_date(item.get("Date")),
                    exchange="NSE",
                    symbol=item.get("Symbol"),
                    company_name=item.get("Security Name"),
                    deal_type="BULK",
                    buy_sell=item.get("Buy / Sell") or item.get("Buy/Sell"),
                    client_name=item.get("Client Name"),
                    quantity=_f(item.get("Quantity Traded")),
                    price=_f(item.get("Trade Price / Wght. Avg. Price")),
                    source="NSE",
                    source_url=NSE_LARGE_DEAL_HIST,
                )
            )
    except Exception as exc:
        errors.append(str(exc))
    return _finish_nse(rows, ok, errors, "NSE Bulk", start, end)


def fetch_nse_block(http: Http, start: date, end: date) -> list[dict]:
    rows = []
    errors = []
    ok = False
    try:
        snap = http.nse_json(NSE_LARGE_DEAL_SNAP)
        ok = True
        for item in snap.get("BLOCK_DEALS_DATA") or []:
            if isinstance(item, dict):
                rows.append(
                    _row(
                        item,
                        trade_date=_parse_date(item.get("date")),
                        exchange="NSE",
                        symbol=item.get("symbol"),
                        company_name=item.get("name"),
                        deal_type="BLOCK",
                        buy_sell=item.get("buySell"),
                        client_name=item.get("clientName"),
                        quantity=_f(item.get("qty")),
                        price=_f(item.get("watp")),
                        source="NSE",
                        source_url=NSE_LARGE_DEAL_SNAP,
                    )
                )
    except Exception as exc:
        errors.append(str(exc))
    r = http.get(NSE_BLOCK_CSV, headers={"Referer": "https://www.nseindia.com/"})
    if r.status_code == 200 and r.content:
        ok = True
        for item in _csv_rows(r.content):
            rows.append(
                _row(
                    item,
                    trade_date=_parse_date(item.get("Date")),
                    exchange="NSE",
                    symbol=item.get("Symbol"),
                    company_name=item.get("Security Name"),
                    deal_type="BLOCK",
                    buy_sell=item.get("Buy/Sell"),
                    client_name=item.get("Client Name"),
                    quantity=_f(item.get("Quantity Traded")),
                    price=_f(item.get("Trade Price / Wght. Avg. Price")),
                    source="NSE",
                    source_url=NSE_BLOCK_CSV,
                )
            )
    elif r.status_code >= 400:
        errors.append(f"NSE block archive HTTP {r.status_code}")
    try:
        for item in _nse_hist_csv(http, "block_deals", start, end):
            ok = True
            rows.append(
                _row(
                    item,
                    trade_date=_parse_date(item.get("Date")),
                    exchange="NSE",
                    symbol=item.get("Symbol"),
                    company_name=item.get("Security Name"),
                    deal_type="BLOCK",
                    buy_sell=item.get("Buy / Sell") or item.get("Buy/Sell"),
                    client_name=item.get("Client Name"),
                    quantity=_f(item.get("Quantity Traded")),
                    price=_f(item.get("Trade Price / Wght. Avg. Price")),
                    source="NSE",
                    source_url=NSE_LARGE_DEAL_HIST,
                )
            )
    except Exception as exc:
        errors.append(str(exc))
    return _finish_nse(rows, ok, errors, "NSE Block", start, end)


def fetch_nse_short(http: Http, start: date, end: date) -> list[dict]:
    rows = []
    errors = []
    ok = False
    try:
        snap = http.nse_json(NSE_LARGE_DEAL_SNAP)
        ok = True
        for item in snap.get("SHORT_DEALS_DATA") or []:
            if isinstance(item, dict):
                rows.append(
                    _row(
                        item,
                        trade_date=_parse_date(item.get("date")),
                        exchange="NSE",
                        symbol=item.get("symbol"),
                        company_name=item.get("name"),
                        deal_type="SHORT_SELLING",
                        buy_sell="SELL",
                        client_name=item.get("clientName"),
                        quantity=_f(item.get("qty")),
                        price=_f(item.get("watp")),
                        source="NSE",
                        source_url=NSE_LARGE_DEAL_SNAP,
                    )
                )
    except Exception as exc:
        errors.append(str(exc))
    r = http.get(NSE_SHORT_CSV, headers={"Referer": "https://www.nseindia.com/"})
    if r.status_code == 200 and r.content:
        ok = True
        for item in _csv_rows(r.content):
            rows.append(
                _row(
                    item,
                    trade_date=_parse_date(item.get("Trade Date") or item.get("Date")),
                    exchange="NSE",
                    symbol=item.get("Symbol Name") or item.get("Symbol"),
                    company_name=item.get("Security Name"),
                    deal_type="SHORT_SELLING",
                    buy_sell="SELL",
                    quantity=_f(item.get("Quantity")),
                    price=None,
                    source="NSE",
                    source_url=NSE_SHORT_CSV,
                )
            )
    elif r.status_code >= 400:
        errors.append(f"NSE short-selling archive HTTP {r.status_code}")
    try:
        for item in _nse_hist_csv(http, "short_selling", start, end):
            ok = True
            rows.append(
                _row(
                    item,
                    trade_date=_parse_date(item.get("Date")),
                    exchange="NSE",
                    symbol=item.get("Symbol"),
                    company_name=item.get("Security Name"),
                    deal_type="SHORT_SELLING",
                    buy_sell="SELL",
                    quantity=_f(item.get("Quantity")),
                    price=None,
                    source="NSE",
                    source_url=NSE_LARGE_DEAL_HIST,
                )
            )
    except Exception as exc:
        errors.append(str(exc))
    return _finish_nse(rows, ok, errors, "NSE Short Selling", start, end)


def _dedupe_raw(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for rec in rows:
        key = (
            rec.get("trade_date"),
            rec.get("exchange"),
            rec.get("symbol"),
            rec.get("deal_type"),
            rec.get("buy_sell"),
            rec.get("client_name"),
            rec.get("quantity"),
            rec.get("price"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def _filter_dates(rows: list[dict], start: date, end: date) -> list[dict]:
    lo, hi = start.isoformat(), end.isoformat()
    return [r for r in rows if r.get("trade_date") and lo <= r["trade_date"] <= hi]


def _finish_nse(rows: list[dict], ok: bool, errors: list[str], label: str, start: date, end: date) -> list[dict]:
    out = _filter_dates(_dedupe_raw(rows), start, end)
    if ok:
        return out
    detail = "; ".join(errors[:3]) or "endpoint unavailable"
    raise RuntimeError(f"{label} unavailable. {detail}. No records were inserted.")


def _parse_bse_table(html: bytes, table_id: str, deal_type: str, source_url: str) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(html, "lxml")
    as_on = None
    blob = soup.get_text(" ", strip=True)
    m = re.search(r"As on\s+(\d{1,2}\s+\w+\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", blob, re.I)
    if m:
        as_on = _parse_date(m.group(1))
    table = soup.find("table", id=table_id)
    if not table:
        raise RuntimeError(f"BSE table {table_id} not found")
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        if len(cells) < 7:
            continue
        date_s, code, name, client, side, qty, price = cells[:7]
        rows.append(
            _row(
                {"cells": cells, "scrip_code": code},
                trade_date=_parse_date(date_s),
                exchange="BSE",
                symbol=name or code,
                company_name=name,
                deal_type=deal_type,
                buy_sell=side,
                client_name=client,
                quantity=_f(qty),
                price=_f(price),
                source="BSE",
                source_url=source_url,
            )
        )
    return rows, as_on


def fetch_bse_bulk(http: Http, start: date, end: date) -> list[dict]:
    http.get(BSE_HOME, headers={"Accept": "text/html"})
    r = http.get(BSE_BULK_PAGE, headers={"Referer": BSE_HOME, "Accept": "text/html"})
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"BSE bulk page HTTP {r.status_code}")
    rows, as_on = _parse_bse_table(r.content, "ContentPlaceHolder1_gvbulk_deals", "BULK", BSE_BULK_PAGE)
    return _filter_dates(rows, start, end)


def fetch_bse_block(http: Http, start: date, end: date) -> list[dict]:
    http.get(BSE_HOME, headers={"Accept": "text/html"})
    r = http.get(BSE_BLOCK_PAGE, headers={"Referer": BSE_HOME, "Accept": "text/html"})
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"BSE block page HTTP {r.status_code}")
    rows, as_on = _parse_bse_table(r.content, "ContentPlaceHolder1_gvblock_deals", "BLOCK", BSE_BLOCK_PAGE)
    return _filter_dates(rows, start, end)


def refresh_index_members(http: Http, conn) -> int:
    by_symbol: dict[str, dict] = {}
    order = {name: i for i, name in enumerate(_SECTOR_LOAD_ORDER)}
    specs = sorted(SECTORS, key=lambda s: order.get(s["name"], 99))
    for spec in specs:
        url = f"{NSE_INDEX_LIST}/{spec['list']}"
        r = http.get(url, headers={"Referer": "https://www.nseindia.com/"})
        if r.status_code != 200 or not r.content:
            continue
        for item in _csv_rows(r.content):
            symbol = _text(item.get("Symbol") or item.get("SYMBOL")).upper()
            if not symbol:
                continue
            if symbol in by_symbol:
                continue
            by_symbol[symbol] = {
                "symbol": symbol,
                "company_name": _text(item.get("Company Name") or item.get("Company")),
                "isin": _text(item.get("ISIN Code") or item.get("ISIN")),
                "sector": spec["name"],
                "source": "NSE",
                "source_url": url,
                "updated_at": now_iso(),
            }
        time.sleep(0.35)
    for rec in by_symbol.values():
        upsert(conn, "nse_index_members", rec, "symbol")
    conn.commit()
    conn.execute(
        """
        UPDATE large_deals d
        SET sector = m.sector
        FROM nse_index_members m
        WHERE (d.sector IS NULL OR d.sector = '')
          AND (
            d.symbol = m.symbol
            OR UPPER(TRIM(COALESCE(d.company_name, ''))) = UPPER(TRIM(COALESCE(m.company_name, '')))
          )
          AND m.company_name IS NOT NULL
          AND m.company_name <> ''
        """
    )
    conn.commit()
    return len(by_symbol)


def store_deals(conn, recs: list[dict]) -> tuple[int, int, int, list[str]]:
    valid, invalid_notes = [], []
    for rec in recs:
        reason = validate(rec)
        if reason:
            invalid_notes.append(f"{rec.get('symbol') or rec.get('company_name')}: {reason}")
            continue
        valid.append(_prepare(rec))
    inserted = insert_ignore_count(conn, "large_deals", valid, DEAL_CONFLICT)
    conn.commit()
    duplicates = len(valid) - inserted
    return inserted, duplicates, len(invalid_notes), invalid_notes[:8]


def _wanted(exchange: str, deal_type: str, ex_filter: str, type_filter: str) -> bool:
    if ex_filter not in ("ALL", "", None) and exchange != ex_filter:
        return False
    if type_filter not in ("ALL", "", None) and deal_type != type_filter:
        return False
    return True


def run_deal_fetch(
    start: date | None = None,
    end: date | None = None,
    exchange: str = "ALL",
    deal_type: str = "ALL",
):
    if not LOCK.acquire(blocking=False):
        yield {"type": "error", "text": "A deal fetch is already running"}
        return
    try:
        yield from _run_deal_fetch(start, end, exchange, deal_type)
    finally:
        LOCK.release()


def _log_step(conn, started, requested, exchange, deal_type, fetched, inserted, dupes, invalid, status, error=None):
    conn.execute(
        """
        INSERT INTO deal_fetch_logs (
            run_date, requested_date, exchange, deal_type, started_at, completed_at,
            status, records_fetched, records_inserted, duplicates, invalid_records, error_message
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            today_ist().isoformat(),
            requested.isoformat() if requested else None,
            exchange,
            deal_type,
            started,
            datetime.now(IST).replace(tzinfo=None),
            status,
            fetched,
            inserted,
            dupes,
            invalid,
            error,
        ),
    )
    conn.commit()


def _run_deal_fetch(start, end, exchange, deal_type):
    init_db()
    conn = connect()
    http = Http()
    today = today_ist()
    start = start or today
    end = end or today
    if end < start:
        yield {"type": "error", "text": "To date is before from date"}
        conn.close()
        return
    exchange = (exchange or "ALL").upper()
    deal_type = (deal_type or "ALL").upper()
    if deal_type in ("SHORT", "SHORT SELLING"):
        deal_type = "SHORT_SELLING"
    jobs = [
        ("NSE", "BULK", "Fetching NSE Bulk Deals...", fetch_nse_bulk),
        ("NSE", "BLOCK", "Fetching NSE Block Deals...", fetch_nse_block),
        ("NSE", "SHORT_SELLING", "Fetching NSE Short Selling...", fetch_nse_short),
        ("BSE", "BULK", "Fetching BSE Bulk Deals...", fetch_bse_bulk),
        ("BSE", "BLOCK", "Fetching BSE Block Deals...", fetch_bse_block),
    ]
    totals = {"fetched": 0, "inserted": 0, "duplicates": 0, "invalid": 0}
    steps = []
    try:
        yield {"type": "progress", "text": "Refreshing NSE index membership for sector join…"}
        refresh_index_members(http, conn)
    except Exception as exc:
        yield {"type": "progress", "text": f"Sector map skipped: {exc}"}

    yield {"type": "progress", "text": "Normalizing and saving exchange records…"}
    for ex, kind, label, fn in jobs:
        if not _wanted(ex, kind, exchange, deal_type):
            continue
        started = datetime.now(IST).replace(tzinfo=None)
        yield {"type": "step", "key": f"{ex}_{kind}", "label": label, "ok": None}
        try:
            recs = fn(http, start, end)
            time.sleep(0.8)
            yield {"type": "progress", "text": f"Saving {len(recs)} {ex} {kind} records…"}
            inserted, dupes, invalid, notes = store_deals(conn, recs)
            _log_step(conn, started, start, ex, kind, len(recs), inserted, dupes, invalid, "SUCCESS")
            totals["fetched"] += len(recs)
            totals["inserted"] += inserted
            totals["duplicates"] += dupes
            totals["invalid"] += invalid
            extra = f" · {notes[0]}" if notes else ""
            yield {
                "type": "step",
                "key": f"{ex}_{kind}",
                "label": label,
                "ok": True,
                "fetched": len(recs),
                "inserted": inserted,
                "duplicates": dupes,
                "invalid": invalid,
                "text": f"{label} ✓  fetched {len(recs)} inserted {inserted} dup {dupes} invalid {invalid}{extra}",
            }
            steps.append({"exchange": ex, "deal_type": kind, "ok": True})
        except Exception as exc:
            _log_step(conn, started, start, ex, kind, 0, 0, 0, 0, "FAILED", str(exc)[:500])
            yield {
                "type": "step",
                "key": f"{ex}_{kind}",
                "label": label,
                "ok": False,
                "error": str(exc),
                "text": f"{label} ✗  {exc}",
            }
            steps.append({"exchange": ex, "deal_type": kind, "ok": False, "error": str(exc)})
    conn.close()
    nse_ok = any(s["ok"] for s in steps if s["exchange"] == "NSE") if any(s["exchange"] == "NSE" for s in steps) else None
    bse_ok = any(s["ok"] for s in steps if s["exchange"] == "BSE") if any(s["exchange"] == "BSE" for s in steps) else None
    yield {
        "type": "done",
        "text": "Completed",
        "fetched": totals["fetched"],
        "inserted": totals["inserted"],
        "duplicates": totals["duplicates"],
        "invalid": totals["invalid"],
        "nse": "Success" if nse_ok else ("Failed" if nse_ok is False else "Skipped"),
        "bse": "Success" if bse_ok else ("Failed" if bse_ok is False else "Skipped"),
        "last_updated": now_iso(),
        "steps": steps,
    }


def start_daily_scheduler() -> None:
    def loop():
        while True:
            now = datetime.now(IST)
            target = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            time.sleep(max(30.0, (target - datetime.now(IST)).total_seconds()))
            if datetime.now(IST).weekday() >= 5:
                continue
            for _ in run_deal_fetch():
                pass

    Thread(target=loop, name="deal-scheduler", daemon=True).start()


def fetch_deals_sync(start: date | None = None, end: date | None = None, exchange: str = "ALL", deal_type: str = "ALL") -> dict:
    last = {"type": "error", "text": "No result"}
    for event in run_deal_fetch(start, end, exchange, deal_type):
        last = event
    return last


CAP_LOCK = Lock()
CAP_STALE = timedelta(hours=12)


def ingest_nse_fo_market_caps(http: Http, conn) -> int:
    data = http.nse_json(NSE_PREOPEN_FO)
    rows = data.get("data") if isinstance(data, dict) else []
    as_of = datetime.now(IST).replace(tzinfo=None)
    n = 0
    for row in rows or []:
        md = row.get("metadata") or {}
        symbol = (md.get("symbol") or "").strip().upper()
        cap = _f(md.get("marketCap"))
        price = _f(md.get("lastPrice"))
        if not symbol or cap is None or cap <= 0:
            continue
        upsert(
            conn,
            "stock_market_cap",
            {
                "symbol": symbol,
                "company_name": None,
                "last_price": price,
                "issued_size": None,
                "market_cap": cap,
                "source": "NSE pre-open F&O",
                "as_of": as_of,
                "updated_at": now_iso(),
            },
            "symbol",
            replace=True,
        )
        n += 1
    if n:
        conn.commit()
    return n


def fetch_nse_market_cap(http: Http, symbol: str) -> dict | None:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return None
    data = http.nse_json(f"{NSE_QUOTE_EQUITY}?symbol={quote(symbol, safe='')}")
    if not isinstance(data, dict):
        return None
    price = _f((data.get("priceInfo") or {}).get("lastPrice"))
    issued = _f((data.get("securityInfo") or {}).get("issuedSize"))
    name = (data.get("info") or {}).get("companyName")
    if price is None or issued is None or issued <= 0:
        return None
    return {
        "symbol": symbol,
        "company_name": name,
        "last_price": price,
        "issued_size": issued,
        "market_cap": price * issued,
        "source": "NSE quote-equity",
        "as_of": datetime.now(IST).replace(tzinfo=None),
        "updated_at": now_iso(),
    }


def _cap_stale(row: dict | None) -> bool:
    if not row or row.get("market_cap") is None:
        return True
    as_of = row.get("as_of") or row.get("updated_at")
    if not as_of:
        return True
    if isinstance(as_of, str):
        try:
            as_of = datetime.fromisoformat(as_of[:19])
        except ValueError:
            return True
    if getattr(as_of, "tzinfo", None):
        as_of = as_of.replace(tzinfo=None)
    return datetime.now(IST).replace(tzinfo=None) - as_of > CAP_STALE


def ensure_market_cap(symbol: str) -> dict | None:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return None
    init_db()
    conn = connect()
    row = conn.execute("SELECT * FROM stock_market_cap WHERE symbol=?", (symbol,)).fetchone()
    stale = _cap_stale(dict(row) if row else None)
    conn.close()
    if stale:
        start_cap_refresh([symbol])
    return dict(row) if row else None


def refresh_market_caps(symbols: list[str], limit: int = 20) -> None:
    if not CAP_LOCK.acquire(blocking=False):
        return
    try:
        init_db()
        conn = connect()
        http = Http()
        try:
            ingest_nse_fo_market_caps(http, conn)
        except Exception:
            pass
        conn.close()
    finally:
        CAP_LOCK.release()


def start_cap_refresh(symbols: list[str]) -> None:
    if not symbols:
        return
    Thread(target=refresh_market_caps, args=(symbols,), name="deal-caps", daemon=True).start()
