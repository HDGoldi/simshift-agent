# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.decision.options import ACTION_OPTIONS
from simshift.domain.enums import Action


def test_action_registry_has_stable_six_action_order() -> None:
    assert tuple(option.label for option in ACTION_OPTIONS) == tuple(
        action.value for action in Action
    )
    assert all(option.description for option in ACTION_OPTIONS)
