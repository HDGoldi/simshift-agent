# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Opt-in verification against already-authorized AWS resources only."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from simshift.integrations.bedrock import StrandsBedrockExplainer
from tests.integration.conftest import require_opt_in, required_environment
from tests.integration.test_production_path import run_real_scenario

pytestmark = pytest.mark.aws_integration


def test_authorized_bedrock_explains_only_after_real_public_evidence(
    real_decider_endpoint: tuple[str, Path],
) -> None:
    require_opt_in("SIMSHIFT_RUN_AWS_INTEGRATION")
    region = required_environment("BEDROCK_REGION")
    model_reference = os.environ.get("BEDROCK_INFERENCE_PROFILE") or os.environ.get(
        "BEDROCK_MODEL_ID"
    )
    if not model_reference:
        pytest.fail(
            "BEDROCK_INFERENCE_PROFILE or BEDROCK_MODEL_ID is required after opt-in",
            pytrace=False,
        )

    br, br_runtime, host_calls = run_real_scenario("BR_PROFILE", real_decider_endpoint)
    assert br.status == "RESTORED"
    assert host_calls == 0
    public_evidence = {
        "final_status": br.status,
        "reason": br.reason,
        "final_profile": br.final_profile,
    }
    explanation = StrandsBedrockExplainer(
        region_name=region,
        model_reference=model_reference,
    ).explain(br_runtime.observable, public_evidence)
    assert explanation.strip()

    offline, offline_runtime, offline_host_calls = run_real_scenario(
        "OFFLINE", real_decider_endpoint
    )
    assert offline.status == "ESCALATED"
    assert offline.transition is None
    assert offline_runtime.observable.active_profile_id == "profile_A"
    assert offline_host_calls == 0
