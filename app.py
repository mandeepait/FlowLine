import json
from datetime import datetime

from flask import Flask, Response, abort, jsonify, render_template, request

from config import APP_NAME, APP_TAGLINE
from db import init_db
from deals import fetch_deals_sync, run_deal_fetch, start_daily_scheduler, today_ist
from engine import run_update
from queries import (
    chart_payload,
    daily_flows_payload,
    deals_fetch_history_payload,
    deals_list_payload,
    deals_stats_payload,
    deals_stock_payload,
    fpi_payload,
    market_payload,
    meta_payload,
    sector_by_slug,
    sector_payload,
    sectors_payload,
)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


@app.before_request
def _ensure_db():
    init_db()


@app.context_processor
def inject_brand():
    return {"app_name": APP_NAME, "app_tagline": APP_TAGLINE}


def _month():
    return request.args.get("month")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/deals")
def deals_page():
    return render_template("deals.html")


@app.route("/deals/<symbol>")
def deal_stock_page(symbol):
    data = deals_stock_payload(symbol)
    if not data:
        abort(404)
    return render_template("deal_stock.html", symbol=data["symbol"], company=data["company_name"])


@app.route("/sector/<slug>")
def sector(slug):
    if not sector_by_slug(slug):
        abort(404)
    return render_template("sector.html", slug=slug)


@app.route("/api/meta")
def api_meta():
    return jsonify(meta_payload(_month()))


@app.route("/api/market")
def api_market():
    return jsonify(market_payload(_month()))


@app.route("/api/sectors")
def api_sectors():
    return jsonify(sectors_payload(_month()))


@app.route("/api/fpi")
def api_fpi():
    return jsonify(fpi_payload(_month()))


@app.route("/api/flows/daily")
def api_daily_flows():
    kind = request.args.get("kind") or "fpi"
    return jsonify(daily_flows_payload(_month(), kind))


@app.route("/api/chart")
def api_chart():
    return jsonify(chart_payload(_month()))


@app.route("/api/sector/<slug>")
def api_sector(slug):
    name = sector_by_slug(slug)
    if not name:
        abort(404)
    data = sector_payload(name, _month())
    if not data:
        abort(404)
    return jsonify(data)


@app.route("/api/scrape")
@app.route("/api/update")
def scrape():
    def gen():
        for event in run_update():
            yield f"data: {json.dumps(event)}\n\n"

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _date_arg(val, fallback=None):
    if not val:
        return fallback
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except ValueError:
        abort(400)


def _deal_range():
    payload = request.get_json(silent=True) or {}
    src = payload if request.method == "POST" and payload else request.args
    today = today_ist()
    start = _date_arg(src.get("fromDate") or src.get("from"), today)
    end = _date_arg(src.get("toDate") or src.get("to"), start)
    if end < start:
        abort(400)
    if (end - start).days > 365:
        abort(400)
    exchange = (src.get("exchange") or "ALL").upper()
    deal_type = (src.get("dealType") or src.get("deal_type") or "ALL").upper()
    return start, end, exchange, deal_type


def _sse(gen):
    def stream():
        for event in gen:
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/deals/fetch/today", methods=["GET", "POST"])
def api_deals_fetch_today():
    today = today_ist()
    if request.method == "GET":
        return _sse(run_deal_fetch(today, today, "ALL", "ALL"))
    result = fetch_deals_sync(today, today, "ALL", "ALL")
    code = 409 if result.get("text") == "A deal fetch is already running" else 200
    return jsonify(result), code


@app.route("/api/deals/fetch", methods=["GET", "POST"])
def api_deals_fetch():
    start, end, exchange, deal_type = _deal_range()
    if request.method == "GET":
        return _sse(run_deal_fetch(start, end, exchange, deal_type))
    result = fetch_deals_sync(start, end, exchange, deal_type)
    code = 409 if result.get("text") == "A deal fetch is already running" else 200
    return jsonify(result), code


@app.route("/api/deals")
def api_deals():
    return jsonify(deals_list_payload(request.args))


@app.route("/api/deals/stats")
def api_deals_stats():
    return jsonify(deals_stats_payload(request.args))


@app.route("/api/deals/fetch-history")
def api_deals_fetch_history():
    limit = int(request.args.get("limit") or 40)
    return jsonify(deals_fetch_history_payload(limit))


@app.route("/api/deals/stock/<symbol>")
def api_deals_stock(symbol):
    data = deals_stock_payload(symbol)
    if not data:
        abort(404)
    return jsonify(data)


if __name__ == "__main__":
    import os

    init_db()
    start_daily_scheduler()
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
