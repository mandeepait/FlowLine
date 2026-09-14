import calendar
import re
from datetime import datetime
from io import BytesIO

import xlrd
from bs4 import BeautifulSoup
from pypdf import PdfReader

from config import AMFI_MONTH, AMFI_MONTHLY_NOTE, AMFI_SIP_PAGE, AMFI_XLS
from db import has_row, now_iso, upsert
from nsdl import parse_num

_NOTE_MONTH = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)[_\-]?(\d{4})",
    re.I,
)
_NOTE_MONTH_NUM = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
_CRORE = r"Rs\.?\s*([\d,\s]+(?:\.\d+)?)\s*crore"
_DII = r"(?:Domestic institutional investors(?:\s*\(\s*DIIs?\s*\))?|DIIs?)"
_DII_POS = [
    re.compile(_DII + r"[^.]{0,120}?equity purchases rising to\s+" + _CRORE, re.I),
    re.compile(
        _DII + r"[^.]{0,80}?(?:bought|acquired|acquiring|buying|purchased)\s+equities\s+worth\s+" + _CRORE,
        re.I,
    ),
]
_DII_NEG = [
    re.compile(_DII + r"[^.]{0,80}?(?:sold|were net sellers)[^.]{0,60}?" + _CRORE, re.I),
]


def scrape_amfi_month(http, conn, month: str) -> dict | None:
    if has_row(conn, "SELECT 1 FROM mutual_fund_flows WHERE month=? AND status='FINAL'", (month,)):
        return conn.execute("SELECT * FROM mutual_fund_flows WHERE month=?", (month,)).fetchone()
    year, mon = month.split("-")
    code = AMFI_MONTH[int(mon) - 1]
    url = AMFI_XLS.format(mon=code, year=year)
    r = http.get(url)
    if r.status_code != 200 or not r.content:
        return None
    if r.content[:4] != b"\xd0\xcf\x11\xe0" and b"<html" in r.content[:200].lower():
        return None
    parsed = parse_amfi_xls(r.content)
    if not parsed:
        return None
    sip = scrape_sip(http, month)
    rec = {
        "month": month,
        "as_of_date": parsed.get("as_of_date") or f"{month}-28",
        "equity_inflow": parsed.get("equity_inflow"),
        "equity_outflow": parsed.get("equity_outflow"),
        "equity_net": parsed.get("equity_net"),
        "sip_contribution": sip,
        "equity_aum": parsed.get("equity_aum"),
        "large_cap_net": parsed.get("large_cap_net"),
        "mid_cap_net": parsed.get("mid_cap_net"),
        "small_cap_net": parsed.get("small_cap_net"),
        "etf_net": parsed.get("etf_net"),
        "source": "AMFI",
        "source_url": url,
        "scraped_at": now_iso(),
        "status": "FINAL",
    }
    upsert(conn, "mutual_fund_flows", rec, "month")
    conn.commit()
    return rec


def scrape_dii_monthly(http, conn, months: list[str], current: str) -> list[dict]:
    """Official monthly DII equity net from AMFI Monthly Notes. Never use the
    NSE one-session cash tape as the month."""
    conn.execute(
        "DELETE FROM institutional_flows WHERE category='DII' AND (source IS NULL OR source<>'AMFI')"
    )
    conn.commit()
    links = _amfi_note_links(http)
    saved = []
    for month in months:
        existing = conn.execute(
            "SELECT net_flow, status, source FROM institutional_flows WHERE month=? AND category='DII'",
            (month,),
        ).fetchone()
        if (
            existing
            and existing["source"] == "AMFI"
            and existing["status"] == "FINAL"
            and existing["net_flow"] is not None
            and month != current
        ):
            continue
        url = links.get(month)
        if not url:
            continue
        rec = _store_amfi_dii(http, conn, month, url)
        if rec:
            saved.append(rec)
    conn.commit()
    return saved


def parse_dii_net_from_note(text: str) -> float | None:
    body = re.sub(r"\s+", " ", text or "")
    for pat in _DII_NEG:
        m = pat.search(body)
        if m:
            val = _parse_amfi_crore(m.group(1))
            if val is not None:
                return -abs(val)
    for pat in _DII_POS:
        m = pat.search(body)
        if m:
            val = _parse_amfi_crore(m.group(1))
            if val is not None:
                return val
    return None


def _amfi_note_links(http) -> dict[str, str]:
    r = http.get(AMFI_MONTHLY_NOTE)
    if r.status_code != 200:
        raise RuntimeError(f"AMFI monthly note listing HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ".pdf" not in href.lower():
            continue
        if href.startswith("/"):
            href = "https://www.amfiindia.com" + href
        elif not href.startswith("http"):
            href = "https://www.amfiindia.com/" + href.lstrip("/")
        month = _month_from_note_label(href) or _month_from_note_label(a.get_text(" ", strip=True))
        if month:
            out[month] = href
    return out


def _month_from_note_label(text: str) -> str | None:
    m = _NOTE_MONTH.search(text or "")
    if not m:
        return None
    name = m.group(1).strip().lower()
    if name.startswith("sept") and name != "september":
        name = "sept"
    num = _NOTE_MONTH_NUM.get(name)
    if not num:
        return None
    return f"{int(m.group(2)):04d}-{num:02d}"


def _store_amfi_dii(http, conn, month: str, url: str) -> dict | None:
    r = http.get(url)
    if r.status_code != 200 or not r.content:
        return None
    net = parse_dii_net_from_note(_pdf_text(r.content))
    if net is None:
        return None
    year, mon = [int(x) for x in month.split("-")]
    rec = {
        "month": month,
        "as_of_date": f"{month}-{calendar.monthrange(year, mon)[1]:02d}",
        "category": "DII",
        "buy_value": None,
        "sell_value": None,
        "net_flow": net,
        "source": "AMFI",
        "source_url": url,
        "scraped_at": now_iso(),
        "status": "FINAL",
    }
    upsert(conn, "institutional_flows", rec, "month, category")
    return rec


def _pdf_text(content: bytes) -> str:
    pages = []
    for page in PdfReader(BytesIO(content)).pages:
        pages.append(page.extract_text() or "")
    return " ".join(pages)


def _parse_amfi_crore(raw: str) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").replace(" ", "").replace("\xa0", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_amfi_xls(content: bytes) -> dict:
    book = xlrd.open_workbook(file_contents=content, formatting_info=False)
    as_of = None
    found = {}
    for sheet in book.sheets():
        grid = []
        for r in range(sheet.nrows):
            row = [ _xls_cell(sheet, r, c) for c in range(sheet.ncols) ]
            grid.append(row)
            blob = " ".join(x for x in row if x)
            m = re.search(r"as on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", blob, re.I)
            if m:
                as_of = _parse_amfi_date(m.group(1))
            m = re.search(r"month of\s+([A-Za-z]+)\s+(\d{4})", blob, re.I)
            if m and not as_of:
                as_of = None
        headers_idx = None
        for i, row in enumerate(grid):
            joined = " ".join(row).lower()
            if "funds mobilized" in joined and ("net inflow" in joined or "repurchase" in joined):
                headers_idx = i
                break
        if headers_idx is None:
            continue
        header = [h.lower() for h in grid[headers_idx]]
        col = {
            "in": _col(header, "funds mobilized"),
            "out": _col(header, "repurchase") or _col(header, "redemption"),
            "net": _col(header, "net inflow"),
            "aum": _col(header, "net assets") or _col(header, "assets under"),
        }
        for row in grid[headers_idx + 1 :]:
            label = " ".join(x for x in row[:4] if x).lower()
            label = re.sub(r"\s+", " ", label).strip()
            if "equity_net" not in found and re.search(r"sub total -\s*ii\b", label) and not re.search(r"sub total -\s*iii\b", label):
                found["equity_inflow"] = _row_num(row, col["in"])
                found["equity_outflow"] = _row_num(row, col["out"])
                found["equity_net"] = _row_num(row, col["net"])
                found["equity_aum"] = _row_num(row, col["aum"])
            if re.search(r"\blarge cap fund\b", label) and "large & mid" not in label:
                found["large_cap_net"] = _row_num(row, col["net"])
            if re.search(r"\bmid cap fund\b", label) and "large & mid" not in label:
                found["mid_cap_net"] = _row_num(row, col["net"])
            if re.search(r"\bsmall cap fund\b", label):
                found["small_cap_net"] = _row_num(row, col["net"])
            if "equity etf" in label and "overseas" not in label:
                found["etf_net"] = _row_num(row, col["net"])
    if as_of:
        found["as_of_date"] = as_of
    return found


def scrape_sip(http, month: str) -> float | None:
    r = http.get(AMFI_SIP_PAGE)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    target = datetime.strptime(month, "%Y-%m")
    keys = {
        target.strftime("%b-%y").lower(),
        target.strftime("%b-%Y").lower(),
        target.strftime("%B-%y").lower(),
        re.sub(r"\s+", "", target.strftime("%b -%y")).lower(),
        f"{target.strftime('%b').lower()}-{target.strftime('%y')}",
        f"{target.strftime('%B').lower()}-{target.strftime('%y')}",
    }
    # August 2026 -> aug-26, july -26, etc.
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if not rows:
            continue
        header = [h.lower() for h in rows[0]]
        contrib = None
        for i, h in enumerate(header):
            if "sip contribution" in h:
                contrib = i
        if contrib is None:
            continue
        for cells in rows[1:]:
            head = re.sub(r"\s+", "", cells[0].lower())
            if any(k.replace(" ", "") in head or head.startswith(k.replace(" ", "")) for k in keys):
                if contrib < len(cells):
                    val = parse_num(cells[contrib])
                    if val is not None:
                        return val
    return None


def _xls_cell(sheet, r, c) -> str:
    val = sheet.cell_value(r, c)
    ctype = sheet.cell_type(r, c)
    if ctype == xlrd.XL_CELL_DATE:
        try:
            dt = xlrd.xldate_as_datetime(val, sheet.book.datemode)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return str(val)
    if isinstance(val, float):
        if val == int(val):
            return str(int(val))
        return str(val)
    return str(val).strip()


def _col(header: list[str], needle: str) -> int | None:
    for i, h in enumerate(header):
        if needle in h:
            return i
    return None


def _row_num(row: list[str], idx: int | None) -> float | None:
    if idx is None or idx >= len(row):
        return None
    return parse_num(row[idx])


def _parse_amfi_date(text: str) -> str | None:
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None
