# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from pydantic import ValidationError

from simshift.domain.models import ObservableIncident
from simshift.scenarios.repository import ScenarioRepository


def test_observable_is_frozen_strict_and_closed() -> None:
    observable = ScenarioRepository().load("BR_PROFILE").observable
    with pytest.raises(ValidationError):
        ObservableIncident.model_validate({**observable.model_dump(), "unknown": True})
    with pytest.raises(ValidationError):
        observable.observation_revision = 1  # type: ignore[misc]


def test_action_counts_are_exact() -> None:
    observable = ScenarioRepository().load("BR_PROFILE").observable
    raw = observable.model_dump()
    raw["action_counts"].pop(next(iter(raw["action_counts"])))
    with pytest.raises(ValidationError, match="exactly all six"):
        ObservableIncident.model_validate(raw)
