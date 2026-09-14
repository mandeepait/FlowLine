# How Flowline works

Flowline is a monthly Indian cash-market **money-flow and sector-rotation** dashboard. It answers: where is money flowing, and which Nifty sectors have both flow and price on their side?

It does not trade, scrape stocks, or invent numbers. It pulls a small set of **official** reports, stores them in Postgres, and the website only reads that database.

---

## Principles

1. **Pages never scrape.** Opening the dashboard hits JSON APIs that `SELECT` from Postgres. Fresh data arrives only from **Update Market Data** or `python scrape.py`.
2. **Official sources only.** NSDL, NSE, AMFI. No Moneycontrol, ScanX, or similar aggregators as source of truth.
3. **Do not mix series.** NSDL FPI is not NSE FII cash. AMFI monthly DII is not the NSE one-session tape.
4. **Missing official data stays blank (`—`).** We do not fill gaps with a daily tape, a sibling sector, or a guess.
5. **Indexes, not stocks.** Price history is Nifty 50, Nifty 500, and 18 sector indexes. There are no stock tables.

Coverage starts at `START_MONTH` in `config.py` (currently `2026-01`). Timezone for “today” and the current month is **Asia/Kolkata**.

---

## Architecture

Two jobs that never mix:

```
Official sites  →  scrape job  →  Postgres (Supabase)
                                      ↓
                              Flask JSON APIs
                                      ↓
                           Browser (vanilla HTML/JS)
```

| Layer | Role |
| --- | --- |
| `app.py` | Flask shell: `/`, `/sector/<slug>`, JSON APIs, SSE scrape endpoint |
| `static/app.js` | Fetches APIs, renders chips / table / charts |
| `queries.py` | Read-only payloads for the UI |
| `engine.py` | One locked update job; streams progress |
| `nse.py` / `nsdl.py` / `amfi.py` | Fetch and parse official files |
| `compute.py` | Returns, relative strength, sector score, market regime |
| `db.py` | Schema, upsert, skip-if-FINAL |

Runtime data lives in **Supabase Postgres**. A local SQLite file is only a one-time copy source, not what the app reads.

---

## Running and refreshing

```bash
python app.py          # dashboard at http://127.0.0.1:5050
python scrape.py       # same update job as the UI button
```

**Update Market Data** opens `/api/scrape` (Server-Sent Events). Only one update can run at a time.

Historical months already marked `FINAL` are skipped. The **current IST month** is always refreshed and stored as `PARTIAL` until the month (and its reports) are complete.

---

## Where each number comes from

### Market chip: FPI / FII net

- **Source:** NSDL (not NSE).
- **Pages:** [Year-wise FPI](https://www.fpi.nsdl.co.in/web/Reports/Yearwise.aspx?RptType=6) and [Monthly](https://www.fpi.nsdl.co.in/web/Reports/Monthly.aspx).
- **Stored as:** `institutional_flows` where `category='FPI'`, `source='NSDL'`.
- **Meaning:** Official foreign-portfolio **equity** net for that calendar month (₹ crore).

NSE’s cash-market FII tape is a different series. Those days are stored separately and rolled up as `FII_CASH` so they **never overwrite** NSDL FPI.

### Market chip: DII net

- **Source:** [AMFI Monthly Notes](https://www.amfiindia.com/otherdata/amfi-monthlynote) (PDF).
- **Stored as:** `institutional_flows` where `category='DII'`, `source='AMFI'`.
- **Meaning:** The note’s DII equity sentence (“bought / acquired / buying equities worth Rs … crore”).
- **UI:** That month’s figure plus a last-four-month trail. Caption: “AMFI monthly note”.

There is **no official DII-by-sector**. Sector pages show this figure as **market-wide** only.

The NSE `fiidiiTradeReact` endpoint is still saved **day-wise** (`institutional_flow_daily`) but is **not** shown as the month. A one-day tape must not be presented as monthly DII.

### Market chip: Mutual funds equity net

- **Source:** AMFI monthly Excel (`https://portal.amfiindia.com/spages/am{mon}{year}repo.xls`) plus the AMFI SIP page.
- **Stored as:** `mutual_fund_flows`.
- **Meaning:** Equity-scheme net inflow for that month. Published after month-end, so the current month is often `—`.

### Sector FPI column

- **Source:** NSDL fortnightly sector-wise FPI report.
- **Stored as:** `sector_fpi_flows` (`period_type='monthly'`).
- **Meaning:** One **industry** net per month (e.g. Financial Services), not one number per Nifty index.

NSDL industries are coarser than Nifty sectors. Several Nifty rows share one industry. **Only one owner displays the rupee figure**; the others point at that owner so the same number is not repeated.

| NSDL industry | Shown on |
| --- | --- |
| Automobile and Auto Components | Auto |
| Financial Services | Financial Services (not Bank / PSU Bank / Private Bank) |
| Fast Moving Consumer Goods | FMCG (not Consumption) |
| Information Technology | IT |
| Media, Entertainment & Publication | Media |
| Metals & Mining | Metal (not Commodities) |
| Healthcare | Healthcare (not Pharma) |
| Realty | Realty |
| Oil, Gas & Consumable Fuels | Oil & Gas (not Energy) |
| Consumer Durables | Consumer Durables |
| Construction | Infra |

Owner map: `FPI_OWNERS` in `config.py`.

### Prices, 1M return, relative strength

- **Source:** NSE daily `ind_close_all_DDMMYYYY.csv` on nsearchives.
- **Stored as:** `daily_indices` (tracked indexes only).
- **Lookback:** about 400 calendar days (`PRICE_LOOKBACK_CAL_DAYS`).

Tracked indexes: Nifty 50, Nifty 500, and the 18 sector indexes listed in `SECTORS`.

---

## What the update job does (in order)

`engine.run_update()`:

1. **NSE index files** — Weekday CSVs into `daily_indices`. Days already stored are skipped; today can be refreshed.
2. **FPI** — NSDL year-wise equity net, then monthly buy/sell. Current month is often `PARTIAL`.
3. **DII** — Save today’s NSE tape to the daily table; roll NSE FII days to `FII_CASH` only; parse AMFI monthly-note PDFs into AMFI DII. Delete any leftover monthly DII that is not AMFI.
4. **Mutual funds** — AMFI XLS per month; skip months already `FINAL`.
5. **Sector FPI** — NSDL fortnightly files, rolled to a monthly industry net.
6. **Compute** (not a scrape) — From closes + FPI:
   - `market_performance` (Nifty 50 / 500 returns)
   - `sector_performance` (each sector index)
   - `sector_relative_strength` (sector 1M/3M minus Nifty 500)
   - `sector_money_flow_score` (0–100 score, signal, category)

Each dataset/month is tracked in `dataset_status` (`FINAL` / `PARTIAL`, source URL, `as_of_date`). Every run is logged in `scrape_runs`.

---

## What the UI shows

The HTML is an empty shell. After load, `app.js` calls:

| API | Used for |
| --- | --- |
| `/api/meta` | Month list, last update, scrape errors |
| `/api/market` | Regime + FPI / DII / MF chips |
| `/api/sectors` | Ranked table (score + FPI trails) |
| `/api/chart` | Monthly FPI, monthly score, weekly index returns |
| `/api/sector/<slug>` | One sector page |

Month comes from `?month=YYYY-MM`. Default is the latest month that already has sector scores.

### Market tab

- **Regime:** Risk-On / Mixed / Risk-Off (see scoring below).
- **FPI chip:** NSDL monthly equity net.
- **DII chip:** AMFI monthly note + 4-month trail (green/red vs previous month).
- **MF chip:** AMFI equity net.

### Charts tab

- Monthly NSDL **sector FPI** (₹ crore)
- Monthly **scores**
- Weekly **index returns** from week-end closes — there is no official weekly sector FPI

### Sectors tab

Ranked by score. Columns: rank, sector, signal, score + 4-month trail, FPI (or `via {owner}`).

### Sector page

Score, FPI (or pointer to the owner industry), market-wide DII word, 1M return vs own index, RS vs Nifty 500, TradingView symbol (`NSE:…`).

---

## Scoring (computed, not an exchange figure)

Weights in `config.WEIGHTS`:

| Component | Weight | Input |
| --- | --- | --- |
| Institutional | 43% | That sector’s NSDL FPI, scaled by the largest absolute FPI that month |
| Price | 35% | 1-month and 3-month return of the Nifty **sector index** |
| Relative strength | 22% | Sector 1M return minus Nifty 500 1M |

Missing parts are dropped and the remaining weights are renormalized.

**Signal** from the 0–100 score:

| Score | Signal |
| --- | --- |
| ≥ 80 | Strong Inflow |
| ≥ 65 | Improving |
| ≥ 45 | Neutral |
| ≥ 30 | Distribution |
| < 30 | Strong Outflow |

### Market regime

A simple vote (not a score):

- Nifty 50 1-month return sign
- Nifty 500 1-month return sign
- AMFI DII sign (skipped if no note yet)
- NSDL FPI: counts positive if net > 0; counts negative if net < −10,000 Cr

If at least three votes are positive and they beat negatives → **Risk-On**. If at least three are negative and they beat positives → **Risk-Off**. Otherwise **Mixed**.

A missing DII note does not count as a vote. September can look Risk-Off on FPI and index returns alone.

---

## Database (what we keep)

| Table | Contents |
| --- | --- |
| `daily_indices` | Official index closes (tracked indexes only) |
| `institutional_flows` | Monthly FPI (NSDL), DII (AMFI), FII_CASH (NSE rollup, not shown) |
| `institutional_flow_daily` | NSE FII/DII session rows; NSDL FPI daily buy/sell when present |
| `sector_fpi_flows` | NSDL industry FPI by month |
| `mutual_fund_flows` | AMFI equity / SIP / AUM |
| `market_performance` | Nifty 50 / 500 returns for the month’s last trading day |
| `sector_performance` | Sector-index returns |
| `sector_relative_strength` | vs Nifty 500 |
| `sector_money_flow_score` | Score, signal, category |
| `dataset_status` | FINAL / PARTIAL per dataset × month |
| `scrape_runs` | Update log |

---

## Why some cells are `—`

Reports are not published on calendar day 1.

| Series | Typical lag |
| --- | --- |
| NSE index closes | Next session (daily) |
| NSDL FPI / sector FPI | During or after the month; current month often partial |
| AMFI monthly note (DII) | After month-end (September 2026 has no note yet) |
| AMFI mutual-fund XLS | After month-end |

January 2026’s AMFI note has no parseable DII rupee figure, so that month stays blank rather than falling back to NSE.

Trail pills still show **published** months next to a dash for the unpublished one.

---

## What Flowline does not do

- Scrape or store individual stocks / bhavcopy
- Treat NSE’s one-day FII/DII page as “the month”
- Mix NSE FII cash into the FPI chip
- Invent DII for Auto, Banks, IT, etc.
- Repeat the same NSDL FPI on Bank, PSU Bank, and Private Bank
- Use unofficial websites as the source of truth

---

## Code map

| File | Responsibility |
| --- | --- |
| `config.py` | URLs, sector list, FPI owners, weights, `START_MONTH` |
| `app.py` | HTTP routes |
| `engine.py` | Update orchestration |
| `nse.py` | Index CSVs + NSE FII/DII daily |
| `nsdl.py` | FPI year-wise, monthly, sector fortnightly |
| `amfi.py` | MF Excel, SIP page, DII monthly-note PDFs |
| `compute.py` | Returns, score, regime |
| `queries.py` | API payloads |
| `db.py` | Postgres schema and helpers |
| `net.py` | HTTP client (NSE session, timeouts) |
| `static/app.js` | UI |
| `templates/` | Page shells |

---

## One-line summary

Official monthly flow (NSDL FPI, AMFI DII, AMFI mutual funds) plus official NSE index closes are stored in Postgres, scored into a sector ranking, and the site only reads that.
