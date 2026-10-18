# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import json

from simshift.tracing.events import RunProvenance
from tests.unit.test_trace_events import run_started


def test_framework_host_explainer_and_cloud_provenance_are_separate() -> None:
    provenance = RunProvenance.model_validate_json(json.dumps(run_started().payload["provenance"]))
    assert provenance.strands_framework_dispatch.status == "REAL"
    assert provenance.strands_tool_host_model.status == "LOCAL_TEST_DOUBLE"
    assert provenance.strands_tool_host_model.invoked is False
    assert provenance.explainer_model.status == "LOCAL_TEST_DOUBLE"
    assert provenance.explainer_model.configured is True
    assert provenance.explainer_model.invoked is False
    assert provenance.telecom_simulator.status == "SIMULATED"
    assert provenance.aws_deployment.status == "UNVERIFIED"
