from datetime import date, datetime, timedelta

from compute import market_regime
from config import FPI_OWNERS, SECTORS, START_MONTH, index_chart_url, symbol_for_index
from db import connect, fetchall, fetchone

SIGNAL_MARK = {
    "Strong Inflow": "🔥",
    "Improving": "🟢",
    "Neutral": "🟡",
    "Distribution": "🟠",
    "Strong Outflow": "🔴",
    "Very Strong": "🔥",
    "Strong": "🟢",
    "Weak": "🔴",
}

REGIME_MARK = {"Risk-On": "🟢", "Risk-Off": "🔴", "Mixed": "🟡"}

CATEGORY_META = [
    ("MONEY_IN", "🔥 MONEY FLOWING IN", "Strong institutional flow + price strength."),
    ("ACCUMULATION", "💰 ACCUMULATION", "Institutions are buying; price is still early."),
    ("WATCH", "🟡 WATCH", "Mixed signals. Wait for confirmation."),
    ("DISTRIBUTION", "⚠️ DISTRIBUTION", "Price weakening as flow fades."),
    ("MONEY_OUT", "🔴 MONEY FLOWING OUT", "Persistent selling + weak price."),
]


def slugify(name: str) -> str:
    return name.lower().replace("&", "and").replace(" ", "-")


def sector_by_slug(slug: str) -> str | None:
    for s in SECTORS:
        if slugify(s["name"]) == slug:
            return s["name"]
    return None


def inr(val) -> str:
    if val is None:
        return "—"
    n = float(val)
    sign = "+" if n > 0 else ""
    return f"{sign}₹{n:,.0f} Cr"


def pct(val) -> str:
    if val is None:
        return "—"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def num(val, digits=1) -> str:
    if val is None:
        return "—"
    return f"{val:.{digits}f}"


def tone(val) -> str:
    if val is None:
        return ""
    if val > 0:
        return "up"
    if val < 0:
        return "down"
    return ""


def rs_word(val) -> str:
    if val is None:
        return "—"
    if val >= 2:
        return "Strong"
    if val <= -2:
        return "Weak"
    return "Neutral"


def dii_word(val) -> str:
    if val is None:
        return "—"
    if val >= 5000:
        return "Strong"
    if val >= 0:
        return "Positive"
    if val > -5000:
        return "Soft"
    return "Weak"


def month_label(month: str) -> str:
    return datetime.strptime(month, "%Y-%m").strftime("%b %Y")


def available_months(conn) -> list[str]:
    return [r["month"] for r in fetchall(
        conn, "SELECT DISTINCT month FROM sector_money_flow_score ORDER BY month"
    )]


def last_run(conn) -> dict | None:
    return fetchone(conn, "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1")


def _resolve_month(conn, selected: str | None) -> tuple[list[str], str | None]:
    months = available_months(conn)
    if not months:
        return [], None
    month = selected if selected in months else months[-1]
    return months, month


def _named_series(names: list[str], mapping: dict, keys: list[str]) -> list[dict]:
    return [{"name": name, "values": [mapping.get((k, name)) for k in keys]} for name in names]


def _months_through(months: list[str], selected: str) -> list[str]:
    if selected in months:
        return months[: months.index(selected) + 1]
    return list(months)


def _inst_net_map(conn, months: list[str], category: str, source: str | None = None) -> dict[str, float]:
    if not months:
        return {}
    q = ",".join("?" for _ in months)
    if source:
        sql = f"""
            SELECT month, net_flow FROM institutional_flows
            WHERE category=? AND source=? AND month IN ({q})
        """
        args = [category, source, *months]
    else:
        sql = f"""
            SELECT month, net_flow FROM institutional_flows
            WHERE category=? AND month IN ({q})
        """
        args = [category, *months]
    return {row["month"]: row["net_flow"] for row in fetchall(conn, sql, args)}


def weekly_sector_series(conn) -> dict:
    start = f"{START_MONTH}-01"
    indexes = [s["index"] for s in SECTORS]
    q = ",".join("?" for _ in indexes)
    rows = fetchall(
        conn,
        f"""
        SELECT index_name, trade_date, close
        FROM daily_indices
        WHERE trade_date>=? AND index_name IN ({q})
        ORDER BY trade_date
        """,
        [start, *indexes],
    )
    last_in_week: dict[tuple[str, str], tuple[str, float]] = {}
    week_dates: dict[str, str] = {}
    for r in rows:
        d = datetime.strptime(r["trade_date"], "%Y-%m-%d").date()
        iso = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        last_in_week[(r["index_name"], iso)] = (r["trade_date"], r["close"])
        prev = week_dates.get(iso)
        if prev is None or r["trade_date"] > prev:
            week_dates[iso] = r["trade_date"]
    week_keys = sorted(week_dates)
    labels = [
        datetime.strptime(week_dates[k], "%Y-%m-%d").strftime("%d %b %Y") for k in week_keys
    ]
    series = []
    for spec in SECTORS:
        idx = spec["index"]
        closes = []
        for key in week_keys:
            hit = last_in_week.get((idx, key))
            closes.append(hit[1] if hit else None)
        rets = []
        prev = None
        for close in closes:
            if close is None or prev in (None, 0):
                rets.append(None)
            else:
                rets.append(round((close / prev - 1.0) * 100.0, 2))
            if close is not None:
                prev = close
        series.append({"name": spec["name"], "values": rets})
    return {"labels": labels, "keys": week_keys, "returns": series}


def build_flow_chart(conn, months: list[str], selected: str) -> dict:
    fpi_rows = fetchall(
        conn,
        """
        SELECT month, sector, equity_net
        FROM sector_fpi_flows
        WHERE period_type='monthly'
        ORDER BY month, period_end
        """,
    )
    fpi_map = {}
    fpi_names = []
    seen = set()
    for row in fpi_rows:
        fpi_map[(row["month"], row["sector"])] = row["equity_net"]
        if row["sector"] not in seen:
            seen.add(row["sector"])
            fpi_names.append(row["sector"])
    fpi_names.sort()

    score_rows = fetchall(
        conn,
        "SELECT month, sector, score FROM sector_money_flow_score ORDER BY month, sector",
    )
    score_map = {(row["month"], row["sector"]): row["score"] for row in score_rows}
    have = {row["sector"] for row in score_rows}
    score_names = [s["name"] for s in SECTORS if s["name"] in have]
    fpi_m = _inst_net_map(conn, months, "FPI")
    dii_m = _inst_net_map(conn, months, "DII", "AMFI")
    fii_m = _inst_net_map(conn, months, "FII_CASH")

    return {
        "selected": selected,
        "monthly": {
            "labels": [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in months],
            "keys": months,
            "fpi": _named_series(fpi_names, fpi_map, months),
            "score": _named_series(score_names, score_map, months),
        },
        "market": {
            "fpi": [fpi_m.get(m) for m in months],
            "dii": [dii_m.get(m) for m in months],
            "fii_cash": [fii_m.get(m) for m in months],
        },
        "weekly": weekly_sector_series(conn),
    }


def meta_payload(selected: str | None = None) -> dict:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    run = last_run(conn)
    errors = []
    if run and run.get("summary") and run["summary"] != "ok":
        errors = [e for e in (run["summary"] or "").split("; ") if e]
    conn.close()
    return {
        "empty": not months,
        "month": month,
        "month_label": datetime.strptime(month, "%Y-%m").strftime("%B %Y") if month else None,
        "months": [{"key": m, "label": month_label(m)} for m in months],
        "run": run,
        "errors": errors,
    }


def market_payload(selected: str | None = None) -> dict:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    if not month:
        conn.close()
        return {"empty": True}
    perf = fetchone(conn, "SELECT * FROM market_performance WHERE month=?", (month,))
    fpi = fetchone(conn, "SELECT * FROM institutional_flows WHERE month=? AND category='FPI'", (month,))
    dii = fetchone(
        conn,
        "SELECT * FROM institutional_flows WHERE month=? AND category='DII' AND source='AMFI'",
        (month,),
    )
    mf = fetchone(conn, "SELECT * FROM mutual_fund_flows WHERE month=?", (month,))
    trail_months = _months_through(months, month)
    fpi_map = _inst_net_map(conn, trail_months, "FPI")
    dii_map = _inst_net_map(conn, trail_months, "DII", "AMFI")
    fpi_trail = _trail(fpi_map, trail_months, compact_cr)
    dii_trail = _trail(dii_map, trail_months, compact_cr)
    scores = fetchall(
        conn,
        "SELECT as_of_date FROM sector_money_flow_score WHERE month=? LIMIT 1",
        (month,),
    )
    as_of = (perf or {}).get("as_of_date") or (scores[0]["as_of_date"] if scores else None)
    regime = market_regime(conn, month)
    conn.close()
    return {
        "empty": False,
        "month": month,
        "month_label": datetime.strptime(month, "%Y-%m").strftime("%B %Y"),
        "as_of": as_of,
        "regime": regime,
        "regime_mark": REGIME_MARK.get(regime, ""),
        "flow": {
            "fpi": fpi,
            "dii": dii,
            "mf": mf,
            "fpi_s": inr(fpi["net_flow"]) if fpi else "—",
            "dii_s": inr(dii["net_flow"]) if dii else "—",
            "mf_s": inr(mf["equity_net"]) if mf else "—",
            "fpi_cls": tone(fpi["net_flow"] if fpi else None),
            "dii_cls": tone(dii["net_flow"] if dii else None),
            "mf_cls": tone(mf["equity_net"] if mf else None),
            "fpi_trail_s": fpi_trail["text"],
            "fpi_trail_steps": fpi_trail["steps"],
            "dii_trail_s": dii_trail["text"],
            "dii_trail_steps": dii_trail["steps"],
        },
    }


def _inr_amt(val) -> str:
    if val is None:
        return "—"
    return f"₹{float(val):,.0f} Cr"


def _daily_flow_rows(conn, category: str, source: str, month: str) -> dict:
    rows = fetchall(
        conn,
        """
        SELECT trade_date, buy_value, sell_value, net_flow, source
        FROM institutional_flow_daily
        WHERE category=? AND source=? AND substr(trade_date,1,7)=?
        ORDER BY trade_date DESC
        """,
        (category, source, month),
    )
    items = []
    buy_sum = sell_sum = net_sum = 0.0
    has_buy = has_sell = has_net = False
    for row in rows:
        items.append(
            {
                "date": row["trade_date"],
                "date_s": datetime.strptime(row["trade_date"], "%Y-%m-%d").strftime("%d %b %Y"),
                "buy_s": _inr_amt(row["buy_value"]),
                "sell_s": _inr_amt(row["sell_value"]),
                "net_s": inr(row["net_flow"]),
                "net_cls": tone(row["net_flow"]),
            }
        )
        if row["buy_value"] is not None:
            buy_sum += row["buy_value"]
            has_buy = True
        if row["sell_value"] is not None:
            sell_sum += row["sell_value"]
            has_sell = True
        if row["net_flow"] is not None:
            net_sum += row["net_flow"]
            has_net = True
    return {
        "rows": items,
        "total": {
            "buy_s": _inr_amt(buy_sum if has_buy else None),
            "sell_s": _inr_amt(sell_sum if has_sell else None),
            "net_s": inr(net_sum if has_net else None),
            "net_cls": tone(net_sum if has_net else None),
        },
    }


def _monthly_flow_block(
    conn, months: list[str], category: str, source: str | None, key: str, label: str, note: str
) -> dict:
    if not months:
        return {
            "key": key,
            "label": label,
            "note": note,
            "period": "month",
            "rows": [],
            "total": {"buy_s": "—", "sell_s": "—", "net_s": "—", "net_cls": ""},
        }
    q = ",".join("?" for _ in months)
    if source:
        sql = f"""
            SELECT month, buy_value, sell_value, net_flow
            FROM institutional_flows
            WHERE category=? AND source=? AND month IN ({q})
        """
        args = [category, source, *months]
    else:
        sql = f"""
            SELECT month, buy_value, sell_value, net_flow
            FROM institutional_flows
            WHERE category=? AND month IN ({q})
        """
        args = [category, *months]
    by = {row["month"]: row for row in fetchall(conn, sql, args)}
    items = []
    buy_sum = sell_sum = net_sum = 0.0
    has_buy = has_sell = has_net = False
    for m in reversed(months):
        row = by.get(m)
        buy = row["buy_value"] if row else None
        sell = row["sell_value"] if row else None
        net = row["net_flow"] if row else None
        items.append(
            {
                "date": m,
                "date_s": month_label(m),
                "buy_s": _inr_amt(buy),
                "sell_s": _inr_amt(sell),
                "net_s": inr(net),
                "net_cls": tone(net),
            }
        )
        if buy is not None:
            buy_sum += buy
            has_buy = True
        if sell is not None:
            sell_sum += sell
            has_sell = True
        if net is not None:
            net_sum += net
            has_net = True
    return {
        "key": key,
        "label": label,
        "note": note,
        "period": "month",
        "rows": items,
        "total": {
            "buy_s": _inr_amt(buy_sum if has_buy else None),
            "sell_s": _inr_amt(sell_sum if has_sell else None),
            "net_s": inr(net_sum if has_net else None),
            "net_cls": tone(net_sum if has_net else None),
        },
    }


def _has_net_rows(block: dict) -> bool:
    return any((row.get("net_s") or "—") != "—" for row in block.get("rows") or [])


def daily_flows_payload(selected: str | None = None, kind: str = "fpi") -> dict:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    if not month:
        conn.close()
        return {"empty": True, "series": []}
    kind = (kind or "fpi").lower()
    if kind not in ("fpi", "dii"):
        kind = "fpi"
    hist = _months_through(months, month)
    if kind == "dii":
        monthly = _monthly_flow_block(
            conn,
            hist,
            "DII",
            "AMFI",
            "dii_m",
            "AMFI DII monthly",
            "Official month net from AMFI notes. Not published by sector.",
        )
        daily = {
            "key": "dii",
            "label": "NSE DII cash · this month",
            "note": "Cash-market sessions NSE has published to us. NSE only posts the latest day publicly; older rows appear after each Update. This tape is not the AMFI monthly note on the chip.",
            "period": "day",
            **_daily_flow_rows(conn, "DII", "NSE", month),
        }
        series = ([monthly] if _has_net_rows(monthly) else []) + [daily]
        title = "DII"
    else:
        monthly_fpi = _monthly_flow_block(
            conn,
            hist,
            "FPI",
            None,
            "fpi_m",
            "NSDL FPI monthly",
            "Official month net from NSDL. This is the figure on the FPI / FII chip.",
        )
        monthly_fii = _monthly_flow_block(
            conn,
            hist,
            "FII_CASH",
            None,
            "fii_m",
            "NSE FII cash monthly",
            "Sum of stored NSE cash-market FII days. Different series from NSDL FPI; can be partial.",
        )
        series = []
        if _has_net_rows(monthly_fpi):
            series.append(monthly_fpi)
        if _has_net_rows(monthly_fii):
            series.append(monthly_fii)
        series.extend(
            [
                {
                    "key": "fpi",
                    "label": "NSDL FPI · this month",
                    "note": "Official day-wise FPI equity buy/sell from NSDL’s monthly page.",
                    "period": "day",
                    **_daily_flow_rows(conn, "FPI", "NSDL", month),
                },
                {
                    "key": "fii",
                    "label": "NSE FII cash · this month",
                    "note": "NSE cash-market FII/FPI tape. Different series from NSDL FPI; not used as the monthly chip.",
                    "period": "day",
                    **_daily_flow_rows(conn, "FII", "NSE", month),
                },
            ]
        )
        title = "FPI / FII"
    conn.close()
    return {
        "empty": False,
        "month": month,
        "month_label": datetime.strptime(month, "%Y-%m").strftime("%B %Y"),
        "kind": kind,
        "title": title,
        "series": series,
    }


def compact_cr(val) -> str:
    if val is None:
        return "—"
    n = float(val)
    sign = "+" if n > 0 else ""
    mag = abs(n)
    if mag >= 1000:
        return f"{sign}{n / 1000:.1f}k"
    return f"{sign}{n:.0f}"


def _month_window(months: list[str], selected: str, count: int = 4) -> list[str]:
    if selected not in months:
        return [selected]
    end = months.index(selected) + 1
    return months[max(0, end - count) : end]


def _score_trail_map(conn, months: list[str]) -> dict[str, dict[str, float]]:
    if not months:
        return {}
    q = ",".join("?" for _ in months)
    rows = fetchall(
        conn,
        f"SELECT month, sector, score FROM sector_money_flow_score WHERE month IN ({q})",
        months,
    )
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        out.setdefault(row["sector"], {})[row["month"]] = row["score"]
    return out


def _fpi_trail_map(conn, months: list[str]) -> dict[str, dict[str, float]]:
    if not months:
        return {}
    q = ",".join("?" for _ in months)
    rows = fetchall(
        conn,
        f"""
        SELECT month, sector, equity_net
        FROM sector_fpi_flows
        WHERE period_type='monthly' AND month IN ({q})
        ORDER BY period_end
        """,
        months,
    )
    by_nsdl: dict[str, dict[str, float]] = {}
    for row in rows:
        by_nsdl.setdefault(row["sector"], {})[row["month"]] = row["equity_net"]
    return {spec["name"]: by_nsdl.get(spec["fpi"]) or {} for spec in SECTORS}


def _fpi_owner(sector_name: str) -> str | None:
    spec = next((s for s in SECTORS if s["name"] == sector_name), None)
    if not spec:
        return None
    return FPI_OWNERS.get(spec["fpi"])


def _trail(by_month: dict, months: list[str], fmt) -> dict:
    vals = [by_month.get(m) for m in months]
    steps = []
    prev = None
    last_cls = ""
    for v in vals:
        label = fmt(v) if v is not None else "—"
        cls = ""
        if v is not None and prev is not None:
            cls = tone(v - prev)
            last_cls = cls
        steps.append({"s": label, "cls": cls})
        if v is not None:
            prev = v
    first = next((v for v in vals if v is not None), None)
    last = next((v for v in reversed(vals) if v is not None), None)
    return {
        "parts": [p["s"] for p in steps],
        "steps": steps,
        "text": " → ".join(p["s"] for p in steps),
        "cls": last_cls or tone(None if first is None or last is None else last - first),
    }


def sectors_payload(selected: str | None = None) -> dict:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    if not month:
        conn.close()
        return {"empty": True, "rows": [], "groups": []}
    fpi_by_name = {
        spec["name"]: fetchone(
            conn,
            """
            SELECT equity_net FROM sector_fpi_flows
            WHERE month=? AND sector=? AND period_type='monthly'
            ORDER BY period_end DESC
            """,
            (month, spec["fpi"]),
        )
        for spec in SECTORS
    }
    scores = fetchall(
        conn,
        """
        SELECT s.sector, s.score, s.signal, s.category, s.as_of_date
        FROM sector_money_flow_score s
        WHERE s.month=?
        ORDER BY s.score DESC
        """,
        (month,),
    )
    trail_months = _month_window(months, month, 4)
    score_map = _score_trail_map(conn, trail_months)
    fpi_map = _fpi_trail_map(conn, trail_months)
    rows = []
    for i, s in enumerate(scores, 1):
        owner = _fpi_owner(s["sector"])
        owns = owner == s["sector"]
        fpi_row = fpi_by_name.get(s["sector"]) if owns else None
        fpi_val = fpi_row["equity_net"] if fpi_row else None
        score_trail = _trail(score_map.get(s["sector"]) or {}, trail_months, lambda v: num(v, 0))
        fpi_trail = _trail(fpi_map.get(s["sector"]) or {}, trail_months, compact_cr) if owns else {
            "text": "",
            "cls": "",
            "steps": [],
        }
        rows.append(
            {
                "rank": i,
                "sector": s["sector"],
                "slug": slugify(s["sector"]),
                "category": s.get("category"),
                "signal": s.get("signal"),
                "mark": SIGNAL_MARK.get(s.get("signal"), ""),
                "score": s.get("score"),
                "score_s": num(s.get("score"), 0),
                "trail_s": score_trail["text"],
                "trail_cls": score_trail["cls"],
                "trail_steps": score_trail["steps"],
                "fpi_val": fpi_val,
                "fpi_s": inr(fpi_val) if owns else "—",
                "fpi_cls": tone(fpi_val) if owns else "",
                "fpi_trail_s": fpi_trail["text"],
                "fpi_trail_cls": fpi_trail["cls"],
                "fpi_trail_steps": fpi_trail["steps"],
                "fpi_via": None if owns else owner,
            }
        )
    groups = []
    for key, title, blurb in CATEGORY_META:
        items = [r for r in rows if r.get("category") == key]
        if items:
            groups.append({"key": key, "title": title, "blurb": blurb, "sectors": items})
    conn.close()
    return {"empty": False, "month": month, "rows": rows, "groups": groups}


def fpi_payload(selected: str | None = None) -> dict:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    if not month:
        conn.close()
        return {"empty": True, "rows": []}
    fpi_split_rows = fetchall(
        conn,
        """
        SELECT sector, equity_net
        FROM sector_fpi_flows
        WHERE month=? AND period_type='monthly'
        ORDER BY period_end DESC
        """,
        (month,),
    )
    seen_fpi = set()
    rows = []
    for row in fpi_split_rows:
        if row["sector"] in seen_fpi:
            continue
        seen_fpi.add(row["sector"])
        rows.append(
            {
                "sector": row["sector"],
                "val": row["equity_net"],
                "s": inr(row["equity_net"]),
                "cls": tone(row["equity_net"]),
            }
        )
    rows.sort(key=lambda x: (x["val"] is None, -(x["val"] or 0)))
    conn.close()
    return {"empty": False, "month": month, "rows": rows}


def chart_payload(selected: str | None = None) -> dict:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    if not month:
        conn.close()
        return {"empty": True, "chart": None}
    chart = build_flow_chart(conn, months, month)
    conn.close()
    return {"empty": False, "month": month, "chart": chart}


def sector_payload(name: str, selected: str | None = None) -> dict | None:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    if not month:
        conn.close()
        return None
    score = fetchone(
        conn,
        """
        SELECT s.*, p.ret_1m, p.ret_3m, p.ret_1y, r.vs_nifty500_1m
        FROM sector_money_flow_score s
        LEFT JOIN sector_performance p ON p.month=s.month AND p.sector=s.sector
        LEFT JOIN sector_relative_strength r ON r.month=s.month AND r.sector=s.sector
        WHERE s.month=? AND s.sector=?
        """,
        (month, name),
    )
    if not score:
        conn.close()
        return None
    spec = next((s for s in SECTORS if s["name"] == name), None)
    symbol = symbol_for_index(spec["index"]) if spec else None
    fpi = None
    if spec:
        fpi = fetchone(
            conn,
            """
            SELECT * FROM sector_fpi_flows
            WHERE month=? AND sector=? AND period_type='monthly'
            ORDER BY period_end DESC
            """,
            (month, spec["fpi"]),
        )
    mf = fetchone(conn, "SELECT * FROM mutual_fund_flows WHERE month=?", (month,))
    dii = fetchone(
        conn,
        "SELECT * FROM institutional_flows WHERE month=? AND category='DII' AND source='AMFI'",
        (month,),
    )
    trail_months = _month_window(months, month, 4)
    hist = _months_through(months, month)
    score_trail = _trail(
        (_score_trail_map(conn, trail_months).get(name) or {}),
        trail_months,
        lambda v: num(v, 0),
    )
    owner = _fpi_owner(name)
    owns = owner == name
    fpi_trail = _trail(
        (_fpi_trail_map(conn, trail_months).get(name) or {}),
        trail_months,
        compact_cr,
    ) if owns else {"text": "", "cls": "", "steps": []}
    dii_map = _inst_net_map(conn, hist, "DII", "AMFI")
    dii_trail = _trail(dii_map, hist, compact_cr)
    conn.close()
    return {
        "name": name,
        "slug": slugify(name),
        "month": month,
        "months": [{"key": m, "label": month_label(m)} for m in months],
        "score": score,
        "mark": SIGNAL_MARK.get(score.get("signal"), ""),
        "trail_s": score_trail["text"],
        "trail_cls": score_trail["cls"],
        "trail_steps": score_trail["steps"],
        "fpi": fpi if owns else None,
        "fpi_s": inr(fpi["equity_net"]) if owns and fpi else "—",
        "fpi_cls": tone(fpi["equity_net"]) if owns and fpi else "",
        "fpi_trail_s": fpi_trail["text"],
        "fpi_trail_cls": fpi_trail["cls"],
        "fpi_trail_steps": fpi_trail["steps"],
        "fpi_via": None if owns else owner,
        "dii_s": inr(dii["net_flow"] if dii else None),
        "dii_cls": tone(dii["net_flow"] if dii else None),
        "dii_trail_s": dii_trail["text"],
        "dii_trail_steps": dii_trail["steps"],
        "dii_word": dii_word(dii["net_flow"] if dii else None),
        "mf_word": dii_word(mf["equity_net"] if mf else None),
        "ret_1m": pct(score.get("ret_1m")),
        "rs": rs_word(score.get("vs_nifty500_1m")),
        "index_name": spec["index"] if spec else None,
        "symbol": symbol,
        "chart_url": index_chart_url(spec["index"]) if spec else None,
    }


DEAL_SCORE = {
    ("BULK", "BUY"): 2,
    ("BULK", "SELL"): -2,
    ("BLOCK", "BUY"): 3,
    ("BLOCK", "SELL"): -3,
    ("SHORT_SELLING", "BUY"): -1,
    ("SHORT_SELLING", "SELL"): -1,
}


def _iso(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat(timespec="seconds")
    if isinstance(val, date):
        return val.isoformat()
    return str(val)


def inr_rs(val, signed=False) -> str:
    if val is None:
        return "—"
    n = float(val)
    if signed:
        sign = "+" if n > 0 else ("-" if n < 0 else "")
    else:
        sign = "-" if n < 0 else ""
    mag = abs(n)
    if mag >= 1e12:
        x = mag / 1e12
        body = f"{x:.2f}".rstrip("0").rstrip(".")
        return f"{sign}₹{body} Lakh Cr"
    if mag >= 1e7:
        x = mag / 1e7
        body = f"{x:.2f}".rstrip("0").rstrip(".")
        return f"{sign}₹{body} Cr"
    if mag >= 1e5:
        x = mag / 1e5
        body = f"{x:.1f}".rstrip("0").rstrip(".")
        return f"{sign}₹{body} L"
    if mag >= 1e3:
        x = mag / 1e3
        body = f"{x:.1f}".rstrip("0").rstrip(".")
        return f"{sign}₹{body} K"
    return f"{sign}₹{mag:,.0f}"


def qty_s(val) -> str:
    if val is None:
        return "—"
    return f"{int(val):,}"


def _deal_signal(net_value, deals, buy_value, sell_value) -> str:
    total = abs(buy_value or 0) + abs(sell_value or 0)
    net = net_value or 0
    if not deals or total <= 0:
        return "Neutral"
    share = abs(net) / total
    if net > 0 and share >= 0.15:
        return "Strong"
    if net < 0 and share >= 0.15:
        return "Weak"
    return "Neutral"


def _parse_filters(args: dict) -> tuple[str, list]:
    where = ["1=1"]
    params: list = []
    day = (args.get("date") or "").strip()
    from_date = (args.get("fromDate") or args.get("from") or "").strip()
    to_date = (args.get("toDate") or args.get("to") or "").strip()
    if day:
        where.append("trade_date = ?")
        params.append(day)
    else:
        if from_date:
            where.append("trade_date >= ?")
            params.append(from_date)
        if to_date:
            where.append("trade_date <= ?")
            params.append(to_date)
    exchange = (args.get("exchange") or "ALL").strip().upper()
    if exchange in ("NSE", "BSE"):
        where.append("exchange = ?")
        params.append(exchange)
    deal_type = (args.get("dealType") or args.get("deal_type") or "ALL").strip().upper().replace(" ", "_")
    if deal_type in ("SHORT", "SHORTSELLING"):
        deal_type = "SHORT_SELLING"
    if deal_type in ("BULK", "BLOCK", "SHORT_SELLING"):
        where.append("deal_type = ?")
        params.append(deal_type)
    symbol = (args.get("symbol") or "").strip()
    if symbol:
        where.append("(symbol ILIKE ? OR company_name ILIKE ?)")
        params.extend([f"%{symbol}%", f"%{symbol}%"])
    client = (args.get("client") or "").strip()
    if client:
        where.append("client_name ILIKE ?")
        params.append(f"%{client}%")
    buy_sell = (args.get("buySell") or args.get("buy_sell") or "").strip().upper()
    if buy_sell in ("BUY", "SELL"):
        where.append("buy_sell = ?")
        params.append(buy_sell)
    return " AND ".join(where), params


def _fmt_deal_row(row: dict) -> dict:
    qty = row.get("quantity")
    price = row.get("price")
    value = row.get("deal_value")
    if value is None and qty and price:
        value = float(qty) * float(price)
    return {
        "id": row.get("id"),
        "trade_date": _iso(row.get("trade_date")),
        "exchange": row.get("exchange"),
        "symbol": row.get("symbol"),
        "company_name": row.get("company_name"),
        "isin": row.get("isin"),
        "sector": row.get("sector"),
        "deal_type": row.get("deal_type"),
        "buy_sell": row.get("buy_sell"),
        "client_name": row.get("client_name"),
        "quantity": qty,
        "quantity_s": qty_s(qty),
        "price": price,
        "price_s": f"₹{float(price):,.2f}" if price else "—",
        "deal_value": value,
        "deal_value_s": inr_rs(value),
        "source": row.get("source"),
    }


def deals_last_fetch(conn=None) -> dict:
    own = conn is None
    if own:
        conn = connect()
    rows = fetchall(
        conn,
        """
        SELECT * FROM deal_fetch_logs
        ORDER BY completed_at DESC NULLS LAST, id DESC
        LIMIT 12
        """,
    )
    if own:
        conn.close()
    if not rows:
        return {"at": None, "at_s": None, "nse": {}, "bse": {}, "fetched": 0, "inserted": 0, "duplicates": 0, "invalid": 0}
    latest = rows[0]["completed_at"] or rows[0]["started_at"]
    window = []
    seen = set()
    for row in rows:
        key = (row.get("exchange"), row.get("deal_type"))
        if key in seen:
            break
        seen.add(key)
        window.append(row)
    nse, bse = {}, {}
    fetched = inserted = dupes = invalid = 0
    for row in window:
        bucket = nse if row.get("exchange") == "NSE" else bse if row.get("exchange") == "BSE" else None
        if bucket is not None:
            bucket[row.get("deal_type")] = {
                "ok": row.get("status") == "SUCCESS",
                "status": row.get("status"),
                "error": row.get("error_message"),
            }
        fetched += row.get("records_fetched") or 0
        inserted += row.get("records_inserted") or 0
        dupes += row.get("duplicates") or 0
        invalid += row.get("invalid_records") or 0
    return {
        "at": _iso(latest),
        "at_s": _iso(latest),
        "nse": nse,
        "bse": bse,
        "fetched": fetched,
        "inserted": inserted,
        "duplicates": dupes,
        "invalid": invalid,
    }


def deals_list_payload(args: dict) -> dict:
    conn = connect()
    where, params = _parse_filters(args)
    page = max(1, int(args.get("page") or 1))
    size = min(200, max(1, int(args.get("pageSize") or args.get("limit") or 50)))
    offset = (page - 1) * size
    total = fetchone(conn, f"SELECT COUNT(*) AS n FROM large_deals WHERE {where}", params)["n"]
    rows = fetchall(
        conn,
        f"""
        SELECT id, trade_date, exchange, symbol, company_name, isin, sector,
               deal_type, buy_sell, client_name, quantity, price, deal_value, source
        FROM large_deals
        WHERE {where}
        ORDER BY trade_date DESC, deal_value DESC NULLS LAST, id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, size, offset],
    )
    last = deals_last_fetch(conn)
    latest_row = fetchone(conn, "SELECT MAX(trade_date) AS d FROM large_deals")
    conn.close()
    return {
        "total": total,
        "page": page,
        "pageSize": size,
        "pages": max(1, (total + size - 1) // size) if total else 1,
        "rows": [_fmt_deal_row(r) for r in rows],
        "lastFetch": last,
        "latestDate": _iso(latest_row["d"]) if latest_row and latest_row.get("d") else None,
    }


def deals_stats_payload(args: dict) -> dict:
    conn = connect()
    where, params = _parse_filters(args)
    agg = fetchone(
        conn,
        f"""
        SELECT
            COUNT(*) AS total_deals,
            COUNT(*) FILTER (WHERE buy_sell='BUY') AS buy_deals,
            COUNT(*) FILTER (WHERE buy_sell='SELL') AS sell_deals,
            COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='BUY'), 0) AS buy_value,
            COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='SELL'), 0) AS sell_value,
            COUNT(DISTINCT symbol) AS unique_stocks
        FROM large_deals
        WHERE {where}
        """,
        params,
    )
    daily = fetchall(
        conn,
        f"""
        SELECT trade_date,
               COUNT(*) AS deals,
               COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='BUY'), 0) AS buy_value,
               COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='SELL'), 0) AS sell_value
        FROM large_deals
        WHERE {where}
        GROUP BY trade_date
        ORDER BY trade_date
        """,
        params,
    )
    by_type = fetchall(
        conn,
        f"""
        SELECT deal_type,
               COUNT(*) AS deals,
               COALESCE(SUM(deal_value), 0) AS value
        FROM large_deals
        WHERE {where}
        GROUP BY deal_type
        ORDER BY value DESC
        """,
        params,
    )
    scores = _deal_scores(conn, where, params, limit=80)
    _attach_market_caps(conn, scores)
    sectors = _deal_sectors(conn, where, params)
    last = deals_last_fetch(conn)
    latest_row = fetchone(conn, "SELECT MAX(trade_date) AS d FROM large_deals")
    conn.close()
    from deals import start_cap_refresh

    start_cap_refresh([r["symbol"] for r in scores])
    buy_value = float(agg["buy_value"] or 0)
    sell_value = float(agg["sell_value"] or 0)
    net = buy_value - sell_value
    total_value = buy_value + sell_value
    return {
        "totalDeals": agg["total_deals"] or 0,
        "buyDeals": agg["buy_deals"] or 0,
        "sellDeals": agg["sell_deals"] or 0,
        "buyValue": buy_value,
        "sellValue": sell_value,
        "netValue": net,
        "totalValue": total_value,
        "uniqueStocks": agg["unique_stocks"] or 0,
        "formatted": {
            "totalDeals": f"{agg['total_deals'] or 0:,}",
            "totalValue": inr_rs(total_value),
            "buyValue": inr_rs(buy_value),
            "sellValue": inr_rs(sell_value),
            "netBuy": inr_rs(net, signed=True),
            "stocks": f"{agg['unique_stocks'] or 0:,}",
        },
        "daily": [
            {
                "date": _iso(r["trade_date"]),
                "deals": r["deals"],
                "buyValue": float(r["buy_value"] or 0),
                "sellValue": float(r["sell_value"] or 0),
            }
            for r in daily
        ],
        "byType": [
            {
                "dealType": r["deal_type"],
                "deals": r["deals"],
                "value": float(r["value"] or 0),
                "value_s": inr_rs(r["value"]),
            }
            for r in by_type
        ],
        "scores": scores,
        "sectors": sectors,
        "lastFetch": last,
        "latestDate": _iso(latest_row["d"]) if latest_row and latest_row.get("d") else None,
    }


def _deal_scores(conn, where: str, params: list, limit: int = 40) -> list[dict]:
    rows = fetchall(
        conn,
        f"""
        SELECT symbol, MAX(company_name) AS company_name, MAX(sector) AS sector,
               COUNT(*) AS deals,
               COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='BUY'), 0) AS buy_value,
               COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='SELL'), 0) AS sell_value
        FROM large_deals
        WHERE {where}
        GROUP BY symbol
        ORDER BY COUNT(*) DESC
        LIMIT ?
        """,
        [*params, limit],
    )
    type_rows = fetchall(
        conn,
        f"""
        SELECT symbol, deal_type, buy_sell, COUNT(*) AS n
        FROM large_deals
        WHERE {where}
        GROUP BY symbol, deal_type, buy_sell
        """,
        params,
    )
    repeat_rows = fetchall(
        conn,
        f"""
        SELECT symbol, client_name, COUNT(*) AS n
        FROM large_deals
        WHERE {where} AND buy_sell='BUY' AND client_name <> ''
        GROUP BY symbol, client_name
        HAVING COUNT(*) >= 2
        """,
        params,
    )
    type_map: dict[str, list] = {}
    for row in type_rows:
        type_map.setdefault(row["symbol"], []).append(row)
    extra = {}
    for row in repeat_rows:
        extra[row["symbol"]] = extra.get(row["symbol"], 0) + int(row["n"]) - 1
    out = []
    for row in rows:
        score = extra.get(row["symbol"], 0)
        bulk = block = None
        for part in type_map.get(row["symbol"], []):
            score += DEAL_SCORE.get((part["deal_type"], part["buy_sell"]), 0) * int(part["n"])
            if part["deal_type"] == "BULK":
                bulk = part["buy_sell"]
            if part["deal_type"] == "BLOCK":
                block = part["buy_sell"]
        net = float(row["buy_value"] or 0) - float(row["sell_value"] or 0)
        out.append(
            {
                "symbol": row["symbol"],
                "company_name": row["company_name"],
                "sector": row["sector"],
                "score": score,
                "buy_value": float(row["buy_value"] or 0),
                "sell_value": float(row["sell_value"] or 0),
                "net_value": net,
                "deals": row["deals"],
                "buy_s": inr_rs(row["buy_value"]),
                "sell_s": inr_rs(row["sell_value"]),
                "net_s": inr_rs(net, signed=True),
                "net_cls": tone(net),
                "bulk": bulk,
                "block": block,
            }
        )
    out.sort(key=lambda r: (r["score"], r["net_value"]), reverse=True)
    return out


def _cap_fields(row: dict | None) -> dict:
    cap = None
    if row and row.get("market_cap") is not None:
        cap = float(row["market_cap"])
    return {
        "market_cap": cap,
        "market_cap_s": inr_rs(cap) if cap else "—",
        "last_price": float(row["last_price"]) if row and row.get("last_price") is not None else None,
        "last_price_s": f"₹{float(row['last_price']):,.2f}" if row and row.get("last_price") else "—",
        "cap_source": (row or {}).get("source"),
    }


def _attach_market_caps(conn, rows: list[dict]) -> None:
    symbols = [r.get("symbol") for r in rows if r.get("symbol")]
    if not symbols:
        return
    placeholders = ", ".join("?" for _ in symbols)
    caps = {
        r["symbol"]: r
        for r in fetchall(
            conn,
            f"SELECT symbol, market_cap, last_price, source FROM stock_market_cap WHERE symbol IN ({placeholders})",
            symbols,
        )
    }
    for row in rows:
        row.update(_cap_fields(caps.get(row.get("symbol"))))


def _deal_sectors(conn, where: str, params: list) -> list[dict]:
    rows = fetchall(
        conn,
        f"""
        SELECT COALESCE(NULLIF(sector, ''), 'Unmapped') AS sector,
               COUNT(*) AS deals,
               COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='BUY'), 0) AS buy_value,
               COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='SELL'), 0) AS sell_value
        FROM large_deals
        WHERE {where}
        GROUP BY COALESCE(NULLIF(sector, ''), 'Unmapped')
        ORDER BY COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='BUY'), 0)
               - COALESCE(SUM(deal_value) FILTER (WHERE buy_sell='SELL'), 0) DESC
        """,
        params,
    )
    out = []
    for row in rows:
        buy = float(row["buy_value"] or 0)
        sell = float(row["sell_value"] or 0)
        net = buy - sell
        out.append(
            {
                "sector": row["sector"],
                "slug": slugify(row["sector"]) if row["sector"] != "Unmapped" else None,
                "buy_value": buy,
                "sell_value": sell,
                "net_value": net,
                "deals": row["deals"],
                "buy_s": inr_rs(buy),
                "sell_s": inr_rs(sell),
                "net_s": inr_rs(net, signed=True),
                "net_cls": tone(net),
                "signal": _deal_signal(net, row["deals"], buy, sell),
            }
        )
    return out


def deals_fetch_history_payload(limit: int = 40) -> dict:
    conn = connect()
    rows = fetchall(
        conn,
        """
        SELECT * FROM deal_fetch_logs
        ORDER BY completed_at DESC NULLS LAST, id DESC
        LIMIT ?
        """,
        (min(100, max(1, limit)),),
    )
    conn.close()
    out = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "run_date": _iso(row.get("run_date")),
                "requested_date": _iso(row.get("requested_date")),
                "exchange": row.get("exchange"),
                "deal_type": row.get("deal_type"),
                "started_at": _iso(row.get("started_at")),
                "completed_at": _iso(row.get("completed_at")),
                "status": row.get("status"),
                "records_fetched": row.get("records_fetched") or 0,
                "records_inserted": row.get("records_inserted") or 0,
                "duplicates": row.get("duplicates") or 0,
                "invalid_records": row.get("invalid_records") or 0,
                "error_message": row.get("error_message"),
            }
        )
    return {"rows": out}


def deals_stock_payload(symbol: str, lookback: int | None = None) -> dict | None:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return None
    conn = connect()
    today = date.today()
    if lookback:
        start = (today - timedelta(days=int(lookback))).isoformat()
        rows = fetchall(
            conn,
            """
            SELECT id, trade_date, exchange, symbol, company_name, isin, sector,
                   deal_type, buy_sell, client_name, quantity, price, deal_value, source
            FROM large_deals
            WHERE symbol=? AND trade_date >= ?
            ORDER BY trade_date DESC, id DESC
            """,
            (symbol, start),
        )
    else:
        rows = fetchall(
            conn,
            """
            SELECT id, trade_date, exchange, symbol, company_name, isin, sector,
                   deal_type, buy_sell, client_name, quantity, price, deal_value, source
            FROM large_deals
            WHERE symbol=?
            ORDER BY trade_date DESC, id DESC
            """,
            (symbol,),
        )
    if not rows:
        conn.close()
        return None
    member = fetchone(conn, "SELECT * FROM nse_index_members WHERE symbol=?", (symbol,))
    sector_name = rows[0].get("sector") or (member["sector"] if member else None)
    flow = None
    if sector_name:
        flow = fetchone(
            conn,
            """
            SELECT sector, score, signal, month, as_of_date
            FROM sector_money_flow_score
            WHERE sector=?
            ORDER BY month DESC
            LIMIT 1
            """,
            (sector_name,),
        )
    conn.close()
    from deals import ensure_market_cap

    cap = ensure_market_cap(symbol)

    def from_rows(subset: list, days: int | None = None) -> dict:
        buy_qty = sum(int(r["quantity"] or 0) for r in subset if r.get("buy_sell") == "BUY")
        sell_qty = sum(int(r["quantity"] or 0) for r in subset if r.get("buy_sell") == "SELL")
        buy_val = sum(float(r["deal_value"] or 0) for r in subset if r.get("buy_sell") == "BUY")
        sell_val = sum(float(r["deal_value"] or 0) for r in subset if r.get("buy_sell") == "SELL")
        return {
            "days": days,
            "deals": len(subset),
            "buy_qty": buy_qty,
            "sell_qty": sell_qty,
            "net_qty": buy_qty - sell_qty,
            "buy_value": buy_val,
            "sell_value": sell_val,
            "net_value": buy_val - sell_val,
            "buy_qty_s": qty_s(buy_qty),
            "sell_qty_s": qty_s(sell_qty),
            "net_qty_s": qty_s(buy_qty - sell_qty) if buy_qty != sell_qty else "0",
            "buy_s": inr_rs(buy_val),
            "sell_s": inr_rs(sell_val),
            "net_s": inr_rs(buy_val - sell_val, signed=True),
            "net_cls": tone(buy_val - sell_val),
        }

    def window(days: int) -> dict:
        cut = (today - timedelta(days=days)).isoformat()
        return from_rows([r for r in rows if _iso(r["trade_date"]) >= cut], days)

    latest = rows[0]
    oldest = rows[-1]
    w90 = window(90)
    wall = from_rows(rows)
    type_score = 0
    bulk = block = None
    clients: dict[str, int] = {}
    by_date: dict[str, list] = {}
    for rec in rows:
        type_score += DEAL_SCORE.get((rec.get("deal_type"), rec.get("buy_sell")), 0)
        if rec.get("deal_type") == "BULK":
            bulk = rec.get("buy_sell")
        if rec.get("deal_type") == "BLOCK":
            block = rec.get("buy_sell")
        if rec.get("buy_sell") == "BUY" and rec.get("client_name"):
            clients[rec["client_name"]] = clients.get(rec["client_name"], 0) + 1
        day = _iso(rec.get("trade_date"))
        if day:
            by_date.setdefault(day, []).append(rec)
    type_score += sum(n - 1 for n in clients.values() if n >= 2)
    timeline = []
    for day in sorted(by_date.keys(), reverse=True):
        day_rows = by_date[day]
        buy_val = sum(float(r["deal_value"] or 0) for r in day_rows if r.get("buy_sell") == "BUY")
        sell_val = sum(float(r["deal_value"] or 0) for r in day_rows if r.get("buy_sell") == "SELL")
        buy_qty = sum(int(r["quantity"] or 0) for r in day_rows if r.get("buy_sell") == "BUY")
        sell_qty = sum(int(r["quantity"] or 0) for r in day_rows if r.get("buy_sell") == "SELL")
        timeline.append(
            {
                "date": day,
                "deals": len(day_rows),
                "buys": sum(1 for r in day_rows if r.get("buy_sell") == "BUY"),
                "sells": sum(1 for r in day_rows if r.get("buy_sell") == "SELL"),
                "buyValue": buy_val,
                "sellValue": sell_val,
                "netValue": buy_val - sell_val,
                "buyQty": buy_qty,
                "sellQty": sell_qty,
                "buy_s": inr_rs(buy_val),
                "sell_s": inr_rs(sell_val),
                "net_s": inr_rs(buy_val - sell_val, signed=True),
                "net_cls": tone(buy_val - sell_val),
                "rows": [_fmt_deal_row(r) for r in day_rows],
            }
        )
    return {
        "symbol": symbol,
        "company_name": latest.get("company_name") or symbol,
        "sector": sector_name,
        "date": _iso(latest.get("trade_date")),
        "firstDate": _iso(oldest.get("trade_date")),
        "lastDate": _iso(latest.get("trade_date")),
        "dateCount": len(timeline),
        "score": type_score,
        "bulk": bulk,
        "block": block,
        "sector_flow": {
            "signal": flow.get("signal") if flow else None,
            "score": flow.get("score") if flow else None,
            "month": flow.get("month") if flow else None,
        },
        "totals": wall,
        "windows": {"7d": window(7), "30d": window(30), "90d": w90},
        "timeline": timeline,
        "rows": [_fmt_deal_row(r) for r in rows],
        **_cap_fields(cap),
    }


def _month_date_bounds(month: str) -> tuple[str, str]:
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start.isoformat(), end.isoformat()


def deals_sector_map(conn, month: str) -> dict[str, dict]:
    start, end = _month_date_bounds(month)
    rows = _deal_sectors(conn, "trade_date >= ? AND trade_date < ?", [start, end])
    return {r["sector"]: r for r in rows}


def deals_sector_detail(conn, name: str, month: str) -> dict:
    start, end = _month_date_bounds(month)
    where = "sector=? AND trade_date >= ? AND trade_date < ?"
    params = [name, start, end]
    scores = _deal_scores(conn, where, params, limit=15)
    sectors = _deal_sectors(conn, where, params)
    summary = sectors[0] if sectors else {
        "buy_s": "—",
        "sell_s": "—",
        "net_s": "—",
        "net_cls": "",
        "deals": 0,
        "signal": "Neutral",
        "net_value": 0,
    }
    rows = fetchall(
        conn,
        """
        SELECT id, trade_date, exchange, symbol, company_name, isin, sector,
               deal_type, buy_sell, client_name, quantity, price, deal_value, source
        FROM large_deals
        WHERE sector=? AND trade_date >= ? AND trade_date < ?
        ORDER BY trade_date DESC, deal_value DESC NULLS LAST
        LIMIT 40
        """,
        (name, start, end),
    )
    return {
        "summary": summary,
        "scores": scores,
        "rows": [_fmt_deal_row(r) for r in rows],
    }

