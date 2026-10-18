# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.config import EnvironmentEvidence, RunConfig
from simshift.domain.enums import ScenarioId


def test_behavior_and_environment_identity_are_separate() -> None:
    run = RunConfig(scenario_id=ScenarioId.BR_PROFILE, fixture_revision="br-profile-v1", seed=1)
    first = EnvironmentEvidence(
        lockfile_sha256="a" * 64,
        explainer_mode="local-test-double",
        dependency_versions={"pydantic": "2.14.1"},
    )
    second = first.model_copy(update={"trusted_manifest_sha256": "b" * 64})
    behavior_hash = run.behavior_config_hash
    run_id = run.run_id
    assert len(run.run_id) == 24
    assert run.behavior_config_hash == behavior_hash
    assert first.environment_evidence_hash != second.environment_evidence_hash
    assert run.behavior_config_hash == behavior_hash
    assert run.run_id == run_id
