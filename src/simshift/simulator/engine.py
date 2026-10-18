# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Occurrence-indexed deterministic synthetic fleet effects."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from simshift.domain.enums import (
    Action,
    DeliveryOutcome,
    RegistrationStatus,
    TelemetryStatus,
)
from simshift.domain.models import ActionEffect, LayerCheck, ObservableIncident
from simshift.scenarios.repository import TruthHandle, _resolve_truth

SIMULATOR_VERSION = "virtual-fleet-v1"


@dataclass(frozen=True)
class EffectResult:
    observable: ObservableIncident
    effect_applied: bool
    registration: LayerCheck | None
    telemetry: LayerCheck | None


def deterministic_pass_count(
    *,
    fixture_revision: str,
    seed: int,
    action: Action,
    occurrence: int,
    check: str,
    cohort_size: int,
    probability: float,
) -> int:
    """Calculate the exact cohort count using the normative SHA-256 stream."""

    passed = 0
    prefix = "\x1f".join((fixture_revision, str(seed), action.value, str(occurrence), check))
    for device_index in range(cohort_size):
        digest = hashlib.sha256(f"{prefix}\x1f{device_index}".encode()).digest()
        uniform = int.from_bytes(digest[:8], "big") / 2**64
        passed += uniform < probability
    return passed


class VirtualFleetEngine:
    """The only component that resolves evaluator truth into public outcomes."""

    def __init__(self, truth_handle: TruthHandle, fixture_revision: str, seed: int) -> None:
        self.__truth = _resolve_truth(truth_handle)
        self.fixture_revision = fixture_revision
        self.seed = seed

    def _effect(self, action: Action, occurrence: int) -> ActionEffect:
        try:
            return next(
                effect
                for effect in self.__truth.effects
                if effect.action is action and effect.occurrence == occurrence
            )
        except StopIteration as error:
            raise ValueError(f"no effect for {action.value} occurrence {occurrence}") from error

    def profile_delivery_outcome(self) -> DeliveryOutcome:
        """Expose only the public lifecycle input, never evaluator truth records."""

        return self._effect(Action.EVALUATE_PROFILE_CHANGE, 1).delivery_outcome

    def apply_action(self, observable: ObservableIncident, action: Action) -> EffectResult:
        """Apply one defined effect, except profile activation which is proposal-only here."""

        occurrence = observable.action_counts[action] + 1
        effect = self._effect(action, occurrence)
        counts = dict(observable.action_counts)
        counts[action] = occurrence
        evidence = observable.evidence + tuple(
            code for code in effect.evidence_added if code not in observable.evidence
        )
        updates: dict[str, object] = {
            "observation_revision": observable.observation_revision + 1,
            "action_counts": counts,
            "evidence": evidence,
        }
        if action is Action.RETRY_CONNECTION:
            updates["connection_retry_count"] = observable.connection_retry_count + 1
        updated = observable.model_copy(update=updates)
        if action in {Action.RETRY_CONNECTION, Action.TRY_ALLOWED_OPERATOR}:
            return self._apply_probabilities(updated, effect, cause=f"{action.value}:{occurrence}")
        return EffectResult(updated, True, None, None)

    def apply_profile_effect(
        self,
        observable: ObservableIncident,
        *,
        cause: str,
        registration_threshold: float = 0.95,
        telemetry_threshold: float = 0.95,
    ) -> EffectResult:
        """Apply the post-enable profile probabilities exactly once."""

        effect = self._effect(Action.EVALUATE_PROFILE_CHANGE, 1)
        return self._apply_probabilities(
            observable,
            effect,
            cause=cause,
            registration_threshold=registration_threshold,
            telemetry_threshold=telemetry_threshold,
        )

    def _apply_probabilities(
        self,
        observable: ObservableIncident,
        effect: ActionEffect,
        *,
        cause: str,
        registration_threshold: float = 0.95,
        telemetry_threshold: float = 0.95,
    ) -> EffectResult:
        if effect.registration_probability is None or effect.telemetry_probability is None:
            raise ValueError("state-changing effect is missing probabilities")
        registration_count = deterministic_pass_count(
            fixture_revision=self.fixture_revision,
            seed=self.seed,
            action=effect.action,
            occurrence=effect.occurrence,
            check="registration",
            cohort_size=observable.cohort_size,
            probability=effect.registration_probability,
        )
        telemetry_count = deterministic_pass_count(
            fixture_revision=self.fixture_revision,
            seed=self.seed,
            action=effect.action,
            occurrence=effect.occurrence,
            check="telemetry",
            cohort_size=observable.cohort_size,
            probability=effect.telemetry_probability,
        )
        registration_rate = registration_count / observable.cohort_size
        telemetry_rate = telemetry_count / observable.cohort_size
        # Thresholds are supplied by policy when a profile transition is dispatched.
        registration = LayerCheck(
            check_id=_check_id(cause, "registration"),
            kind="REGISTRATION",
            passed_count=registration_count,
            cohort_size=observable.cohort_size,
            rate=registration_rate,
            threshold=registration_threshold,
            passed=registration_rate >= registration_threshold,
        )
        telemetry = LayerCheck(
            check_id=_check_id(cause, "telemetry"),
            kind="TELEMETRY",
            passed_count=telemetry_count,
            cohort_size=observable.cohort_size,
            rate=telemetry_rate,
            threshold=telemetry_threshold,
            passed=telemetry_rate >= telemetry_threshold,
        )
        updated = observable.model_copy(
            update={
                "registration_status": (
                    RegistrationStatus.REGISTERED
                    if registration.passed
                    else RegistrationStatus.FAILED
                ),
                "attach_success_rate": registration.rate,
                "telemetry_status": (
                    TelemetryStatus.ACKED if telemetry.passed else TelemetryStatus.MISSING
                ),
                "telemetry_ack_rate": telemetry.rate,
            }
        )
        return EffectResult(updated, True, registration, telemetry)


def _check_id(cause: str, kind: str) -> str:
    return hashlib.sha256(f"check\0{cause}\0{kind}".encode()).hexdigest()[:32]
