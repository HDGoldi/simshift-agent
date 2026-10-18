# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.domain.enums import Action
from simshift.orchestration.services import ToolServices
from simshift.scenarios.repository import ScenarioRepository


def test_stale_and_unknown_requests_do_not_mutate() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    services = ToolServices(runtime, run_id="a" * 24)
    original = runtime.observable
    stale = services.execute(
        Action.INVESTIGATE_DEVICE,
        incident_id="BR_PROFILE",
        observation_revision=1,
    )
    unknown = services.execute(
        Action.INVESTIGATE_DEVICE,
        incident_id="OFFLINE",
        observation_revision=0,
    )
    assert stale.status == unknown.status == "REJECTED"
    assert stale.reason == "STALE_OBSERVATION"
    assert unknown.reason == "UNKNOWN_INCIDENT"
    assert runtime.observable == original
    assert services.invocations == []


def test_profile_service_only_prepares_proposal() -> None:
    runtime = ScenarioRepository().load_runtime("BR_PROFILE")
    result = ToolServices(runtime, run_id="a" * 24).execute(
        Action.EVALUATE_PROFILE_CHANGE,
        incident_id="BR_PROFILE",
        observation_revision=0,
    )
    assert result.status == "PROPOSAL_PREPARED"
    assert result.proposal is not None
    assert runtime.observable.active_profile_id == "profile_A"
    assert runtime.transitions == {}
