"""UI backend over HTTP, on recorded real Decider answers (no Decider server, no AWS)."""
import http.client
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from simshift.simulator import SCENARIOS
from simshift.web import App, serve


@pytest.fixture(scope="module")
def base():
    runs = os.path.join(os.path.dirname(__file__), "..", "docs", "sample-runs", "orchestrated")
    srv = serve(App("http://127.0.0.1:1", replay_dir=runs), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, body=None):
    req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(),
                                 {"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_page_and_scenarios(base):
    assert b"Recovery Decision Inspector" in urllib.request.urlopen(base + "/").read()
    assert {s["id"] for s in call(base, "/api/scenarios")[1]} == set(SCENARIOS)


def test_brazil_waits_for_a_human_then_restores(base):
    _, s = call(base, "/api/incidents", {"scenario": "BR_PROFILE"})
    while not (s["done"] or s["pending_approval"]):
        s = call(base, f"/api/incidents/{s['id']}/step", {})[1]
    assert s["pending_approval"] and s["profiles"]["active"] == "profile_A" and s["gate"]["failed"] == ["human_approval"]
    assert call(base, f"/api/incidents/{s['id']}/step", {})[0] == 409
    _, s = call(base, f"/api/incidents/{s['id']}/approval", {"approved": True})
    assert s["done"] and s["outcome"]["restored"] and s["transition"][-1] == "SUCCEEDED"
    assert all(t["decision"] is None or t["decision"]["raw"].get("replayed") for t in s["trace"])


def test_offline_forced_profile_change_is_blocked_on_a_clone(base):
    _, s = call(base, "/api/incidents", {"scenario": "OFFLINE"})
    code, cf = call(base, f"/api/incidents/{s['id']}/counterfactual", {"option": "evaluate_profile_change"})
    assert code == 200 and cf["result"]["transition"] == ["REQUESTED", "BLOCKED"] and cf["excluded"]
    assert call(base, f"/api/incidents/{s['id']}")[1]["events"] == []  # live incident untouched


def test_snapshots_never_contain_hidden_truth(base):
    for sid, sc in SCENARIOS.items():
        _, s = call(base, "/api/incidents", {"scenario": sid})
        blobs = [json.dumps(s)]
        while not (s["done"] or s["pending_approval"]):
            s = call(base, f"/api/incidents/{s['id']}/step", {})[1]
            blobs.append(json.dumps(s))
        for secret in (sc["hidden"]["cause"], "best_actions", '"networks"', "ingestion_healthy", "firmware_fault",
                       "transient_congestion", "device_powered"):
            assert secret not in "".join(blobs), (sid, secret)


def test_bad_requests(base):
    assert call(base, "/api/incidents", {"scenario": "NOPE"})[0] == 404
    assert call(base, "/api/incidents/999")[0] == 404
    _, s = call(base, "/api/incidents", {"scenario": "OFFLINE"})
    assert call(base, f"/api/incidents/{s['id']}/approval", {"approved": True})[0] == 400
    assert call(base, f"/api/incidents/{s['id']}/explain", {})[0] == 409  # Bedrock off


def raw_post(base, path, body: bytes, headers: dict):
    host, port = base.removeprefix("http://").split(":")
    c = http.client.HTTPConnection(host, int(port), timeout=5)
    c.request("POST", path, body, headers)
    r = c.getresponse()
    return r.status, r.read()


def test_cross_origin_and_rebinding_requests_are_refused(base):
    ok = {"content-type": "application/json"}
    body = json.dumps({"scenario": "BR_PROFILE"}).encode()
    assert raw_post(base, "/api/incidents", body, {"content-type": "text/plain"})[0] == 403  # CORS-simple request
    assert raw_post(base, "/api/incidents", body, {**ok, "origin": "https://evil.example"})[0] == 403
    assert raw_post(base, "/api/incidents", body, {**ok, "host": "attacker.example:8090"})[0] == 403  # DNS rebinding
    assert raw_post(base, "/api/incidents", body, {**ok, "origin": base})[0] == 200  # the UI itself


def test_approval_must_be_a_literal_boolean(base):
    _, s = call(base, "/api/incidents", {"scenario": "BR_PROFILE"})
    while not (s["done"] or s["pending_approval"]):
        s = call(base, f"/api/incidents/{s['id']}/step", {})[1]
    for bad in ("false", "true", 1, None):
        assert call(base, f"/api/incidents/{s['id']}/approval", {"approved": bad})[0] == 400
    assert call(base, f"/api/incidents/{s['id']}")[1]["profiles"]["active"] == "profile_A"  # nothing executed


def test_malformed_bodies_get_an_http_error(base):
    ok = {"content-type": "application/json"}
    for body in (b"{not json", b"[1]", json.dumps({"scenario": ["x"]}).encode()):
        assert raw_post(base, "/api/incidents", body, ok)[0] == 400, body
