"""Typed contracts for the Capability-Aware Router. Standard library only."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

State = Mapping[str, Any]


@dataclass(frozen=True)
class Option:
    """One thing the agent may do next.

    name:        option id the decision model returns (e.g. "restart_service")
    description: what the option means; sent to the model as its `criteria` text
    tool:        callable run when this option is chosen; receives the state
    risky:       risky options run only after `approve(state, option)` returns True
    """

    name: str
    description: str
    tool: Callable[[State], Any]
    risky: bool = False


@dataclass(frozen=True)
class Decision:
    """What the decision model answered. Values are copied from the model, never invented."""

    choice: str
    probabilities: dict[str, float]
    confidence: float
    evidence_sufficient: float | None = None
    latency_ms: float | None = None
    model: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


Outcome = Literal[
    "executed",            # chosen tool ran
    "no_options",          # policy removed everything; nothing ran
    "low_confidence",      # model unsure and no fallback; nothing ran
    "low_confidence_fallback",  # model unsure; fallback tool ran instead
    "awaiting_approval",   # risky option chosen; approval refused or missing; nothing ran
]


@dataclass
class StepResult:
    """One router step: everything a trace, a test or a UI needs."""

    question: str
    allowed: list[str]
    removed: dict[str, str]
    outcome: Outcome
    decision: Decision | None = None
    executed: str | None = None          # option whose tool actually ran
    tool_name: str | None = None
    tool_output: Any = None

    def to_trace(self) -> dict[str, Any]:
        d = self.decision
        return {
            "question": self.question,
            "allowed": self.allowed,
            "removed": self.removed,
            "outcome": self.outcome,
            "choice": d.choice if d else None,
            "probabilities": d.probabilities if d else None,
            "confidence": d.confidence if d else None,
            "evidence_sufficient": d.evidence_sufficient if d else None,
            "decider_latency_ms": d.latency_ms if d else None,
            "model": d.model if d else None,
            "executed": self.executed,
            "tool": self.tool_name,
            "tool_output": self.tool_output if isinstance(self.tool_output, (str, int, float, bool, dict, list, type(None))) else repr(self.tool_output),
        }
