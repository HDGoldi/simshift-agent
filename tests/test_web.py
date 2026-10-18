"""Web API tests with the fake decider (no model server needed)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from web.server import FakeDecider, create_app

client = TestClient(create_app(FakeDecider()))


def test_health_flags_fake():
    h = client.get("/api/health").json()
    assert h["decider"] == "up" and h["fake"] is True


def test_index_and_static_served():
    assert "SIMULATED FLEET" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_brazil_flow_with_human_approval():
    s = client.post("/api/incidents", json={"scenario": "profile_recovery"}).json()
    # FakeDecider picks first allowed: investigate_device, then investigate_data_path, then evaluate_profile_change
    for _ in range(3):
        s = client.post(f"/api/incidents/{s['id']}/step").json()
    assert s["steps"][-1]["choice"] == "evaluate_profile_change"
    assert s["awaiting_approval"] is True
    assert client.post(f"/api/incidents/{s['id']}/step").status_code == 409  # cannot skip the human
    s = client.post(f"/api/incidents/{s['id']}/approval", json={"approved": True}).json()
    assert s["outcome"]["restored"] and s["euicc"]["enabled"] == "profile_B" and s["done"]
    assert all(g["ok"] for g in s["guards"])


def test_offline_force_is_blocked_on_clone():
    r = client.post("/api/force-profile-change", json={"scenario": "unreachable_device"}).json()
    assert r["result"]["executed"] is False
    assert "no reachable management path" in r["result"]["blocked_reasons"]


def test_counterfactual_validates_actions():
    assert client.post("/api/counterfactual", json={"scenario": "profile_recovery", "actions": ["rm -rf"]}).status_code == 422
    r = client.post("/api/counterfactual", json={"scenario": "application_failure",
                                                 "actions": ["evaluate_profile_change"]}).json()
    assert r["outcome"]["unnecessary_profile_changes"] == 1


def test_snapshot_never_contains_hidden_truth():
    from simulator import scenarios

    for name in scenarios.names():
        s = client.post("/api/incidents", json={"scenario": name}).json()
        s = client.post(f"/api/incidents/{s['id']}/step").json()
        assert scenarios.load(name)["evaluator_only"]["true_cause"] not in str(s)
