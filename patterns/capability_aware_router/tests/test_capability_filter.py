# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from pydantic import ValidationError

from patterns.capability_aware_router.filters import filter_options
from patterns.capability_aware_router.schemas import (
    FilterResult,
    QuestionOption,
    RemovedOption,
)


def _options() -> tuple[QuestionOption, ...]:
    return (
        QuestionOption(label="extract", description="Extract"),
        QuestionOption(label="inspect", description="Inspect"),
        QuestionOption(label="review", description="Review"),
    )


def test_filter_returns_exact_partition_in_original_order() -> None:
    options = _options()
    result = filter_options(
        options,
        lambda option: "PARSER_MISSING" if option.label == "extract" else None,
    )
    assert [option.label for option in result.eligible] == ["inspect", "review"]
    assert [(entry.option.label, entry.reason) for entry in result.removed] == [
        ("extract", "PARSER_MISSING")
    ]
    result.assert_exact_partition(options)


def test_partition_rejects_omitted_invented_and_overlapping_options() -> None:
    options = _options()
    with pytest.raises(ValueError, match="exactly partition"):
        FilterResult.from_partition(options, eligible=(options[0],), removed=())
    invented = QuestionOption(label="invented", description="Invented")
    with pytest.raises(ValueError, match="exactly partition"):
        FilterResult.from_partition(options, eligible=(invented,), removed=())
    with pytest.raises(ValidationError, match="disjoint"):
        FilterResult(
            eligible=(options[0],),
            removed=(RemovedOption(option=options[0], reason="removed"),),
        )


def test_filter_rejects_more_than_255_original_options() -> None:
    options = tuple(
        QuestionOption(label=f"a{index}", description="Action") for index in range(256)
    )
    with pytest.raises(ValueError, match="at most 255"):
        filter_options(options, lambda _option: None)
