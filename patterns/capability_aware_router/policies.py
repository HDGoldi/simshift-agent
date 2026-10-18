"""Deterministic eligibility. The policy decides what is ALLOWED; the model only picks among it."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .schemas import State


class Policy(Protocol):
    def removed(self, state: State, options: Sequence[str]) -> dict[str, str]:
        """Return {option: reason} for every option that must NOT be offered right now."""
        ...


@dataclass(frozen=True)
class Rule:
    """Remove `option` when `when(state)` is True, recording `reason`."""

    option: str
    when: Callable[[State], bool]
    reason: str


class RulePolicy:
    """A list of rules. First matching rule per option supplies the reason."""

    def __init__(self, rules: Iterable[Rule]) -> None:
        self.rules = list(rules)

    def removed(self, state: State, options: Sequence[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in self.rules:
            if r.option in options and r.option not in out and r.when(state):
                out[r.option] = r.reason
        return out
