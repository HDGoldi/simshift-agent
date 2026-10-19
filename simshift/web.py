"""SIMShift Recovery Decision Inspector: a local web UI over the same Incident the CLI runs.

    python -m simshift.web                              # live Decider at $DECIDER_URL (default :8099)
    python -m simshift.web --replay-dir docs/sample-runs/orchestrated  # recorded real Decider answers, no server
    python -m simshift.web --bedrock                    # also ask Bedrock to review plans and explain outcomes
    open http://127.0.0.1:8090

Binds to 127.0.0.1 only and has no authentication: a local demo, not a service. Requests must carry a local Host
header, and POSTs must be JSON from this origin, so another web page or a DNS-rebound name cannot drive it.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from patterns.capability_aware_router.router import DeciderClient, ReplayDecider

from .agent import QUESTION, TOOLS, Incident
from .policy import OPTIONS, counterfactual, profile_transition_gate
from .simulator import SCENARIOS

STATIC = Path(__file__).parent / "static"
MAX_INCIDENTS = 50


class App:
    def __init__(self, decider_url: str, replay_dir: str | None = None, use_bedrock: bool = False):
        self.decider_url, self.replay_dir, self.use_bedrock = decider_url, replay_dir, use_bedrock
        self.incidents: dict[int, tuple[Incident, threading.Lock, str]] = {}
        self.ids, self.lock = itertools.count(1), threading.Lock()

    def _decider(self, scenario: str):
        if not self.replay_dir:
            return DeciderClient(self.decider_url), f"live {self.decider_url}"
        path = os.path.join(self.replay_dir, f"{scenario}.json")
        with open(path) as f:
            return ReplayDecider([t["decision"] for t in json.load(f)["trace"]]), f"replay of {path}"

    def create(self, scenario: str) -> dict:
        if not isinstance(scenario, str):
            raise ValueError("scenario must be a string")
        if scenario not in SCENARIOS:
            raise LookupError("unknown scenario")
        decider, source = self._decider(scenario)
        inc = Incident(scenario, approve=False, decider=decider, use_bedrock=self.use_bedrock)
        with self.lock:
            iid = next(self.ids)
            self.incidents[iid] = (inc, threading.Lock(), source)
            for old in sorted(self.incidents)[:-MAX_INCIDENTS]:
                self.incidents.pop(old)
        return self.snapshot(iid)

    def get(self, iid: int) -> tuple[Incident, threading.Lock, str]:
        if iid not in self.incidents:
            raise LookupError("incident not found")
        return self.incidents[iid]

    def snapshot(self, iid: int) -> dict:
        inc, _, source = self.get(iid)
        twin = inc.twin
        target = next(p for p in twin.s["profiles"] if p != twin.s["active_profile"])
        last_gate = next((t["tool_result"] for t in reversed(inc.trace)
                          if isinstance(t["tool_result"], dict) and "gate" in t["tool_result"]), None)
        pending = inc.pending_approval
        return {"id": iid, "scenario": inc.scenario_id, "title": SCENARIOS[inc.scenario_id]["title"],
                "decider_source": source, "bedrock": self.use_bedrock, "question": QUESTION,
                "options": {o: {"description": d, "tool": TOOLS[o]} for o, d in OPTIONS.items()},
                "observable": twin.observe(), "profiles": twin.get_profiles(),
                "gate": last_gate["gate"] if last_gate else profile_transition_gate(twin, target, None),
                "transition": last_gate and last_gate.get("transition"),
                "bedrock_plan": last_gate and last_gate.get("bedrock_plan"),
                "trace": inc.trace, "outcome": inc.outcome(), "events": twin.events,
                "pending_approval": pending, "done": inc.done and not pending}

    def act(self, iid: int, action: str, body: dict) -> dict:
        inc, lock, _ = self.get(iid)
        with lock:  # one step at a time per incident; other incidents are not blocked
            if action == "step":
                if inc.pending_approval or inc.done:
                    raise PermissionError("awaiting human approval" if inc.pending_approval else "incident finished")
                inc.step()
            elif action == "approval":
                if not isinstance(body.get("approved"), bool):  # bool("false") is True: accept only true/false
                    raise ValueError("approved must be true or false")
                inc.resolve_approval(body["approved"])
            elif action == "counterfactual":
                if body.get("option") not in OPTIONS:
                    raise LookupError("unknown option")
                return counterfactual(inc.twin, body["option"])
            elif action == "explain":
                if not self.use_bedrock:
                    raise PermissionError("Bedrock is off; start the UI with --bedrock")
                return {"explanation": inc.result(explain=True)["explanation"]}
            else:
                raise LookupError("unknown action")
        return self.snapshot(iid)


def handler(app: App):
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, default=str).encode())

        def _local(self, post: bool) -> bool:
            hosts = {f"{h}:{self.server.server_address[1]}" for h in ("127.0.0.1", "localhost")}
            if self.headers.get("host") not in hosts:  # DNS rebinding sends a foreign Host
                return False
            if not post:
                return True
            origin = self.headers.get("origin")
            # A cross-site page can only send JSON after a CORS preflight, which this server never answers.
            return ((origin is None or origin.removeprefix("http://") in hosts)
                    and (self.headers.get("content-type") or "").startswith("application/json"))

        def do_GET(self):
            if not self._local(post=False):
                return self._json(403, {"error": "local requests only"})
            if self.path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if self.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if self.path in ("/app.js", "/style.css"):
                ctype = "text/javascript" if self.path.endswith(".js") else "text/css"
                return self._send(200, (STATIC / self.path[1:]).read_bytes(), ctype)
            if self.path == "/api/scenarios":
                return self._json(200, [{"id": k, "title": v["title"], "incident": v["incident"], "devices": v["devices"],
                                         "country": v["country"]} for k, v in SCENARIOS.items()])
            self._route(lambda parts: app.snapshot(int(parts[2])) if len(parts) == 3 else None)

        def do_POST(self):
            if not self._local(post=True):
                return self._json(403, {"error": "JSON requests from this page only"})
            try:
                n = int(self.headers.get("content-length") or 0)
            except ValueError:
                return self._json(400, {"error": "bad content-length"})
            if not 0 <= n <= 65536:
                return self._json(413, {"error": "body too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, RecursionError):  # RecursionError: absurdly nested JSON
                return self._json(400, {"error": "body must be JSON"})
            if not isinstance(body, dict):
                return self._json(400, {"error": "body must be a JSON object"})
            self._route(lambda parts: app.create(body.get("scenario")) if parts == ["api", "incidents"]
                        else app.act(int(parts[2]), parts[3], body) if len(parts) == 4 else None)

        def _route(self, fn):
            parts = self.path.strip("/").split("/")
            try:
                if parts[:2] != ["api", "incidents"] or (out := fn(parts)) is None:
                    return self._json(404, {"error": "not found"})
                self._json(200, out)
            except PermissionError as e:  # before OSError, which it subclasses
                self._json(409, {"error": str(e)})
            except (LookupError, OSError, ValueError) as e:  # OSError: no recording for this scenario
                self._json(400 if isinstance(e, ValueError) else 404, {"error": str(e)})
            except Exception as e:  # anything else, e.g. Bedrock unreachable: answer instead of dropping the socket
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def log_message(self, *a):
            pass

    return H


def serve(app: App, port: int = 8090) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), handler(app))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--replay-dir", help="replay recorded Decider answers from <dir>/<SCENARIO>.json")
    ap.add_argument("--bedrock", action="store_true", help="Bedrock reviews profile plans and explains outcomes")
    a = ap.parse_args()
    srv = serve(App(os.environ.get("DECIDER_URL", "http://127.0.0.1:8099"), a.replay_dir, a.bedrock), a.port)
    print(f"SIMShift UI on http://127.0.0.1:{a.port} (SIMULATED fleet)")
    srv.serve_forever()
