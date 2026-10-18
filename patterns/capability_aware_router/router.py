"""CapabilityAwareRouter: state -> policy filter -> Decider choice -> re-check -> tool.

Guarantees (each covered by a test in ./tests):
  * the model is only ever offered options the policy allows;
  * the option the model picks is the option whose tool runs (no LLM override);
  * a choice outside the allowed set is refused, never executed;
  * a risky option runs only after explicit approval;
  * below `low_confidence`, nothing runs unless a safe, allowed fallback is configured.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .decider_client import DeciderClient
from .policies import Policy
from .schemas import Option, State, StepResult


class NonAdmissibleChoice(RuntimeError):
    """The model returned an option the policy did not allow."""


class CapabilityAwareRouter:
    def __init__(
        self,
        question: str,
        options: Sequence[Option],
        policy: Policy,
        decider: DeciderClient,
        *,
        describe: Callable[[State], Any] = lambda s: dict(s),
        low_confidence: float = 0.5,
        fallback: str | None = None,
        approve: Callable[[State, Option], bool] | None = None,
    ) -> None:
        names = [o.name for o in options]
        if len(set(names)) != len(names):
            raise ValueError("option names must be unique")
        if fallback is not None and fallback not in names:
            raise ValueError(f"fallback {fallback!r} is not an option")
        self.question = question
        self.options = {o.name: o for o in options}
        self.policy = policy
        self.decider = decider
        self.describe = describe
        self.low_confidence = low_confidence
        self.fallback = fallback
        self.approve = approve

    def admissible(self, state: State) -> tuple[list[str], dict[str, str]]:
        names = list(self.options)
        removed = self.policy.removed(state, names)
        return [n for n in names if n not in removed], removed

    def step(self, state: State) -> StepResult:
        allowed, removed = self.admissible(state)
        result = StepResult(question=self.question, allowed=allowed, removed=removed, outcome="no_options")
        if not allowed:
            return result

        criteria = {n: self.options[n].description for n in allowed}
        decision = self.decider.choose(self.describe(state), self.question, criteria)
        result.decision = decision

        if decision.choice not in allowed:
            raise NonAdmissibleChoice(f"model chose {decision.choice!r}; allowed {allowed}")

        target = decision.choice
        if decision.confidence < self.low_confidence:
            if self.fallback and self.fallback in allowed:
                target, result.outcome = self.fallback, "low_confidence_fallback"
            else:
                result.outcome = "low_confidence"
                return result
        else:
            result.outcome = "executed"

        # re-check right before acting
        if target in self.policy.removed(state, [target]):
            raise NonAdmissibleChoice(f"{target!r} no longer allowed")

        opt = self.options[target]
        if opt.risky and not (self.approve and self.approve(state, opt)):
            result.outcome = "awaiting_approval"
            return result

        result.executed = target
        result.tool_name = getattr(opt.tool, "__name__", repr(opt.tool))
        result.tool_output = opt.tool(state)
        return result
