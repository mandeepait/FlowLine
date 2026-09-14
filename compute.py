from config import NIFTY_500, SECTORS, WEIGHTS
from db import now_iso, upsert


def last_trading_day(conn, month: str | None = None, before: str | None = None) -> str | None:
    sql = "SELECT MAX(trade_date) AS d FROM daily_indices"
    args: list = []
    clauses = []
    if month:
        clauses.append("substr(trade_date,1,7)=?")
        args.append(month)
    if before:
        clauses.append("trade_date<=?")
        args.append(before)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    row = conn.execute(sql, args).fetchone()
    return row["d"] if row and row["d"] else None


def index_close_on(conn, name: str, day: str) -> float | None:
    row = conn.execute(
        "SELECT close FROM daily_indices WHERE index_name=? AND trade_date=?",
        (name, day),
    ).fetchone()
    return row["close"] if row else None


def index_close_asof(conn, name: str, as_of: str, lookback_days: int | None = None, ytd: bool = False) -> float | None:
    if ytd:
        start = f"{as_of[:4]}-01-01"
        row = conn.execute(
            """
            SELECT close FROM daily_indices
            WHERE index_name=? AND trade_date>=? AND trade_date<=?
            ORDER BY trade_date LIMIT 1
            """,
            (name, start, as_of),
        ).fetchone()
        return row["close"] if row else None
    if lookback_days is None:
        row = conn.execute(
            "SELECT close FROM daily_indices WHERE index_name=? AND trade_date=?",
            (name, as_of),
        ).fetchone()
        return row["close"] if row else None
    row = conn.execute(
        """
        SELECT close FROM daily_indices
        WHERE index_name=? AND trade_date<=(?::date - (? * INTERVAL '1 day'))::text
        ORDER BY trade_date DESC LIMIT 1
        """,
        (name, as_of, lookback_days),
    ).fetchone()
    return row["close"] if row else None


def pct(new, old) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def returns_for(conn, name: str, as_of: str) -> dict:
    close = index_close_asof(conn, name, as_of)
    return {
        "close": close,
        "ret_1w": pct(close, index_close_asof(conn, name, as_of, 7)),
        "ret_1m": pct(close, index_close_asof(conn, name, as_of, 30)),
        "ret_3m": pct(close, index_close_asof(conn, name, as_of, 91)),
        "ret_6m": pct(close, index_close_asof(conn, name, as_of, 182)),
        "ret_ytd": pct(close, index_close_asof(conn, name, as_of, ytd=True)),
        "ret_1y": pct(close, index_close_asof(conn, name, as_of, 365)),
    }


def compute_market_performance(conn, month: str, as_of: str, status: str, url: str) -> None:
    n50 = returns_for(conn, "Nifty 50", as_of)
    n500 = returns_for(conn, NIFTY_500, as_of)
    upsert(
        conn,
        "market_performance",
        {
            "month": month,
            "as_of_date": as_of,
            "nifty50_close": n50["close"],
            "nifty50_ret_1w": n50["ret_1w"],
            "nifty50_ret_1m": n50["ret_1m"],
            "nifty50_ret_3m": n50["ret_3m"],
            "nifty50_ret_6m": n50["ret_6m"],
            "nifty50_ret_ytd": n50["ret_ytd"],
            "nifty50_ret_1y": n50["ret_1y"],
            "nifty500_close": n500["close"],
            "nifty500_ret_1w": n500["ret_1w"],
            "nifty500_ret_1m": n500["ret_1m"],
            "nifty500_ret_3m": n500["ret_3m"],
            "nifty500_ret_6m": n500["ret_6m"],
            "nifty500_ret_ytd": n500["ret_ytd"],
            "nifty500_ret_1y": n500["ret_1y"],
            "source": "NSE",
            "source_url": url,
            "scraped_at": now_iso(),
            "status": status,
        },
        "month",
    )


def compute_sectors(conn, month: str, as_of: str, status: str) -> None:
    n500 = returns_for(conn, NIFTY_500, as_of)
    url = "https://nsearchives.nseindia.com/content/indices/"
    fpi_by_name = {
        r["sector"]: r["equity_net"]
        for r in conn.execute(
            "SELECT sector, equity_net FROM sector_fpi_flows WHERE month=? AND period_type='monthly'",
            (month,),
        )
    }
    fpi_values = [v for v in fpi_by_name.values() if v is not None]
    fpi_scale = max((abs(v) for v in fpi_values), default=0) or 1

    for spec in SECTORS:
        name, index, fpi_name = spec["name"], spec["index"], spec["fpi"]
        rets = returns_for(conn, index, as_of)
        upsert(
            conn,
            "sector_performance",
            {
                "month": month,
                "as_of_date": as_of,
                "sector": name,
                "close": rets["close"],
                "ret_1w": rets["ret_1w"],
                "ret_1m": rets["ret_1m"],
                "ret_3m": rets["ret_3m"],
                "ret_6m": rets["ret_6m"],
                "ret_ytd": rets["ret_ytd"],
                "ret_1y": rets["ret_1y"],
                "source": "NSE",
                "source_url": url,
                "scraped_at": now_iso(),
                "status": status,
            },
            "month, sector",
        )
        vs1 = None if rets["ret_1m"] is None or n500["ret_1m"] is None else rets["ret_1m"] - n500["ret_1m"]
        vs3 = None if rets["ret_3m"] is None or n500["ret_3m"] is None else rets["ret_3m"] - n500["ret_3m"]
        upsert(
            conn,
            "sector_relative_strength",
            {
                "month": month,
                "as_of_date": as_of,
                "sector": name,
                "vs_nifty500_1m": vs1,
                "vs_nifty500_3m": vs3,
                "source": "NSE",
                "source_url": url,
                "scraped_at": now_iso(),
                "status": status,
            },
            "month, sector",
        )
        inst = fpi_by_name.get(fpi_name)
        inst_score = None if inst is None else _clip(50 + 50 * (inst / fpi_scale), 0, 100)
        price_score = _price_score(rets["ret_1m"], rets["ret_3m"])
        rs_score = None if vs1 is None else _clip(50 + vs1 * 6, 0, 100)
        score, used = _weighted_score(
            {
                "institutional": inst_score,
                "price": price_score,
                "rs": rs_score,
            }
        )
        signal = classify_signal(score)
        category = classify_category(score, inst_score, price_score)
        upsert(
            conn,
            "sector_money_flow_score",
            {
                "month": month,
                "as_of_date": as_of,
                "sector": name,
                "score": score,
                "institutional_score": inst_score,
                "price_score": price_score,
                "rs_score": rs_score,
                "signal": signal,
                "category": category,
                "source": "computed",
                "source_url": None,
                "scraped_at": now_iso(),
                "status": status,
            },
            "month, sector",
        )
    conn.commit()


def _price_score(r1, r3) -> float | None:
    if r1 is None and r3 is None:
        return None
    if r1 is None:
        return _clip(50 + r3 * 2.2, 0, 100)
    if r3 is None:
        return _clip(50 + r1 * 3.5, 0, 100)
    return _clip(50 + r1 * 2.2 + r3 * 0.8, 0, 100)


def _weighted_score(parts: dict) -> tuple[float | None, dict]:
    present = {k: v for k, v in parts.items() if v is not None}
    if not present:
        return None, present
    wsum = sum(WEIGHTS[k] for k in present)
    score = sum(present[k] * WEIGHTS[k] for k in present) / wsum
    return round(score, 1), present


def _clip(val, lo, hi) -> float:
    return float(max(lo, min(hi, val)))


def classify_signal(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 80:
        return "Strong Inflow"
    if score >= 65:
        return "Improving"
    if score >= 45:
        return "Neutral"
    if score >= 30:
        return "Distribution"
    return "Strong Outflow"


def classify_category(score, inst, price) -> str | None:
    if score is None:
        return None
    if score >= 80 or (score >= 70 and (inst or 0) >= 60 and (price or 0) >= 60):
        return "MONEY_IN"
    if (inst or 0) >= 65 and (price or 50) < 55 and score >= 50:
        return "ACCUMULATION"
    if score < 30:
        return "MONEY_OUT"
    if score < 45 or (price or 50) < 40:
        return "DISTRIBUTION"
    return "WATCH"


def rotation_label(score: float | None, prev: float | None) -> str:
    if score is None:
        return "—"
    if score >= 80:
        return "Very Strong"
    if score >= 65:
        return "Strong"
    if score >= 50 and prev is not None and score > prev + 3:
        return "Improving"
    if score >= 45:
        return "Neutral"
    return "Weak"


def market_regime(conn, month: str) -> str:
    perf = conn.execute("SELECT * FROM market_performance WHERE month=?", (month,)).fetchone()
    fpi = conn.execute(
        "SELECT net_flow FROM institutional_flows WHERE month=? AND category='FPI'", (month,)
    ).fetchone()
    dii = conn.execute(
        "SELECT net_flow FROM institutional_flows WHERE month=? AND category='DII' AND source='AMFI'",
        (month,),
    ).fetchone()
    pos = 0
    neg = 0
    if perf and perf["nifty500_ret_1m"] is not None:
        pos += perf["nifty500_ret_1m"] > 0
        neg += perf["nifty500_ret_1m"] < 0
    if perf and perf["nifty50_ret_1m"] is not None:
        pos += perf["nifty50_ret_1m"] > 0
        neg += perf["nifty50_ret_1m"] < 0
    dii_net = dii["net_flow"] if dii else None
    fpi_net = fpi["net_flow"] if fpi else None
    if dii_net is not None:
        pos += dii_net > 0
        neg += dii_net < 0
    if fpi_net is not None:
        pos += fpi_net > 0
        neg += fpi_net < -10000
    if pos >= 3 and pos > neg:
        return "Risk-On"
    if neg >= 3 and neg > pos:
        return "Risk-Off"
    return "Mixed"
