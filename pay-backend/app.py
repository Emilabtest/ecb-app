"""Owner-side PayMongo relay for Leiturgia license activation.

This tiny Flask service holds the PayMongo LIVE secrets (via environment
variables) so customer machines never see them. The local Leiturgia server
proxies its /api/pay/* calls here when `paymongo_backend` is configured.

Endpoints:
  GET  /api/health            -> {"ok": true}
  POST /api/pay/create        -> creates a QRPh PaymentIntent (fixed price)
  GET  /api/pay/status?id=PI  -> payment status for a PI we created

Env:
  PM_SK_LIVE / PM_PK_LIVE   PayMongo live keys (or *_TEST for the sandbox)
  LICENSE_PRICE_PESO        fixed license price (default 500)
  PM_BACKEND_AUTH           shared secret the client sends as X-Auth
"""
import base64
import os
import time
import urllib.parse

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

SK = (os.environ.get("PM_SK_LIVE") or os.environ.get("PM_SK_TEST") or "").strip()
PK = (os.environ.get("PM_PK_LIVE") or os.environ.get("PM_PK_TEST") or "").strip()
AUTH = (os.environ.get("PM_BACKEND_AUTH") or "").strip()
try:
    PRICE_PESO = int(os.environ.get("LICENSE_PRICE_PESO") or 500)
except ValueError:
    PRICE_PESO = 500

API = "https://api.paymongo.com/v1"

_created = {}  # pi_id -> {'hwid': str, 'ts': float} in-memory; fine for a poll session


def _pm_headers(key):
    tok = base64.b64encode((key + ":").encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + tok}


def _auth_ok():
    if not AUTH:
        return True
    return request.headers.get("X-Auth", "") == AUTH


@app.errorhandler(404)
def _nf(_e):
    return jsonify(ok=False, message="not found"), 404


@app.get("/api/health")
def _health():
    return jsonify(ok=True, live=bool(SK and SK.startswith("sk_live_")))


@app.post("/api/pay/create")
def _create():
    if not _auth_ok():
        return jsonify(ok=False, message="forbidden"), 403
    if not SK or not PK:
        return jsonify(ok=False, message="pay not configured on backend"), 500
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    hwid = (data.get("hwid") or "").strip()
    if not hwid:
        return jsonify(ok=False, message="missing hwid")
    if PRICE_PESO <= 0:
        return jsonify(ok=False, message="price not set on backend")
    try:
        r = requests.post(API + "/payment_intents", headers=_pm_headers(SK), timeout=30,
                          json={"data": {"attributes": {
                              "amount": PRICE_PESO * 100, "currency": "PHP",
                              "description": "Leiturgia license for PC-%s" % hwid[:12],
                              "payment_method_allowed": ["qrph"],
                              "metadata": {"hwid": hwid}}}})
        j = r.json()
        if r.status_code >= 400:
            return jsonify(ok=False, message="PayMongo error: %s" % str(j.get("errors"))[:400])
        pi = (j.get("data") or {}).get("id")
        ck = ((j.get("data") or {}).get("attributes") or {}).get("client_key")
        r = requests.post(API + "/payment_methods", headers=_pm_headers(PK), timeout=30,
                          json={"data": {"attributes": {"type": "qrph"}}})
        if r.status_code >= 400:
            return jsonify(ok=False, message="PayMongo error: %s" % str(r.json().get("errors"))[:400])
        pm = (r.json().get("data") or {}).get("id")
        r = requests.post(API + "/payment_intents/%s/attach" % pi, headers=_pm_headers(PK),
                          timeout=30, json={"data": {"attributes": {"payment_method": pm,
                                                                    "client_key": ck}}})
        j = r.json()
        if r.status_code >= 400:
            return jsonify(ok=False, message="PayMongo error: %s" % str(j.get("errors"))[:400])
        att = ((j.get("data") or {}).get("attributes") or {})
        code = ((att.get("next_action") or {}).get("code") or {})
    except requests.RequestException as e:
        return jsonify(ok=False, message="PayMongo connection error: %s" % e)
    qr = code.get("image_url") or ""
    if not pi or not qr:
        return jsonify(ok=False, message="could not start QR payment")
    _created[pi] = {"hwid": hwid, "ts": time.time()}
    # prune old entries (10 min stale)
    now = time.time()
    for _k in [k for k, v in _created.items() if now - v["ts"] > 600]:
        _created.pop(_k, None)
    return jsonify(ok=True, id=pi, qr_image=qr, test_url=code.get("test_url") or "")


@app.get("/api/pay/status")
def _status():
    if not _auth_ok():
        return jsonify(ok=False, message="forbidden"), 403
    pid = (request.args.get("id") or "").strip()
    if not pid or pid not in _created:
        return jsonify(paid=False, message="unknown session")
    if not SK:
        return jsonify(paid=False, message="not configured")
    try:
        r = requests.get(API + "/payment_intents/" + urllib.parse.quote(pid, safe=""),
                         headers=_pm_headers(SK), timeout=25)
        st = ((r.json().get("data") or {}).get("attributes") or {}).get("status", "")
    except requests.RequestException:
        return jsonify(paid=False, message="status check failed")
    return jsonify(paid=st in ("succeeded", "paid"), status=st)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5010")), debug=False)