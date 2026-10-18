# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Strict, domain-independent DTOs for capability-aware routing."""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Label = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list[Any] | dict[str, Any]
NoDecisionReason = Literal[
    "INSUFFICIENT_CHOICE_CARDINALITY", "UNSUPPORTED_CHOICE_CARDINALITY"
]
OverrideReason = Literal["LOW_CONFIDENCE"]


class FrozenModel(BaseModel):
    """Base configuration shared by all public DTOs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class QuestionOption(FrozenModel):
    """One stable action label and its human-readable criterion."""

    label: Label
    description: str = Field(min_length=1, max_length=300)


class RemovedOption(FrozenModel):
    """An original option removed by a capability filter."""

    option: QuestionOption
    reason: str = Field(min_length=1, max_length=300)


class FilterResult(FrozenModel):
    """A complete, non-overlapping partition produced by a capability filter."""

    eligible: tuple[QuestionOption, ...] = Field(max_length=255)
    removed: tuple[RemovedOption, ...] = Field(max_length=255)

    @model_validator(mode="after")
    def validate_unique_partition(self) -> FilterResult:
        if len(self.eligible) + len(self.removed) > 255:
            raise ValueError("a filter result may contain at most 255 original options")
        eligible_labels = [option.label for option in self.eligible]
        removed_labels = [entry.option.label for entry in self.removed]
        if len(set(eligible_labels)) != len(eligible_labels):
            raise ValueError("eligible labels must be unique")
        if len(set(removed_labels)) != len(removed_labels):
            raise ValueError("removed labels must be unique")
        if set(eligible_labels) & set(removed_labels):
            raise ValueError("eligible and removed options must be disjoint")
        return self

    @classmethod
    def from_partition(
        cls,
        originals: tuple[QuestionOption, ...],
        *,
        eligible: tuple[QuestionOption, ...],
        removed: tuple[RemovedOption, ...],
    ) -> FilterResult:
        """Construct a result only when it exactly partitions ``originals``."""

        result = cls(eligible=eligible, removed=removed)
        result.assert_exact_partition(originals)
        return result

    def assert_exact_partition(self, originals: tuple[QuestionOption, ...]) -> None:
        """Reject omitted, invented, duplicated, or altered original options."""

        if len(originals) > 255:
            raise ValueError("a filter accepts at most 255 original options")
        original_labels = [option.label for option in originals]
        if len(set(original_labels)) != len(original_labels):
            raise ValueError("original option labels must be unique")
        partition = {option.label: option for option in self.eligible}
        partition.update({entry.option.label: entry.option for entry in self.removed})
        originals_by_label = {option.label: option for option in originals}
        if partition != originals_by_label:
            raise ValueError("eligible and removed options must exactly partition originals")


class TypedChoiceQuestion(FrozenModel):
    """One typed Decider choice question."""

    name: Label
    instructions: str = Field(min_length=1, max_length=1000)
    options: tuple[QuestionOption, ...] = Field(min_length=2, max_length=255)

    @model_validator(mode="after")
    def validate_unique_options(self) -> TypedChoiceQuestion:
        labels = [option.label for option in self.options]
        if len(set(labels)) != len(labels):
            raise ValueError("question option labels must be unique")
        return self


class Usage(FrozenModel):
    """Token counts reported by Decider."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ChoiceDecision(FrozenModel):
    """A fully validated model decision returned by the canonical client."""

    model: str = Field(min_length=1, max_length=300)
    model_choice: Label
    probabilities: Mapping[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    usage: Usage
    latency_ms: float | None = Field(default=None, ge=0.0)
    client_latency_ms: float = Field(ge=0.0)
    extensions: Mapping[str, JSONValue] = Field(default_factory=dict)

    @field_validator("confidence", "latency_ms", "client_latency_ms")
    @classmethod
    def validate_finite_numbers(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("numeric decision fields must be finite")
        return value

    @field_validator("probabilities")
    @classmethod
    def validate_probabilities(cls, value: Mapping[str, float]) -> Mapping[str, float]:
        if not value:
            raise ValueError("probabilities must not be empty")
        for label, probability in value.items():
            if not isinstance(label, str):
                raise ValueError("probability labels must be strings")
            if isinstance(probability, bool) or not isinstance(probability, (int, float)):
                raise ValueError("probabilities must be numbers")
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                raise ValueError("probabilities must be finite values in [0, 1]")
        return MappingProxyType(dict(value))

    @field_validator("extensions")
    @classmethod
    def freeze_extensions(cls, value: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
        return MappingProxyType(dict(value))


class NoDecision(FrozenModel):
    """A local cardinality result that never invokes Decider or a callback."""

    reason: NoDecisionReason
    eligible_count: int = Field(ge=0, le=255)
    capacity: int = Field(ge=1, le=255)

    @model_validator(mode="after")
    def validate_reason_matches_count(self) -> NoDecision:
        if self.reason == "INSUFFICIENT_CHOICE_CARDINALITY" and self.eligible_count >= 2:
            raise ValueError("insufficient cardinality requires fewer than two choices")
        if self.reason == "UNSUPPORTED_CHOICE_CARDINALITY" and self.eligible_count <= self.capacity:
            raise ValueError("unsupported cardinality requires a count above capacity")
        return self


class EffectiveDecision(FrozenModel):
    """A model choice and the policy-controlled label that may be dispatched."""

    model_choice: Label
    effective_choice: Label
    override_reason: OverrideReason | None = None

    @model_validator(mode="after")
    def validate_override(self) -> EffectiveDecision:
        differs = self.model_choice != self.effective_choice
        if differs != (self.override_reason is not None):
            raise ValueError("override_reason must be present exactly when choices differ")
        return self


class DecisionPolicy(FrozenModel):
    """Fail-closed confidence policy applied after response validation."""

    min_confidence: float = Field(default=0.20, ge=0.0, le=1.0)
    fallback_label: Label

    @field_validator("min_confidence")
    @classmethod
    def validate_finite_floor(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("minimum confidence must be finite")
        return value

    def apply(
        self, decision: ChoiceDecision, eligible_labels: tuple[str, ...]
    ) -> EffectiveDecision:
        if decision.model_choice not in eligible_labels:
            raise ValueError("model choice is not eligible")
        if decision.confidence < self.min_confidence:
            if self.fallback_label not in eligible_labels:
                raise ValueError("low-confidence fallback is not eligible")
            return EffectiveDecision(
                model_choice=decision.model_choice,
                effective_choice=self.fallback_label,
                override_reason="LOW_CONFIDENCE",
            )
        return EffectiveDecision(
            model_choice=decision.model_choice,
            effective_choice=decision.model_choice,
        )
