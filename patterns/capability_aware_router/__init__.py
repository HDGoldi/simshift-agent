"""Capability-Aware Router: a reusable Strands Decider 2B tool-selection pattern (#tool-selection)."""

from .decider_client import DeciderClient, HttpDeciderClient
from .policies import Policy, Rule, RulePolicy
from .router import CapabilityAwareRouter, NonAdmissibleChoice
from .schemas import Decision, Option, StepResult

__all__ = [
    "CapabilityAwareRouter",
    "DeciderClient",
    "Decision",
    "HttpDeciderClient",
    "NonAdmissibleChoice",
    "Option",
    "Policy",
    "Rule",
    "RulePolicy",
    "StepResult",
]
