# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Capability-filter protocol and exact partition helper."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .schemas import FilterResult, QuestionOption, RemovedOption


class CapabilityFilter(Protocol):
    """A filter that returns an exact partition of its input options."""

    def filter(self, options: tuple[QuestionOption, ...]) -> FilterResult:
        """Return eligible and reasoned-removed options in original order."""
        ...


RemovalReason = Callable[[QuestionOption], str | None]


def filter_options(
    options: tuple[QuestionOption, ...], removal_reason: RemovalReason
) -> FilterResult:
    """Apply a predicate while preserving every option in exactly one partition."""

    eligible: list[QuestionOption] = []
    removed: list[RemovedOption] = []
    for option in options:
        reason = removal_reason(option)
        if reason is None:
            eligible.append(option)
        else:
            removed.append(RemovedOption(option=option, reason=reason))
    return FilterResult.from_partition(
        options,
        eligible=tuple(eligible),
        removed=tuple(removed),
    )
