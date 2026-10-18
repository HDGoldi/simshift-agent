# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Portable causal trace DTOs for one routing operation."""

from __future__ import annotations

from pydantic import model_validator

from .schemas import (
    ChoiceDecision,
    EffectiveDecision,
    FilterResult,
    FrozenModel,
    Label,
    NoDecision,
    TypedChoiceQuestion,
)


class RouterTrace(FrozenModel):
    """Validated causal evidence from filtering through optional dispatch."""

    filtered: FilterResult
    question: TypedChoiceQuestion | None = None
    decision: ChoiceDecision | None = None
    effective: EffectiveDecision | None = None
    no_decision: NoDecision | None = None
    dispatched_label: Label | None = None

    @model_validator(mode="after")
    def validate_causality(self) -> RouterTrace:
        if self.no_decision is not None:
            if any(
                value is not None
                for value in (
                    self.question,
                    self.decision,
                    self.effective,
                    self.dispatched_label,
                )
            ):
                raise ValueError("a no-decision trace cannot contain decision or dispatch data")
            return self
        if None in (self.question, self.decision, self.effective, self.dispatched_label):
            raise ValueError("a dispatched trace requires question, decision, policy, and label")
        if self.effective is not None and self.dispatched_label != self.effective.effective_choice:
            raise ValueError("dispatched label must equal the effective choice")
        return self
