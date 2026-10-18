"""Comparator strategies. Each is a DeciderClient: it receives the SAME state text and the SAME
policy-filtered option set as Strands Decider 2B, and its pick goes through the same router,
guards and approval gate. Only the chooser differs.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping
from random import Random
from typing import Any

from patterns.capability_aware_router import Decision


def _num(text: str, label: str) -> float | None:
    m = re.search(re.escape(label) + r"[^0-9]*([0-9]+(?:\.[0-9]+)?)", text)
    return float(m.group(1)) if m else None


class RulesChooser:
    """Hand-written priority list over the same state text. A strong, honest baseline."""

    name = "rules"

    def choose(self, state: str, question: str, criteria: Mapping[str, str]) -> Decision:
        t = state
        attach = (_num(t, "Network registration (attach) success:") or 0) / 100
        app = (_num(t, "acknowledged by the cloud:") or 0) / 100
        resets = _num(t, "Modem resets per device per hour:") or 0
        order: list[str] = []
        if "NOT reachable" in t:
            order.append("escalate_or_wait")
        if "Fault is above the cellular layer" in t or "Fault is in the device firmware" in t:
            order.append("escalate_or_wait")
        if attach >= 0.9 and app < 0.5:
            order.append("investigate_data_path")
        if resets >= 3:
            order.append("investigate_device")
        if "trend over the last 15 minutes: improving" in t:
            order.append("retry_connection")
        order += ["try_allowed_operator", "evaluate_profile_change", "investigate_data_path",
                  "investigate_device", "retry_connection", "escalate_or_wait"]
        c = next(o for o in order if o in criteria)
        return Decision(choice=c, probabilities={c: 1.0}, confidence=1.0, latency_ms=0.0, model="rules")


class RandomChooser:
    """Uniform over allowed options. Lower bound: shows how much the policy alone buys."""

    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self.r = Random(seed)

    def choose(self, state: Any, question: str, criteria: Mapping[str, str]) -> Decision:
        names = list(criteria)
        c = self.r.choice(names)
        p = 1 / len(names)
        return Decision(choice=c, probabilities=dict.fromkeys(names, p), confidence=0.0,
                        latency_ms=0.0, model="random")


class BedrockChooser:
    """Bedrock picks among the same admissible options (no free-form actions)."""

    name = "bedrock"

    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        import boto3

        from agent.bedrock import DEFAULT_REGION
        from agent.bedrock import model_id as default_model

        self.model_id = model_id or default_model()
        profile = os.environ.get("SIMSHIFT_AWS_PROFILE") or None
        self.client = boto3.Session(profile_name=profile).client(
            "bedrock-runtime", region_name=region or os.environ.get("SIMSHIFT_AWS_REGION", DEFAULT_REGION))
        self.input_tokens = 0
        self.output_tokens = 0

    def choose(self, state: str, question: str, criteria: Mapping[str, str]) -> Decision:
        opts = "\n".join(f"- {k}: {v}" for k, v in criteria.items())
        prompt = (f"{question}\n\nState:\n{state}\n\nOptions:\n{opts}\n\n"
                  'Answer with JSON only: {"choice": "<option name>"}')
        t0 = time.perf_counter()
        r = self.client.converse(modelId=self.model_id,
                                 messages=[{"role": "user", "content": [{"text": prompt}]}],
                                 inferenceConfig={"maxTokens": 50, "temperature": 0})
        ms = (time.perf_counter() - t0) * 1000
        u = r.get("usage", {})
        self.input_tokens += u.get("inputTokens", 0)
        self.output_tokens += u.get("outputTokens", 0)
        text = r["output"]["message"]["content"][0]["text"]
        m = re.search(r"\{.*\}", text, re.DOTALL)
        c = json.loads(m.group(0))["choice"] if m else ""
        if c not in criteria:
            c = next((k for k in criteria if k in text), "escalate_or_wait" if "escalate_or_wait" in criteria
                     else next(iter(criteria)))
        return Decision(choice=c, probabilities={c: 1.0}, confidence=1.0, latency_ms=ms, model=self.model_id)
