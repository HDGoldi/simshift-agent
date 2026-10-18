# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from types import MappingProxyType

from patterns.capability_aware_router.schemas import ChoiceDecision, QuestionOption, Usage
from simshift.decision.projection import observable_projection
from simshift.domain.models import ObservableIncident
from simshift.orchestration.dispatch import EvidenceSink


class InjectedChoiceProvider:
    status = "LOCAL_TEST_DOUBLE"
    detail = "injected deterministic test decision"

    def __init__(self, choices: str | Sequence[str], *, confidence: float = 1.0) -> None:
        self.choices = [choices] if isinstance(choices, str) else list(choices)
        self.confidence = confidence
        self.call_count = 0
        self.capacity = 24

    def choose(
        self,
        observable: ObservableIncident,
        options: tuple[QuestionOption, ...],
        *,
        decision_id: str | None = None,
        evidence_sink: EvidenceSink | None = None,
    ) -> ChoiceDecision:
        choice = self.choices[min(self.call_count, len(self.choices) - 1)]
        self.call_count += 1
        labels = [option.label for option in options]
        if choice not in labels:
            raise AssertionError(f"injected choice {choice!r} is not eligible: {labels!r}")
        if self.confidence == 1.0:
            probabilities = {label: float(label == choice) for label in labels}
        else:
            maximum = (1 + self.confidence * (len(labels) - 1)) / len(labels)
            remainder = (1 - maximum) / (len(labels) - 1)
            probabilities = {
                label: maximum if label == choice else remainder for label in labels
            }
        decision = ChoiceDecision(
            model="test-decider",
            model_choice=choice,
            probabilities=MappingProxyType(probabilities),
            confidence=self.confidence,
            usage=Usage(input_tokens=1, output_tokens=1),
            client_latency_ms=0.0,
        )
        if evidence_sink is not None:
            request = {
                "state": observable_projection(observable),
                "questions": {
                    "next_recovery_step": {
                        "type": "choice",
                        "instructions": "injected test choice",
                        "criteria": {option.label: option.description for option in options},
                    }
                },
            }
            request_bytes = json.dumps(
                request, sort_keys=True, separators=(",", ":")
            ).encode()
            response = {
                "model": decision.model,
                "answers": {
                    "next_recovery_step": {
                        "type": "choice",
                        "choice": choice,
                        "probabilities": probabilities,
                        "confidence": self.confidence,
                    }
                },
                "usage": decision.usage.model_dump(mode="json"),
            }
            response_bytes = json.dumps(
                response, sort_keys=True, separators=(",", ":")
            ).encode()
            evidence_sink(
                "decider_request",
                {
                    "decision_id": decision_id,
                    "request_hash": hashlib.sha256(request_bytes).hexdigest(),
                    "request_body_utf8": request_bytes.decode("utf-8"),
                    "request": request,
                    "attempt": 1,
                },
            )
            evidence_sink(
                "decider_response",
                {
                    "decision_id": decision_id,
                    "response_hash": hashlib.sha256(response_bytes).hexdigest(),
                    "response_body_utf8": response_bytes.decode("utf-8"),
                    "body": response,
                    "model_choice": choice,
                    "probabilities": probabilities,
                    "confidence": self.confidence,
                    "usage": decision.usage.model_dump(mode="json"),
                    "client_latency_ms": 0.0,
                    "extensions": {},
                },
            )
        return decision
