from datetime import datetime

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

    return {
        "selected": selected,
        "monthly": {
            "labels": [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in months],
            "keys": months,
            "fpi": _named_series(fpi_names, fpi_map, months),
            "score": _named_series(score_names, score_map, months),
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
    trail_months = _month_window(months, month, 4)
    dii_map = {
        row["month"]: row["net_flow"]
        for row in fetchall(
            conn,
            f"""
            SELECT month, net_flow FROM institutional_flows
            WHERE category='DII' AND source='AMFI' AND month IN ({",".join("?" for _ in trail_months)})
            """,
            trail_months,
        )
    }
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


def daily_flows_payload(selected: str | None = None, kind: str = "fpi") -> dict:
    conn = connect()
    months, month = _resolve_month(conn, selected)
    if not month:
        conn.close()
        return {"empty": True, "series": []}
    kind = (kind or "fpi").lower()
    if kind not in ("fpi", "dii"):
        kind = "fpi"
    if kind == "dii":
        series = [
            {
                "key": "dii",
                "label": "NSE DII cash",
                "note": "Cash-market sessions NSE has published to us. NSE only posts the latest day publicly; older rows appear after each Update. This tape is not the AMFI monthly note on the chip.",
                **_daily_flow_rows(conn, "DII", "NSE", month),
            }
        ]
        title = "Daily DII"
    else:
        series = [
            {
                "key": "fpi",
                "label": "NSDL FPI",
                "note": "Official day-wise FPI equity buy/sell from NSDL’s monthly page.",
                **_daily_flow_rows(conn, "FPI", "NSDL", month),
            },
            {
                "key": "fii",
                "label": "NSE FII cash",
                "note": "NSE cash-market FII/FPI tape. Different series from NSDL FPI; not used as the monthly chip.",
                **_daily_flow_rows(conn, "FII", "NSE", month),
            },
        ]
        title = "Daily FPI / FII"
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
        "fpi_trail_s": fpi_trail["text"],
        "fpi_trail_cls": fpi_trail["cls"],
        "fpi_trail_steps": fpi_trail["steps"],
        "fpi_via": None if owns else owner,
        "dii_word": dii_word(dii["net_flow"] if dii else None),
        "mf_word": dii_word(mf["equity_net"] if mf else None),
        "ret_1m": pct(score.get("ret_1m")),
        "rs": rs_word(score.get("vs_nifty500_1m")),
        "index_name": spec["index"] if spec else None,
        "symbol": symbol,
        "chart_url": index_chart_url(spec["index"]) if spec else None,
    }
