# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from simshift.domain.models import LayerCheck
from simshift.verification.recovery import RecoveryVerifier


def _check(kind: str, passed: bool) -> LayerCheck:
    count = 10 if passed else 9
    return LayerCheck(
        check_id=kind,
        kind=kind,
        passed_count=count,
        cohort_size=10,
        rate=count / 10,
        threshold=0.95,
        passed=passed,
    )  # type: ignore[arg-type]


def test_no_single_layer_success_restores_service() -> None:
    assert not RecoveryVerifier.verify(
        _check("REGISTRATION", True), _check("TELEMETRY", False)
    ).service_restored
    assert not RecoveryVerifier.verify(
        _check("REGISTRATION", False), _check("TELEMETRY", True)
    ).service_restored
    assert RecoveryVerifier.verify(
        _check("REGISTRATION", True), _check("TELEMETRY", True)
    ).service_restored
