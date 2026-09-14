from datetime import date, datetime, timedelta
from threading import Lock

from config import IST, PRICE_LOOKBACK_CAL_DAYS, START_MONTH
from db import connect, init_db, now_iso, set_status, should_skip, upsert
from net import Http
from nse import scrape_fii_dii_daily, sync_market_files
from nsdl import scrape_fpi_monthly_buy_sell, scrape_fpi_yearwise, scrape_sector_fpi
from amfi import scrape_amfi_month, scrape_dii_monthly
from compute import (
    compute_market_performance,
    compute_sectors,
    last_trading_day,
)

LOCK = Lock()
STEPS = [
    ("fpi", "FPI/FII"),
    ("dii", "DII"),
    ("mf", "Mutual Funds"),
    ("sector_fpi", "Sector Flows"),
    ("market_perf", "Market Performance"),
    ("sector_perf", "Sector Performance"),
    ("rs", "Relative Strength"),
]


def month_iter(start: str, end: date) -> list[str]:
    y, m = [int(x) for x in start.split("-")]
    out = []
    while date(y, m, 1) <= date(end.year, end.month, 1):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def month_label(month: str) -> str:
    dt = datetime.strptime(month, "%Y-%m")
    return dt.strftime("%B %Y")


def today_ist() -> date:
    return datetime.now(IST).date()


def run_update():
    if not LOCK.acquire(blocking=False):
        yield {"type": "error", "text": "Update already running"}
        return
    try:
        yield from _run()
    finally:
        LOCK.release()


def _run():
    init_db()
    conn = connect()
    http = Http()
    today = today_ist()
    current = f"{today.year:04d}-{today.month:02d}"
    months = month_iter(START_MONTH, today)
    errors = []
    hist_updated = hist_skipped = 0
    current_updated = False
    run_started = now_iso()

    def emit(kind, text=None, **extra):
        ev = {"type": kind}
        if text:
            ev["text"] = text
        ev.update(extra)
        return ev

    yield emit("log", "Checking existing data...")

    try:
        start = today - timedelta(days=PRICE_LOOKBACK_CAL_DAYS)
        yield emit("log", "Downloading NSE index files…")
        for ev in sync_market_files(http, conn, start, today):
            yield ev
    except Exception as exc:
        errors.append(f"Market files: {exc}")
        yield emit("log", f"Market files error: {exc}")

    # FPI yearwise once, then monthly buy/sell for current
    try:
        years = sorted({int(m[:4]) for m in months})
        for year in years:
            scrape_fpi_yearwise(http, conn, year)
        scrape_fpi_monthly_buy_sell(http, conn)
        yield emit("step", key="fpi", ok=True, label="FPI/FII")
    except Exception as exc:
        errors.append(f"FPI: {exc}")
        yield emit("step", key="fpi", ok=False, label="FPI/FII", error=str(exc))

    try:
        scrape_fii_dii_daily(http, conn)
        _rollup_fii_cash(conn, months, current)
        scrape_dii_monthly(http, conn, months, current)
        yield emit("step", key="dii", ok=True, label="DII")
    except Exception as exc:
        errors.append(f"DII: {exc}")
        yield emit("step", key="dii", ok=False, label="DII", error=str(exc))

    mf_ok = True
    try:
        for month in months:
            is_current = month == current
            if should_skip(conn, "mf", month, is_current):
                continue
            rec = scrape_amfi_month(http, conn, month)
            if rec:
                set_status(conn, "mf", month, status="FINAL", as_of_date=rec.get("as_of_date"), source="AMFI", source_url=rec.get("source_url"))
            elif is_current:
                set_status(conn, "mf", month, status="PARTIAL", source="AMFI", error="Monthly report not published yet")
            else:
                # prior month may still be unpublished early next month
                set_status(conn, "mf", month, status="PARTIAL", source="AMFI", error="AMFI report not found")
        yield emit("step", key="mf", ok=True, label="Mutual Funds")
    except Exception as exc:
        mf_ok = False
        errors.append(f"Mutual Funds: {exc}")
        yield emit("step", key="mf", ok=False, label="Mutual Funds", error=str(exc))

    try:
        to_fetch = []
        for month in months:
            if should_skip(conn, "sector_fpi", month, month == current):
                continue
            to_fetch.append(month)
        scrape_sector_fpi(http, conn, to_fetch or months, current, lambda k, t: None)
        for month in months:
            has = conn.execute(
                "SELECT 1 FROM sector_fpi_flows WHERE month=? LIMIT 1", (month,)
            ).fetchone()
            if has:
                set_status(
                    conn,
                    "sector_fpi",
                    month,
                    status="PARTIAL" if month == current else "FINAL",
                    source="NSDL",
                    source_url="https://www.fpi.nsdl.co.in/web/Reports/FPI_Fortnightly_Selection.aspx",
                )
        yield emit("step", key="sector_fpi", ok=True, label="Sector Flows")
    except Exception as exc:
        errors.append(f"Sector FPI: {exc}")
        yield emit("step", key="sector_fpi", ok=False, label="Sector Flows", error=str(exc))

    for month in months:
        is_current = month == current
        as_of = last_trading_day(conn, month)
        if not as_of:
            if not is_current:
                hist_skipped += 1
            continue
        status = "PARTIAL" if is_current else "FINAL"
        skip_all = all(
            should_skip(conn, ds, month, is_current)
            for ds in ("market_perf", "sector_perf", "rs")
        )
        if skip_all:
            hist_skipped += 1
            continue

        yield emit("month", text=f"Updating {month_label(month)}...")
        url = f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{as_of[8:10]}{as_of[5:7]}{as_of[:4]}.csv"
        try:
            compute_market_performance(conn, month, as_of, status, url)
            set_status(conn, "market_perf", month, status=status, as_of_date=as_of, source="NSE", source_url=url)
            yield emit("step", key="market_perf", ok=True, label="Market Performance")
        except Exception as exc:
            errors.append(f"Market performance {month}: {exc}")
            yield emit("step", key="market_perf", ok=False, label="Market Performance", error=str(exc))
        try:
            compute_sectors(conn, month, as_of, status)
            for ds in ("sector_perf", "rs"):
                set_status(conn, ds, month, status=status, as_of_date=as_of, source="NSE")
            yield emit("step", key="sector_perf", ok=True, label="Sector Performance")
            yield emit("step", key="rs", ok=True, label="Relative Strength")
        except Exception as exc:
            errors.append(f"Sectors {month}: {exc}")
            yield emit("step", key="sector_perf", ok=False, label="Sector Performance", error=str(exc))

        # FPI/DII monthly status
        fpi = conn.execute(
            "SELECT status, as_of_date FROM institutional_flows WHERE month=? AND category='FPI'",
            (month,),
        ).fetchone()
        if fpi:
            set_status(conn, "fpi", month, status=fpi["status"], as_of_date=fpi["as_of_date"], source="NSDL")
        dii = conn.execute(
            "SELECT status, as_of_date FROM institutional_flows WHERE month=? AND category='DII' AND source='AMFI'",
            (month,),
        ).fetchone()
        if dii:
            set_status(conn, "dii", month, status=dii["status"], as_of_date=dii["as_of_date"], source="AMFI")

        if is_current:
            current_updated = True
        else:
            hist_updated += 1

    conn.execute(
        """
        INSERT INTO scrape_runs (started_at, finished_at, historical_updated, historical_skipped,
            current_updated, errors, summary)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            run_started,
            now_iso(),
            hist_updated,
            hist_skipped,
            int(current_updated),
            len(errors),
            "; ".join(errors)[:2000] if errors else "ok",
        ),
    )
    conn.commit()
    conn.close()
    yield {
        "type": "done",
        "text": "Market data updated",
        "historical_updated": hist_updated,
        "historical_skipped": hist_skipped,
        "current_updated": current_updated,
        "errors": len(errors),
        "error_detail": errors,
        "last_updated": now_iso(),
    }


def _rollup_fii_cash(conn, months: list[str], current: str) -> None:
    """Roll NSE FII cash-tape days into FII_CASH only. Monthly DII comes from
    AMFI notes; this must never overwrite NSDL FPI or AMFI DII."""
    monthly_category = {"FII": "FII_CASH"}
    for month in months:
        rows = conn.execute(
            """
            SELECT category,
                   MAX(trade_date) AS as_of,
                   SUM(buy_value) AS buy_value,
                   SUM(sell_value) AS sell_value,
                   SUM(net_flow) AS net_flow,
                   COUNT(*) AS days
            FROM institutional_flow_daily
            WHERE substr(trade_date,1,7)=?
            GROUP BY category
            """,
            (month,),
        ).fetchall()
        for row in rows:
            target = monthly_category.get(row["category"])
            if not target or not row["as_of"]:
                continue
            upsert(
                conn,
                "institutional_flows",
                {
                    "month": month,
                    "as_of_date": row["as_of"],
                    "category": target,
                    "buy_value": row["buy_value"],
                    "sell_value": row["sell_value"],
                    "net_flow": row["net_flow"],
                    "source": "NSE",
                    "source_url": "https://www.nseindia.com/api/fiidiiTradeReact",
                    "scraped_at": now_iso(),
                    "status": "PARTIAL" if month == current else "FINAL",
                },
                "month, category",
            )
    conn.commit()
