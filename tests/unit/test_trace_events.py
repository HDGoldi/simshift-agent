# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from pydantic import ValidationError

from simshift.config import EnvironmentEvidence
from simshift.tracing.events import ComponentStatus, TraceEvent


def _provenance() -> dict[str, object]:
    return {
        "decider": {"status": "REAL", "detail": "loopback service"},
        "strands_framework_dispatch": {"status": "REAL", "detail": "direct framework dispatch"},
        "strands_tool_host_model": {
            "status": "LOCAL_TEST_DOUBLE",
            "detail": "inert host",
            "invoked": False,
        },
        "explainer_model": {
            "status": "LOCAL_TEST_DOUBLE",
            "detail": "deterministic local explainer",
            "configured": True,
            "invoked": False,
        },
        "telecom_simulator": {"status": "SIMULATED", "detail": "virtual cohort"},
        "aws_deployment": {"status": "UNVERIFIED", "detail": "not invoked"},
    }


def run_started() -> TraceEvent:
    environment = EnvironmentEvidence(
        lockfile_sha256="d" * 64,
        explainer_mode="local-test-double",
        dependency_versions={"python": "3.11.15"},
    )
    return TraceEvent.create(
        run_id="a" * 24,
        sequence=0,
        event_type="run_started",
        component="runner",
        component_status=ComponentStatus.SIMULATED,
        payload={
            "behavior_config_hash": "b" * 64,
            "environment_evidence_hash": environment.environment_evidence_hash,
            "environment_evidence": environment.model_dump(mode="json"),
            "fixture_revision": "br-profile-v1",
            "seed": 1,
            "bounds": {"max_steps": 4},
            "provenance": _provenance(),
        },
    )


def test_event_id_is_deterministic() -> None:
    assert run_started().event_id == f"{'a' * 24}:000000"


def test_event_rejects_mismatched_environment_evidence_hash() -> None:
    started = run_started()
    environment = started.payload["environment_evidence"] | {"lockfile_sha256": "e" * 64}
    payload = started.payload | {"environment_evidence": environment}
    with pytest.raises(ValidationError, match="environment evidence hash"):
        TraceEvent.create(
            run_id="a" * 24,
            sequence=0,
            event_type="run_started",
            component="runner",
            component_status=ComponentStatus.SIMULATED,
            payload=payload,
        )


def test_event_rejects_evaluator_key() -> None:
    payload = run_started().payload | {"_evaluator_truth": {}}
    with pytest.raises(ValidationError):
        TraceEvent.create(
            run_id="a" * 24,
            sequence=0,
            event_type="run_started",
            component="runner",
            component_status=ComponentStatus.SIMULATED,
            payload=payload,
        )
