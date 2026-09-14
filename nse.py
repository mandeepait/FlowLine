import csv
import io
import re
from datetime import date, datetime, timedelta

from config import IST, NSE_ARCHIVES, NSE_FII_DII, TRACKED_INDEXES, symbol_for_index
from db import has_row, insert_many, now_iso, upsert

INDEX_ALIASES = {
    "nifty 50": "Nifty 50",
    "nifty50": "Nifty 50",
    "nifty 500": "Nifty 500",
    "nifty500": "Nifty 500",
    "nifty bank": "Nifty Bank",
    "nifty financial services": "Nifty Financial Services",
    "nifty auto": "Nifty Auto",
    "nifty fmcg": "Nifty FMCG",
    "nifty it": "Nifty IT",
    "nifty pharma": "Nifty Pharma",
    "nifty metal": "Nifty Metal",
    "nifty realty": "Nifty Realty",
    "nifty media": "Nifty Media",
    "nifty energy": "Nifty Energy",
    "nifty healthcare": "Nifty Healthcare",
    "nifty healthcare index": "Nifty Healthcare",
    "nifty consumer durables": "Nifty Consumer Durables",
    "nifty oil & gas": "Nifty Oil & Gas",
    "nifty oil and gas": "Nifty Oil & Gas",
    "nifty psu bank": "Nifty PSU Bank",
    "nifty private bank": "Nifty Private Bank",
    "nifty infra": "Nifty Infra",
    "nifty infrastructure": "Nifty Infra",
    "nifty commodities": "Nifty Commodities",
    "nifty consumption": "Nifty Consumption",
    "nifty india consumption": "Nifty Consumption",
}


def _norm_index(name: str) -> str:
    key = re.sub(r"\s+", " ", (name or "").strip().lower())
    return INDEX_ALIASES.get(key, name.strip())


def _today() -> date:
    return datetime.now(IST).date()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def ingest_index_close(http, conn, day: date) -> bool:
    iso = day.isoformat()
    refresh = day == _today()
    if not refresh and has_row(
        conn, "SELECT 1 FROM daily_indices WHERE trade_date=? LIMIT 1", (iso,)
    ):
        return False
    url = f"{NSE_ARCHIVES}/content/indices/ind_close_all_{day.strftime('%d%m%Y')}.csv"
    r = http.get(url, headers={"Referer": "https://www.nseindia.com/"})
    if r.status_code != 200 or not r.content or b"Index Name" not in r.content[:200]:
        return False
    text = r.content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    batch = []
    for row in reader:
        name = _norm_index(row.get("Index Name") or "")
        close = _f(row.get("Closing Index Value"))
        if not name or close is None or name not in TRACKED_INDEXES:
            continue
        batch.append(
            {
                "trade_date": iso,
                "index_name": name,
                "symbol": symbol_for_index(name),
                "close": close,
                "volume": _f(row.get("Volume")),
                "turnover": _f(row.get("Turnover (Rs. Cr.)")),
            }
        )
    insert_many(conn, "daily_indices", batch, "trade_date, index_name", replace=refresh)
    return True


def sync_market_files(http, conn, start: date, end: date):
    got_idx = skipped = 0
    for day in daterange(start, end):
        if day.weekday() >= 5:
            continue
        iso = day.isoformat()
        if day != _today() and has_row(
            conn, "SELECT 1 FROM daily_indices WHERE trade_date=? LIMIT 1", (iso,)
        ):
            skipped += 1
            continue
        if ingest_index_close(http, conn, day):
            got_idx += 1
        if got_idx and got_idx % 15 == 0:
            yield {
                "type": "log",
                "text": f"Index files through {day.isoformat()} ({got_idx} new days)",
            }
            conn.commit()
    conn.commit()
    yield {
        "type": "log",
        "text": f"Stored {got_idx} index days; skipped {skipped} days already in DB",
    }


def scrape_fii_dii_daily(http, conn) -> list[dict]:
    """NSE cash-market daily activity. Store every category day-wise (DII and
    FII cash tape). Monthly DII on the UI comes from AMFI notes, not this tape.
    Official monthly FPI still comes from NSDL, never summed from NSE."""
    payload = http.nse_json(NSE_FII_DII)
    rows = payload if isinstance(payload, list) else payload.get("data") or []
    saved = []
    for item in rows:
        cat = (item.get("category") or "").upper()
        if "DII" in cat:
            category = "DII"
        elif "FII" in cat or "FPI" in cat:
            category = "FII"
        else:
            continue
        trade_date = _parse_nse_date(item.get("date"))
        if not trade_date:
            continue
        rec = {
            "trade_date": trade_date,
            "category": category,
            "buy_value": _f(item.get("buyValue")),
            "sell_value": _f(item.get("sellValue")),
            "net_flow": _f(item.get("netValue")),
            "source": "NSE",
            "source_url": NSE_FII_DII,
            "scraped_at": now_iso(),
        }
        is_today = trade_date == _today().isoformat()
        if not is_today and has_row(
            conn,
            "SELECT 1 FROM institutional_flow_daily WHERE trade_date=? AND category=?",
            (trade_date, category),
        ):
            continue
        upsert(conn, "institutional_flow_daily", rec, "trade_date, category", replace=is_today)
        saved.append(rec)
    conn.commit()
    return saved


def _f(val):
    if val is None or val == "" or val == "-":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").replace("₹", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _parse_nse_date(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None
