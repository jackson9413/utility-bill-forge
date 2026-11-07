"""Flask app for the Utility Bill Forge.

Local-first: no outbound network calls, no API keys, no LLM. The bill text you
paste stays on this machine.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from flask import Flask, Response, jsonify, render_template, request

from forge.engine import analyze
from forge.exporter import to_json, to_markdown
from forge.samples import SAMPLES
from forge.store import (
    delete_session,
    get_session,
    init_db,
    list_sessions,
    save_session,
    update_session,
)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

UTILITIES = [
    {"id": "auto", "label": "Detect automatically"},
    {"id": "electric", "label": "Electric"},
    {"id": "gas", "label": "Natural gas"},
    {"id": "water", "label": "Water / sewer"},
]

CUSTOMER_CLASSES = [
    {"id": "auto", "label": "Detect automatically"},
    {"id": "residential", "label": "Residential"},
    {"id": "commercial", "label": "Commercial / business"},
]

PROFILES = [
    {"id": "residential", "label": "Residential"},
    {"id": "commercial", "label": "Commercial / business"},
    {"id": "landlord", "label": "Landlord / property manager"},
]


@app.route("/")
def index():
    return render_template(
        "index.html",
        utilities=UTILITIES,
        customer_classes=CUSTOMER_CLASSES,
        profiles=PROFILES,
        samples=[{"id": s["id"], "title": s["title"], "note": s["note"]} for s in SAMPLES],
    )


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "1.0.0", "network": "none"})


@app.route("/api/samples")
def api_samples():
    return jsonify({"samples": SAMPLES})


@app.route("/api/sample/<sample_id>")
def api_sample(sample_id: str):
    for s in SAMPLES:
        if s["id"] == sample_id:
            return jsonify(s)
    return jsonify({"error": "sample not found"}), 404


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No bill text was provided."}), 400

    utility = payload.get("utility") or "auto"
    customer_class = payload.get("customer_class") or "auto"
    profile = payload.get("profile") or "residential"

    result = analyze(text, utility, customer_class, profile)
    if result.get("bill_count", 0) == 0:
        return jsonify({"error": result.get("error", "No bill content was found.")}), 400

    session_id = None
    try:
        session_id = save_session(result, text)
    except Exception:
        # A logging failure must never lose the analysis.
        session_id = None
    result["session_id"] = session_id
    return jsonify(result)


@app.route("/api/sessions")
def api_sessions():
    return jsonify({"sessions": list_sessions()})


@app.route("/api/sessions/<int:session_id>", methods=["GET", "PATCH", "DELETE"])
def api_session(session_id: int):
    if request.method == "DELETE":
        ok = delete_session(session_id)
        return jsonify({"deleted": ok}), (200 if ok else 404)
    if request.method == "PATCH":
        payload = request.get_json(silent=True) or {}
        row = update_session(session_id, payload.get("rating"), payload.get("notes"))
        if row is None:
            return jsonify({"error": "session not found"}), 404
        return jsonify(row)
    row = get_session(session_id)
    if row is None:
        return jsonify({"error": "session not found"}), 404
    return jsonify(row)


@app.route("/api/export/<int:session_id>")
def api_export(session_id: int):
    fmt = (request.args.get("fmt") or "md").lower()
    row = get_session(session_id)
    if row is None:
        return jsonify({"error": "session not found"}), 404
    result = row.get("result") or {}
    if fmt == "json":
        body = to_json(result)
        mimetype = "application/json"
        ext = "json"
    else:
        body = to_markdown(result)
        mimetype = "text/markdown"
        ext = "md"
    stamp = row.get("created_at", "").replace(":", "").replace("-", "")[:15]
    filename = "utility-bill-audit-{0}.{1}".format(stamp, ext)
    return Response(
        body,
        mimetype=mimetype,
        headers={"Content-Disposition": 'attachment; filename="{0}"'.format(filename)},
    )


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8787"))
    app.run(host="127.0.0.1", port=port, debug=False)
