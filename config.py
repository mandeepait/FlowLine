import os
import re
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# One-time copy source only. Runtime data lives in Postgres.
SQLITE_PATH = ROOT / "data" / "market.db"


def _database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        if "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
        return url
    host = os.environ.get("PGHOST", "").strip()
    user = os.environ.get("PGUSER", "postgres").strip()
    password = os.environ.get("PGPASSWORD", "")
    port = os.environ.get("PGPORT", "5432").strip()
    name = os.environ.get("PGDATABASE", "postgres").strip()
    if not host:
        return ""
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{name}?sslmode=require"
    )


DATABASE_URL = _database_url()

APP_NAME = "Flowline"
APP_TAGLINE = "Where is the money flowing?"

IST = ZoneInfo("Asia/Kolkata")
START_MONTH = "2026-01"
PRICE_LOOKBACK_CAL_DAYS = 400

NSDL_BASE = "https://www.fpi.nsdl.co.in/web"
NSDL_YEARWISE = f"{NSDL_BASE}/Reports/Yearwise.aspx?RptType=6"
NSDL_MONTHLY = f"{NSDL_BASE}/Reports/Monthly.aspx"
NSDL_FORTNIGHTLY = f"{NSDL_BASE}/Reports/FPI_Fortnightly_Selection.aspx"
NSDL_STATIC = f"{NSDL_BASE}/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data"

NSE_HOME = "https://www.nseindia.com/"
NSE_ARCHIVES = "https://nsearchives.nseindia.com"
NSE_FII_DII = "https://www.nseindia.com/api/fiidiiTradeReact"
NSE_ALL_INDICES = "https://www.nseindia.com/api/allIndices"
NSE_LARGE_DEAL_SNAP = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
NSE_LARGE_DEAL_HIST = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
NSE_LARGE_DEAL_PAGE = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
NSE_QUOTE_EQUITY = "https://www.nseindia.com/api/quote-equity"
NSE_PREOPEN_FO = "https://www.nseindia.com/api/market-data-pre-open?key=FO"
NSE_BULK_CSV = f"{NSE_ARCHIVES}/content/equities/bulk.csv"
NSE_BLOCK_CSV = f"{NSE_ARCHIVES}/content/equities/block.csv"
NSE_SHORT_CSV = f"{NSE_ARCHIVES}/content/equities/ShortSelling.csv"
NSE_INDEX_LIST = f"{NSE_ARCHIVES}/content/indices"
BSE_HOME = "https://www.bseindia.com/"
BSE_BULK_PAGE = "https://beta.bseindia.com/markets/equity/EQReports/bulk_deals.aspx"
BSE_BLOCK_PAGE = "https://beta.bseindia.com/markets/equity/EQReports/block_deals.aspx"

AMFI_MONTHLY_PAGE = "https://www.amfiindia.com/research-information/amfi-monthly"
AMFI_MONTHLY_NOTE = "https://www.amfiindia.com/otherdata/amfi-monthlynote"
AMFI_SIP_PAGE = "https://www.amfiindia.com/mutual-fund"
AMFI_XLS = "https://portal.amfiindia.com/spages/am{mon}{year}repo.xls"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# NSE index name -> constituent file on nsearchives, NSDL FPI sector name
SECTORS = [
    {"name": "Auto", "index": "Nifty Auto", "list": "ind_niftyautolist.csv", "fpi": "Automobile and Auto Components"},
    {"name": "Bank", "index": "Nifty Bank", "list": "ind_niftybanklist.csv", "fpi": "Financial Services"},
    {"name": "Financial Services", "index": "Nifty Financial Services", "list": "ind_niftyfinancelist.csv", "fpi": "Financial Services"},
    {"name": "FMCG", "index": "Nifty FMCG", "list": "ind_niftyfmcglist.csv", "fpi": "Fast Moving Consumer Goods"},
    {"name": "IT", "index": "Nifty IT", "list": "ind_niftyitlist.csv", "fpi": "Information Technology"},
    {"name": "Media", "index": "Nifty Media", "list": "ind_niftymedialist.csv", "fpi": "Media, Entertainment & Publication"},
    {"name": "Metal", "index": "Nifty Metal", "list": "ind_niftymetallist.csv", "fpi": "Metals & Mining"},
    {"name": "Pharma", "index": "Nifty Pharma", "list": "ind_niftypharmalist.csv", "fpi": "Healthcare"},
    {"name": "Healthcare", "index": "Nifty Healthcare", "list": "ind_niftyhealthcarelist.csv", "fpi": "Healthcare"},
    {"name": "Realty", "index": "Nifty Realty", "list": "ind_niftyrealtylist.csv", "fpi": "Realty"},
    {"name": "Energy", "index": "Nifty Energy", "list": "ind_niftyenergylist.csv", "fpi": "Oil, Gas & Consumable Fuels"},
    {"name": "Oil & Gas", "index": "Nifty Oil & Gas", "list": "ind_niftyoilgaslist.csv", "fpi": "Oil, Gas & Consumable Fuels"},
    {"name": "Consumer Durables", "index": "Nifty Consumer Durables", "list": "ind_niftyconsumerdurableslist.csv", "fpi": "Consumer Durables"},
    {"name": "PSU Bank", "index": "Nifty PSU Bank", "list": "ind_niftypsubanklist.csv", "fpi": "Financial Services"},
    {"name": "Private Bank", "index": "Nifty Private Bank", "list": "ind_nifty_privatebanklist.csv", "fpi": "Financial Services"},
    {"name": "Infra", "index": "Nifty Infra", "list": "ind_niftyinfralist.csv", "fpi": "Construction"},
    {"name": "Commodities", "index": "Nifty Commodities", "list": "ind_niftycommoditieslist.csv", "fpi": "Metals & Mining"},
    {"name": "Consumption", "index": "Nifty Consumption", "list": "ind_niftyconsumptionlist.csv", "fpi": "Fast Moving Consumer Goods"},
]

# One Nifty sector displays each NSDL FPI industry. The rest share that bucket
# and must not repeat the same figure (Bank / PSU Bank / Private Bank → Financial Services).
FPI_OWNERS = {
    "Automobile and Auto Components": "Auto",
    "Financial Services": "Financial Services",
    "Fast Moving Consumer Goods": "FMCG",
    "Information Technology": "IT",
    "Media, Entertainment & Publication": "Media",
    "Metals & Mining": "Metal",
    "Healthcare": "Healthcare",
    "Realty": "Realty",
    "Oil, Gas & Consumable Fuels": "Oil & Gas",
    "Consumer Durables": "Consumer Durables",
    "Construction": "Infra",
}

NIFTY_50 = "Nifty 50"
NIFTY_500 = "Nifty 500"
TRACKED_INDEXES = tuple(dict.fromkeys([NIFTY_50, NIFTY_500, *[s["index"] for s in SECTORS]]))

# Compact tickers for NSE / TradingView charts (NSE:SYMBOL)
INDEX_SYMBOLS = {
    "Nifty 50": "NIFTY",
    "Nifty 500": "CNX500",
    "Nifty Auto": "NIFTYAUTO",
    "Nifty Bank": "NIFTYBANK",
    "Nifty Financial Services": "NIFTYFINSERVICE",
    "Nifty FMCG": "NIFTYFMCG",
    "Nifty IT": "CNXIT",
    "Nifty Media": "NIFTYMEDIA",
    "Nifty Metal": "NIFTYMETAL",
    "Nifty Pharma": "NIFTYPHARMA",
    "Nifty Realty": "NIFTYREALTY",
    "Nifty Energy": "NIFTYENERGY",
    "Nifty Healthcare": "NIFTYHEALTHCARE",
    "Nifty Consumer Durables": "NIFTYCONSDURBL",
    "Nifty Oil & Gas": "NIFTYOILANDGAS",
    "Nifty PSU Bank": "NIFTYPSUBANK",
    "Nifty Private Bank": "NIFTYPVTBANK",
    "Nifty Infra": "NIFTYINFRA",
    "Nifty Commodities": "NIFTYCOMMODITIES",
    "Nifty Consumption": "NIFTYCONSUMPTION",
    "India VIX": "INDIAVIX",
}


def compact_index_symbol(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (name or "").upper())[:24]


def symbol_for_index(name: str) -> str:
    return INDEX_SYMBOLS.get(name) or compact_index_symbol(name)


def index_chart_url(name: str) -> str:
    return f"https://www.tradingview.com/chart/?symbol=NSE:{symbol_for_index(name)}"

WEIGHTS = {
    "institutional": 0.43,
    "price": 0.35,
    "rs": 0.22,
}

AMFI_MONTH = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
