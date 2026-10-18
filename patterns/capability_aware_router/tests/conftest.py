from __future__ import annotations

from patterns.capability_aware_router import Decision, Option, Rule, RulePolicy


class FakeDecider:
    """Returns a fixed choice/confidence and records what it was offered."""

    def __init__(self, choice: str | None = None, confidence: float = 0.9) -> None:
        self.choice, self.confidence = choice, confidence
        self.offered: list[str] = []

    def choose(self, state, question, criteria):
        self.offered = list(criteria)
        c = self.choice or self.offered[0]
        return Decision(choice=c, probabilities={c: self.confidence}, confidence=self.confidence, model="fake")


def tool(name):
    def _t(state):
        return name
    _t.__name__ = f"tool_{name}"
    return _t


OPTIONS = [
    Option("a", "option a", tool("a")),
    Option("b", "option b", tool("b")),
    Option("c", "option c (risky)", tool("c"), risky=True),
    Option("safe", "read-only fallback", tool("safe")),
]

POLICY = RulePolicy([
    Rule("b", lambda s: s.get("block_b", False), "b blocked by state"),
    Rule("a", lambda s: s.get("block_all", False), "all blocked"),
    Rule("b", lambda s: s.get("block_all", False), "all blocked"),
    Rule("c", lambda s: s.get("block_all", False), "all blocked"),
    Rule("safe", lambda s: s.get("block_all", False), "all blocked"),
])
