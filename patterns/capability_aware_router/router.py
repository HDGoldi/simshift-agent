# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Capacity-bounded routing and immutable exact-label callback dispatch."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from .schemas import (
    ChoiceDecision,
    DecisionPolicy,
    FilterResult,
    JSONValue,
    NoDecision,
    TypedChoiceQuestion,
)
from .trace import RouterTrace

_LABEL = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
Callback = Callable[[], Any]


class ChoiceClient(Protocol):
    """The canonical client's decision surface used by the router."""

    def choose(
        self,
        *,
        state: JSONValue,
        question: TypedChoiceQuestion,
        expected_model: str,
    ) -> ChoiceDecision:
        """Return one fully validated choice decision."""
        ...


class RouterInvariantError(RuntimeError):
    """An eligible or policy label cannot be safely dispatched."""


@dataclass(frozen=True, slots=True)
class ToolRegistry:
    """An immutable exact label-to-callback allowlist."""

    callbacks: Mapping[str, Callback]

    def __post_init__(self) -> None:
        copied = dict(self.callbacks)
        if not copied:
            raise ValueError("tool registry must not be empty")
        for label, callback in copied.items():
            if not isinstance(label, str) or _LABEL.fullmatch(label) is None:
                raise ValueError(f"invalid registry label {label!r}")
            if not callable(callback):
                raise ValueError(f"registry value for {label!r} is not callable")
        object.__setattr__(self, "callbacks", MappingProxyType(copied))

    def callback_for(self, label: str) -> Callback:
        try:
            return self.callbacks[label]
        except KeyError as error:
            raise RouterInvariantError(f"label {label!r} is not registered") from error


@dataclass(frozen=True, slots=True)
class RouteResult:
    """One local no-decision or one exact callback dispatch."""

    trace: RouterTrace
    callback_result: Any = None

    @property
    def no_decision(self) -> NoDecision | None:
        return self.trace.no_decision

    @property
    def decision(self) -> ChoiceDecision | None:
        return self.trace.decision


class CapabilityAwareRouter:
    """Route a validated filter result without reducing or fabricating options."""

    def __init__(
        self,
        *,
        client: ChoiceClient,
        trusted_num_slots: int,
        expected_model: str,
        registry: ToolRegistry,
        policy: DecisionPolicy,
    ) -> None:
        if (
            isinstance(trusted_num_slots, bool)
            or not isinstance(trusted_num_slots, int)
            or not 1 <= trusted_num_slots <= 255
        ):
            raise ValueError("trusted_num_slots must be an integer in [1, 255]")
        if not isinstance(expected_model, str) or not expected_model:
            raise ValueError("expected_model must be a non-empty trusted value")
        self._client = client
        self._capacity = trusted_num_slots
        self._expected_model = expected_model
        self._registry = registry
        self._policy = policy

    def route_filtered(
        self,
        *,
        filtered: FilterResult,
        state: JSONValue,
        question_name: str,
        instructions: str,
    ) -> RouteResult:
        """Call Decider only for supported cardinality, then dispatch one callback."""

        count = len(filtered.eligible)
        if count < 2:
            no_decision = NoDecision(
                reason="INSUFFICIENT_CHOICE_CARDINALITY",
                eligible_count=count,
                capacity=self._capacity,
            )
            return RouteResult(trace=RouterTrace(filtered=filtered, no_decision=no_decision))
        if count > min(255, self._capacity):
            no_decision = NoDecision(
                reason="UNSUPPORTED_CHOICE_CARDINALITY",
                eligible_count=count,
                capacity=self._capacity,
            )
            return RouteResult(trace=RouterTrace(filtered=filtered, no_decision=no_decision))

        labels = tuple(option.label for option in filtered.eligible)
        for label in labels:
            self._registry.callback_for(label)
        question = TypedChoiceQuestion(
            name=question_name,
            instructions=instructions,
            options=filtered.eligible,
        )
        decision = self._client.choose(
            state=state,
            question=question,
            expected_model=self._expected_model,
        )
        effective = self._policy.apply(decision, labels)
        callback = self._registry.callback_for(effective.effective_choice)
        trace = RouterTrace(
            filtered=filtered,
            question=question,
            decision=decision,
            effective=effective,
            dispatched_label=effective.effective_choice,
        )
        callback_result = callback()
        return RouteResult(trace=trace, callback_result=callback_result)


__all__ = [
    "CapabilityAwareRouter",
    "ChoiceClient",
    "RouteResult",
    "RouterInvariantError",
    "ToolRegistry",
]
