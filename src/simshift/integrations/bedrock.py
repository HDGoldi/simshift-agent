# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Inert local tool-host model and post-evidence explanation adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncGenerator, AsyncIterable, Mapping
from typing import Any

from botocore.config import Config  # type: ignore[import-untyped]
from strands import Agent
from strands.models import BedrockModel, Model

from simshift.decision.projection import assert_no_evaluator_leak, observable_projection
from simshift.domain.models import ObservableIncident

_MAX_EXPLANATION_BYTES = 32 * 1024


class LocalTestDoubleModel(Model):
    """A non-networking model used only to host directly called Strands tools."""

    def __init__(self) -> None:
        self.invocation_count = 0
        self._config: dict[str, Any] = {
            "model_id": "simshift-local-tool-host",
            "context_window_limit": 4096,
        }

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self._config)

    async def stream(  # type: ignore[override]
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterable[dict[str, Any]]:
        self.invocation_count += 1
        if False:  # make this an async generator without yielding a usable event
            yield {}
        raise AssertionError("LocalTestDoubleModel must never be invoked")

    async def structured_output(
        self, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        self.invocation_count += 1
        if False:
            yield {}
        raise AssertionError("LocalTestDoubleModel must never be invoked")


class DeterministicLocalExplainer:
    """Format terminal public evidence without a model or network call."""

    status = "LOCAL_TEST_DOUBLE"
    detail = "deterministic local explanation"
    provider = "local"
    region_name = "local"
    model_reference = "deterministic-template-v1"

    def __init__(self) -> None:
        self.invocation_count = 0

    def request_evidence(
        self, observable: ObservableIncident, evidence: Mapping[str, Any]
    ) -> dict[str, str]:
        del observable, evidence
        return {
            "prompt_hash": hashlib.sha256(b"deterministic-template-v1").hexdigest(),
            "provider": self.provider,
            "region": self.region_name,
            "model_reference": self.model_reference,
        }

    def explain(self, observable: ObservableIncident, evidence: Mapping[str, Any]) -> str:
        if not evidence:
            raise ValueError("explanation requires already-produced public evidence")
        projected = observable_projection(observable)
        assert_no_evaluator_leak(evidence)
        self.invocation_count += 1
        return (
            "SIMULATED SIMShift outcome: "
            f"incident={projected['incident_id']}; "
            f"profile={projected['active_profile_id']}; "
            f"status={evidence.get('final_status', 'UNKNOWN')}. "
            "No real telecom action was performed."
        )


class StrandsBedrockExplainer:
    """Use a separate no-tools Bedrock agent only after public evidence exists."""

    status = "REAL"
    detail = "no-tools Amazon Bedrock explanation"
    provider = "Amazon Bedrock"

    def __init__(
        self,
        *,
        region_name: str,
        model_reference: str,
        agent: Agent | None = None,
    ) -> None:
        self.region_name = region_name
        self.model_reference = model_reference
        self.invocation_count = 0
        if agent is None:
            model = BedrockModel(
                region_name=region_name,
                model_id=model_reference,
                temperature=0.0,
                max_tokens=600,
                boto_client_config=Config(
                    connect_timeout=5,
                    read_timeout=60,
                    retries={"mode": "standard", "max_attempts": 2},
                ),
            )
            agent = Agent(model=model, tools=[])
        if agent.tool_registry.registry:
            raise ValueError("Bedrock explainer agent must have no tools")
        self.agent = agent

    def build_prompt(
        self, observable: ObservableIncident, evidence: Mapping[str, Any]
    ) -> str:
        if not evidence:
            raise ValueError("explanation requires already-produced public evidence")
        payload = {
            "observable": observable_projection(observable),
            "evidence": dict(evidence),
        }
        assert_no_evaluator_leak(payload)
        return (
            "Explain this SIMULATED telecom recovery evidence concisely. "
            "Do not claim any real telecom command or deployment occurred.\n"
            + json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )

    def request_evidence(
        self, observable: ObservableIncident, evidence: Mapping[str, Any]
    ) -> dict[str, str]:
        prompt = self.build_prompt(observable, evidence)
        return {
            "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "provider": self.provider,
            "region": self.region_name,
            "model_reference": self.model_reference,
        }

    def explain(self, observable: ObservableIncident, evidence: Mapping[str, Any]) -> str:
        prompt = self.build_prompt(observable, evidence)
        self.invocation_count += 1
        text = str(self.agent(prompt))
        if len(text.encode("utf-8")) > _MAX_EXPLANATION_BYTES:
            raise ValueError("Bedrock explanation exceeds 32 KiB")
        return text


__all__ = [
    "DeterministicLocalExplainer",
    "LocalTestDoubleModel",
    "StrandsBedrockExplainer",
]
