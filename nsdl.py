import re
from datetime import datetime
from html import unescape

from bs4 import BeautifulSoup

from config import NSDL_FORTNIGHTLY, NSDL_MONTHLY, NSDL_STATIC, NSDL_YEARWISE
from db import has_row, now_iso, upsert

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], 1)}
MONTHS.update({m[:3].lower(): i for m, i in list(MONTHS.items())})
MONTHS["june"] = 6
MONTHS["july"] = 7


def parse_num(text) -> float | None:
    if text is None:
        return None
    s = unescape(str(text)).replace(",", "").replace("₹", "").strip()
    if s in ("", "-", "NA", "N/A"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def scrape_fpi_yearwise(http, conn, year: int) -> dict:
    r = http.get(NSDL_YEARWISE, headers={"Referer": "https://www.fpi.nsdl.co.in/"})
    if r.status_code != 200:
        raise RuntimeError(f"NSDL yearwise HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")
    html = r.text
    if year != datetime.utcnow().year:
        html = _aspnet_post(http, NSDL_YEARWISE, soup, {"ddl": str(year)})
        soup = BeautifulSoup(html, "lxml")
    table = _find_table_with(soup, "Equity")
    if table is None:
        raise RuntimeError("NSDL yearwise table not found")

    as_of = None
    m = re.search(r"up to\s+(\d{1,2}\s+\w+\s+\d{4})", soup.get_text(" ", strip=True), re.I)
    if m:
        as_of = _parse_long_date(m.group(1))

    saved = []
    for tr in table.find_all("tr"):
        cells = [_cell(c) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        month_no, partial = _month_from_label(cells[0])
        if not month_no:
            continue
        equity_net = parse_num(cells[1] if len(cells) > 1 else None)
        if equity_net is None:
            continue
        month = f"{year:04d}-{month_no:02d}"
        existing = conn.execute(
            "SELECT buy_value, sell_value, net_flow, status FROM institutional_flows WHERE month=? AND category='FPI'",
            (month,),
        ).fetchone()
        if existing and existing["status"] == "FINAL" and existing["net_flow"] is not None:
            continue
        status = "PARTIAL" if partial else "FINAL"
        rec = {
            "month": month,
            "as_of_date": as_of or f"{month}-28",
            "category": "FPI",
            "buy_value": None,
            "sell_value": None,
            "net_flow": equity_net,
            "source": "NSDL",
            "source_url": NSDL_YEARWISE,
            "scraped_at": now_iso(),
            "status": status,
        }
        if existing:
            rec["buy_value"] = existing["buy_value"]
            rec["sell_value"] = existing["sell_value"]
        upsert(conn, "institutional_flows", rec, "month, category")
        saved.append(rec)
    conn.commit()
    return {"rows": saved, "as_of": as_of}


def scrape_fpi_monthly_buy_sell(http, conn) -> list[dict]:
    r = http.get(NSDL_MONTHLY, headers={"Referer": "https://www.fpi.nsdl.co.in/"})
    if r.status_code != 200:
        raise RuntimeError(f"NSDL monthly HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")
    rows = []
    current_date = None
    current_asset = None
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [_cell(c) for c in tr.find_all(["td", "th"])]
            if len(cells) < 5:
                continue
            if _looks_like_date(cells[0]):
                current_date = _parse_nsdl_date(cells[0])
                current_asset = cells[1]
                route = cells[2]
                buy, sell, net = parse_num(cells[3]), parse_num(cells[4]), parse_num(cells[5] if len(cells) > 5 else None)
            else:
                if cells[0] in ("Equity", "Debt", "Hybrid", "Mutual Funds", "AIFs", "Debt-General Limit", "Debt-VRR", "Debt-FAR"):
                    current_asset = cells[0]
                    route = cells[1] if len(cells) > 1 else ""
                    buy, sell, net = parse_num(cells[2] if len(cells) > 2 else None), parse_num(cells[3] if len(cells) > 3 else None), parse_num(cells[4] if len(cells) > 4 else None)
                else:
                    route = cells[0] or (cells[1] if len(cells) > 1 else "")
                    nums = [parse_num(c) for c in cells]
                    nums = [n for n in nums if n is not None]
                    buy = nums[0] if nums else None
                    sell = nums[1] if len(nums) > 1 else None
                    net = nums[2] if len(nums) > 2 else None
            if current_date and current_asset == "Equity" and re.search(r"sub[- ]total", route or "", re.I):
                if has_row(
                    conn,
                    "SELECT 1 FROM institutional_flow_daily WHERE trade_date=? AND category='FPI'",
                    (current_date,),
                ):
                    continue
                rec = {
                    "trade_date": current_date,
                    "category": "FPI",
                    "buy_value": buy,
                    "sell_value": sell,
                    "net_flow": net,
                    "source": "NSDL",
                    "source_url": NSDL_MONTHLY,
                    "scraped_at": now_iso(),
                }
                upsert(conn, "institutional_flow_daily", rec, "trade_date, category")
                rows.append(rec)
    conn.commit()
    _rollup_fpi_buy_sell(conn)
    return rows


def scrape_sector_fpi(http, conn, months: list[str], current_month: str, emit) -> dict:
    r = http.get(NSDL_FORTNIGHTLY, headers={"Referer": "https://www.fpi.nsdl.co.in/"})
    if r.status_code != 200:
        raise RuntimeError(f"NSDL fortnightly HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "lxml")
    select = soup.find("select", {"name": "ddlfortnighly"}) or soup.find("select", id="ddlfortnighly")
    if not select:
        raise RuntimeError("NSDL fortnightly dropdown missing")
    options = []
    for opt in select.find_all("option"):
        href = (opt.get("value") or "").strip()
        label = opt.get_text(" ", strip=True)
        fname = href.rsplit("/", 1)[-1]
        if not fname.endswith(".html"):
            continue
        period_end, month_key = _parse_fortnight_filename(fname, label)
        if month_key:
            options.append((month_key, period_end, fname, label))

    wanted = set(months)
    by_month: dict[str, list] = {}
    for month_key, period_end, fname, label in options:
        if month_key in wanted:
            by_month.setdefault(month_key, []).append((period_end, fname, label))

    saved = 0
    for month in months:
        if has_row(
            conn,
            """
            SELECT 1 FROM sector_fpi_flows
            WHERE month=? AND period_type='monthly' LIMIT 1
            """,
            (month,),
        ) and month != current_month:
            continue
        files = sorted(by_month.get(month, []), key=lambda x: x[0] or "")
        if not files:
            continue
        # Prefer month-end report which already has both fortnights
        end_report = files[-1]
        period_end, fname, label = end_report
        url = f"{NSDL_STATIC}/{fname}"
        page = http.get(url, headers={"Referer": NSDL_FORTNIGHTLY})
        if page.status_code != 200:
            continue
        sectors = parse_sector_table(page.text)
        status = "PARTIAL" if month == current_month else "FINAL"
        for name, equity_net in sectors.items():
            upsert(
                conn,
                "sector_fpi_flows",
                {
                    "month": month,
                    "sector": name,
                    "period_type": "monthly",
                    "period_end": period_end or month,
                    "equity_net": equity_net,
                    "source": "NSDL",
                    "source_url": url,
                    "scraped_at": now_iso(),
                    "status": status,
                },
                "month, sector, period_type, period_end",
                replace=(month == current_month),
            )
            saved += 1
        emit("log", f"Sector FPI {label}")
    conn.commit()
    return {"rows": saved}


def parse_sector_table(html: str) -> dict[str, float]:
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [_cell(c) for c in tr.find_all(["td", "th"])]
            if len(cells) < 10:
                continue
            if not re.match(r"^\d+$", cells[0] or ""):
                continue
            sector = cells[1]
            if not sector or sector.lower() in ("grand total", "total", "others", "sovereign"):
                if sector and sector.lower() == "others":
                    pass
                elif sector and sector.lower() in ("grand total", "total", "sovereign"):
                    continue
            nums = [parse_num(c) for c in cells[2:]]
            nums = [n for n in nums if n is not None]
            if len(nums) < 25:
                continue
            # numeric layout: 12 AUC INR, 12 AUC USD, 12 net1 INR, ...
            net1 = nums[24] if len(nums) > 24 else None
            net2 = nums[48] if len(nums) > 48 else None
            total = None
            if net1 is not None and net2 is not None:
                total = net1 + net2
            elif net1 is not None:
                total = net1
            if total is None:
                continue
            out[sector] = total
    return out


def _rollup_fpi_buy_sell(conn) -> None:
    rows = conn.execute(
        """
        SELECT substr(trade_date,1,7) AS month,
               MAX(trade_date) AS as_of,
               SUM(buy_value) AS buy_value,
               SUM(sell_value) AS sell_value,
               SUM(net_flow) AS net_flow
        FROM institutional_flow_daily
        WHERE category='FPI'
        GROUP BY substr(trade_date,1,7)
        """
    ).fetchall()
    for row in rows:
        existing = conn.execute(
            "SELECT net_flow, status, source, source_url FROM institutional_flows WHERE month=? AND category='FPI'",
            (row["month"],),
        ).fetchone()
        rec = {
            "month": row["month"],
            "as_of_date": row["as_of"],
            "category": "FPI",
            "buy_value": row["buy_value"],
            "sell_value": row["sell_value"],
            "net_flow": existing["net_flow"] if existing and existing["net_flow"] is not None else row["net_flow"],
            "source": "NSDL",
            "source_url": existing["source_url"] if existing else NSDL_MONTHLY,
            "scraped_at": now_iso(),
            "status": existing["status"] if existing else "PARTIAL",
        }
        upsert(conn, "institutional_flows", rec, "month, category")
    conn.commit()


def _aspnet_post(http, url, soup, extra: dict) -> str:
    payload = {}
    for inp in soup.find_all("input"):
        name = inp.get("name")
        if name:
            payload[name] = inp.get("value") or ""
    payload.update(extra)
    r = http.s.post(url, data=payload, headers={"Referer": url, "User-Agent": http.s.headers.get("User-Agent")}, timeout=40)
    r.raise_for_status()
    return r.text


def _find_table_with(soup, text: str):
    for table in soup.find_all("table"):
        if text.lower() in table.get_text(" ", strip=True).lower():
            return table
    return None


def _cell(c) -> str:
    return c.get_text(" ", strip=True).replace("\xa0", " ")


def _month_from_label(label: str) -> tuple[int | None, bool]:
    raw = (label or "").strip()
    partial = "**" in raw
    raw = raw.replace("*", "").strip()
    key = raw.lower()
    if key in MONTHS:
        return MONTHS[key], partial
    return None, partial


def _is_current_month_label(label: str) -> bool:
    return "**" in (label or "")


def _looks_like_date(text: str) -> bool:
    return bool(re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$", text or ""))


def _parse_nsdl_date(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _parse_long_date(text: str) -> str | None:
    text = re.sub(r"\s+", " ", text.strip())
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_fortnight_filename(fname: str, label: str) -> tuple[str | None, str | None]:
    m = re.search(
        r"FIIInvestSectou?r_([A-Za-z]+)(\d{1,2})(\d{4})\.html",
        fname,
        re.I,
    )
    if not m:
        return None, None
    mon_s, day_s, year_s = m.group(1), m.group(2), m.group(3)
    mon = MONTHS.get(mon_s.lower())
    if not mon:
        return None, None
    day = int(day_s)
    year = int(year_s)
    try:
        period_end = datetime(year, mon, min(day, 28)).date().isoformat()
        if day > 28:
            period_end = datetime(year, mon, day).date().isoformat()
    except ValueError:
        period_end = f"{year:04d}-{mon:02d}-{min(day, 28):02d}"
    return period_end, f"{year:04d}-{mon:02d}"
