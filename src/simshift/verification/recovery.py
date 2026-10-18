# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Independent dual-layer recovery verification."""

from dataclasses import dataclass

from simshift.domain.models import LayerCheck


@dataclass(frozen=True)
class RecoveryResult:
    registration: LayerCheck
    telemetry: LayerCheck
    service_restored: bool


class RecoveryVerifier:
    """The sole owner of service-restored computation."""

    @staticmethod
    def verify(registration: LayerCheck, telemetry: LayerCheck) -> RecoveryResult:
        if registration.kind != "REGISTRATION" or telemetry.kind != "TELEMETRY":
            raise ValueError("recovery requires distinct registration and telemetry checks")
        return RecoveryResult(
            registration=registration,
            telemetry=telemetry,
            service_restored=registration.passed and telemetry.passed,
        )
