"""Adapter for a Strands Decider 2B server (`strands-decider serve`), standard library only.

Verified against strands-decider 0.1.0 and checkpoint
StrandsAgents/strands-decider-2B-qwen3.5-v1-2610 (revision 216d1ccb46a9e9b036eb9187b248db98480f77d4):
    POST /v1/systemone  {"state": ..., "questions": {name: {"type": "choice", "instructions", "criteria"}}}
    -> {"model", "answers": {name: {"choice", "probabilities", "confidence"}}, "usage", "latency_ms"}
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol

from .schemas import Decision

DEFAULT_URL = os.environ.get("STRANDS_DECIDER_URL", "http://127.0.0.1:8099")


class DeciderClient(Protocol):
    def choose(self, state: Any, question: str, criteria: Mapping[str, str]) -> Decision: ...


class HttpDeciderClient:
    """One request per step: the routing `choice` plus an optional `noul` evidence check."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        timeout: float = 300.0,
        evidence_question: str | None = "Is the current evidence sufficient to choose a next step confidently?",
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.evidence_question = evidence_question

    def choose(self, state: Any, question: str, criteria: Mapping[str, str]) -> Decision:
        questions: dict[str, Any] = {
            "next_option": {"type": "choice", "instructions": question, "criteria": dict(criteria)}
        }
        if self.evidence_question:
            questions["evidence_sufficient"] = {"type": "noul", "instructions": self.evidence_question}
        req = urllib.request.Request(
            f"{self.url}/v1/systemone",
            data=json.dumps({"state": state, "questions": questions}).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read())
        ans = payload["answers"]["next_option"]
        ev = payload["answers"].get("evidence_sufficient", {}).get("noul")
        return Decision(
            choice=ans["choice"],
            probabilities=dict(ans["probabilities"]),
            confidence=float(ans["confidence"]),
            evidence_sufficient=ev,
            latency_ms=payload.get("latency_ms"),
            model=payload.get("model"),
            raw=payload,
        )

    def health(self) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.url}/health", timeout=5) as resp:
            return json.loads(resp.read())
