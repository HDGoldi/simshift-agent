# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.domain.enums import Action
from simshift.simulator.engine import deterministic_pass_count


def test_seed_and_occurrence_streams_are_repeatable_and_distinct() -> None:
    kwargs = dict(
        fixture_revision="br-profile-v1",
        seed=20261018,
        action=Action.RETRY_CONNECTION,
        check="registration",
        cohort_size=3200,
        probability=0.04,
    )
    first = deterministic_pass_count(occurrence=1, **kwargs)
    assert first == deterministic_pass_count(occurrence=1, **kwargs)
    assert first != deterministic_pass_count(occurrence=2, **kwargs)
    assert first != deterministic_pass_count(occurrence=1, **{**kwargs, "seed": 1})
