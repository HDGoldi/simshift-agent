"""SIMShift decision-trace UI backend (FastAPI). Binds to 127.0.0.1 only; no authentication.

    python -m web.server                  # real Decider at $STRANDS_DECIDER_URL (default :8099)
    python -m web.server --fake-decider   # UI development only; every screen says FAKE DECIDER
    open http://127.0.0.1:8090
"""

from __future__ import annotations

import argparse
import itertools
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.incident import Incident
from decider.recovery_decisions import OPTION_SPECS, QUESTION
from patterns.capability_aware_router import Decision, HttpDeciderClient
from simulator import scenarios
from simulator.twin import PROFILE_GUARDS, TOOL_NAMES, replay

STATIC = Path(__file__).parent / "static"
MAX_INCIDENTS = 50

GUARD_LABELS = {
    "eUICC does not support remote profile enable": "eUICC supports remote enable",
    "no alternate profile installed": "Alternate profile installed",
    "no reachable management path": "Management path reachable",
    "owner has not permitted profile changes": "Owner permits profile changes",
}


class FakeDecider:
    """UI development stand-in. Picks the first allowed option; flagged as fake everywhere."""

    def choose(self, state: Any, question: str, criteria: dict[str, str]) -> Decision:
        names = list(criteria)
        p = round(1 / len(names), 3)
        return Decision(choice=names[0], probabilities=dict.fromkeys(names, p), confidence=0.0,
                        latency_ms=0.0, model="FAKE-DECIDER (not a model)")

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "model": "FAKE-DECIDER (not a model)", "device": "none"}


class CreateIncident(BaseModel):
    scenario: str


class ApprovalBody(BaseModel):
    approved: bool


class CounterfactualBody(BaseModel):
    scenario: str
    actions: list[str]
    approve: bool = True


def create_app(decider: Any) -> FastAPI:
    app = FastAPI(title="SIMShift", docs_url=None, redoc_url=None)
    incidents: dict[int, Incident] = {}
    ids = itertools.count(1)
    lock = threading.Lock()

    def get(iid: int) -> Incident:
        inc = incidents.get(iid)
        if inc is None:
            raise HTTPException(404, "incident not found")
        return inc

    def snapshot(iid: int, inc: Incident) -> dict[str, Any]:
        t = inc.twin
        return {
            "id": iid,
            "scenario": inc.scenario,
            "question": QUESTION,
            "options": {n: {"description": d, "tool": TOOL_NAMES[n]} for n, (d, _) in OPTION_SPECS.items()},
            "observable": t.observe(),
            "state_text": scenarios.describe(t.observe()),
            "euicc": t.euicc,
            "guards": [{"check": GUARD_LABELS[r], "ok": bool(ok(t.obs))} for r, ok in PROFILE_GUARDS],
            "steps": inc.steps,
            "outcome": t.outcome(),
            "events": t.events,
            "awaiting_approval": inc.awaiting_approval,
            "done": inc.done,
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            h = decider.health()
            return {"decider": "up", "fake": isinstance(decider, FakeDecider), **h}
        except OSError as e:
            return {"decider": "down", "fake": False, "error": str(e)[:200]}

    @app.get("/api/scenarios")
    def list_scenarios() -> list[dict[str, Any]]:
        out = []
        for n in scenarios.names():
            o = scenarios.observe(n)
            out.append({"name": n, "id": scenarios.load(n)["id"], "incident": o["incident"],
                        "affected_devices": o["affected_devices"], "country": o.get("country")})
        return out

    @app.post("/api/incidents")
    def create(body: CreateIncident) -> dict[str, Any]:
        if body.scenario not in scenarios.names():
            raise HTTPException(404, "unknown scenario")
        with lock:
            iid = next(ids)
            incidents[iid] = Incident(body.scenario, decider, approve=None)
            for old in sorted(incidents)[:-MAX_INCIDENTS]:
                incidents.pop(old)
            return snapshot(iid, incidents[iid])

    @app.get("/api/incidents/{iid}")
    def read(iid: int) -> dict[str, Any]:
        return snapshot(iid, get(iid))

    @app.post("/api/incidents/{iid}/step")
    def step(iid: int) -> dict[str, Any]:
        inc = get(iid)
        with lock:
            if inc.awaiting_approval:
                raise HTTPException(409, "awaiting human approval")
            if inc.done:
                raise HTTPException(409, "incident finished")
            try:
                inc.step()
            except OSError as e:
                raise HTTPException(503, f"decider unavailable: {e}") from e
            return snapshot(iid, inc)

    @app.post("/api/incidents/{iid}/approval")
    def approval(iid: int, body: ApprovalBody) -> dict[str, Any]:
        inc = get(iid)
        with lock:
            if not inc.awaiting_approval:
                raise HTTPException(409, "nothing awaiting approval")
            inc.resolve_approval(body.approved)
            return snapshot(iid, inc)

    @app.post("/api/counterfactual")
    def counterfactual(body: CounterfactualBody) -> dict[str, Any]:
        if body.scenario not in scenarios.names():
            raise HTTPException(404, "unknown scenario")
        bad = [a for a in body.actions if a not in OPTION_SPECS]
        if bad or not body.actions or len(body.actions) > 6:
            raise HTTPException(422, "actions must be 1-6 known options")
        return replay(body.scenario, body.actions, approve=body.approve)

    @app.post("/api/force-profile-change")
    def force(body: CreateIncident) -> dict[str, Any]:
        """Counterfactual on a CLONE: an operator forces a profile change past the agent.
        The deterministic guards still apply; the live incident is untouched."""
        if body.scenario not in scenarios.names():
            raise HTTPException(404, "unknown scenario")
        from simulator.twin import Twin

        t = Twin.from_scenario(body.scenario)
        t.obs["profile_change_pending"] = True
        res = t.execute_profile_change(approved=True)
        return {"forced": True, "result": res, "outcome": t.outcome(), "events": t.events}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--fake-decider", action="store_true")
    a = ap.parse_args()
    import uvicorn

    decider = FakeDecider() if a.fake_decider else HttpDeciderClient()
    uvicorn.run(create_app(decider), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
