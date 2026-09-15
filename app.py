import json

from flask import Flask, Response, abort, jsonify, render_template, request

from config import APP_NAME, APP_TAGLINE
from db import init_db
from engine import run_update
from queries import (
    chart_payload,
    daily_flows_payload,
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


@app.context_processor
def inject_brand():
    return {"app_name": APP_NAME, "app_tagline": APP_TAGLINE}


def _month():
    return request.args.get("month")


@app.route("/")
def home():
    return render_template("index.html")


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


if __name__ == "__main__":
    import os

    init_db()
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
