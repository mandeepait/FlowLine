# Flowline

Indian cash-market **money flow & sector rotation** dashboard.

Answers: **where is money flowing, and which sectors are gaining strength?**

Light stack: Python, Flask, PostgreSQL (Supabase), vanilla HTML.

How data is fetched, stored, scored, and shown: **[docs/how-it-works.md](docs/how-it-works.md)**.

## Run

Copy `.env.example` to `.env` and set the Postgres host/password. Then:

```bash
cd "/Users/mandeepsingh/My Business/Flowline"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5050](http://127.0.0.1:5050). The dashboard only **reads Postgres** through JSON APIs (`/api/meta`, `/api/market`, `/api/sectors`, `/api/fpi`, `/api/chart`, `/api/sector/...`).

Scraping is separate — it writes into the database and is not part of page load:

```bash
python scrape.py
```

Or click **🔄 Update Market Data** (same job, `/api/scrape`).

Check the database:

```bash
python db.py
```

All scraped data is stored in Postgres. Downloads are parsed in memory. Historical months marked `FINAL` and trading days already in the database are skipped; only gaps and the current month are refreshed. Stock-level bhavcopy data is not stored.

## Sources

| Dataset | Source | Notes |
| --- | --- | --- |
| FPI / FII (market chip) | NSDL year-wise + monthly | Never summed from NSE FII cash. |
| Sector FPI | NSDL fortnightly sector report | One industry figure; sibling Nifty rows point at the owner. |
| DII (market chip) | AMFI Monthly Note PDFs | UI shows this monthly figure only. NSE tape is stored daily, not shown as the month. |
| FII cash tape | NSE `fiidiiTradeReact` | Rolled up as `FII_CASH` only; does not overwrite NSDL FPI. |
| Mutual funds / SIP | AMFI monthly Excel + AMFI SIP page | Published after month-end. |
| Sector / Nifty returns | NSE `ind_close_all` | Official index closes. |

Missing official data is left blank. Failed scrapes keep the last valid row.

## Monthly rules

- Historical month already `FINAL` → skip.
- Current month → always refresh, stored as `PARTIAL` with `as_of_date`.
- Future months → ignored.
- When a month is complete, status becomes `FINAL`.

Start month is `START_MONTH` in `config.py` (default `2026-01`).
