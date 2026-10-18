# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Idempotent virtual eUICC transition lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from simshift.domain.enums import DeliveryOutcome, ProfileState, TransitionState
from simshift.domain.models import LayerCheck, TransitionRecord
from simshift.scenarios.repository import IncidentRuntime
from simshift.verification.recovery import RecoveryResult, RecoveryVerifier

from .engine import VirtualFleetEngine


@dataclass(frozen=True)
class EuiccDispatchResult:
    transition: TransitionRecord
    registration: LayerCheck | None
    telemetry: LayerCheck | None
    recovery: RecoveryResult | None
    duplicate_suppressed: bool


class VirtualEuiccEngine:
    """Advance an approved virtual transition once; no real telecom call exists."""

    def __init__(self, runtime: IncidentRuntime, *, seed: int | None = None) -> None:
        self.runtime = runtime
        self.fleet = VirtualFleetEngine(
            runtime.truth_handle,
            runtime.fixture_revision,
            runtime.default_seed if seed is None else seed,
        )

    def dispatch(self, transition_id: str) -> EuiccDispatchResult:
        with self.runtime.lock:
            record = self.runtime.transitions.get(transition_id)
            if record is None:
                raise ValueError("unknown transition")
            if TransitionState.SENT in record.states or record.terminal:
                return EuiccDispatchResult(
                    transition=record.model_copy(update={"duplicate": True}),
                    registration=None,
                    telemetry=None,
                    recovery=None,
                    duplicate_suppressed=True,
                )

            delivery = self.fleet.profile_delivery_outcome()
            sent_states = record.states + (TransitionState.SENT,)
            if delivery is DeliveryOutcome.TIMEOUT:
                result = record.model_copy(
                    update={
                        "states": sent_states + (TransitionState.TIMED_OUT,),
                        "terminal": True,
                    }
                )
                self._finish(result)
                return EuiccDispatchResult(result, None, None, None, False)
            if delivery is DeliveryOutcome.FAIL:
                result = record.model_copy(
                    update={
                        "states": sent_states + (TransitionState.FAILED,),
                        "terminal": True,
                    }
                )
                self._finish(result)
                return EuiccDispatchResult(result, None, None, None, False)
            if delivery is not DeliveryOutcome.ACK:
                raise ValueError("profile transition requires ACK, TIMEOUT, or FAIL")

            profiles = tuple(
                profile.model_copy(
                    update={
                        "state": (
                            ProfileState.ENABLED
                            if profile.profile_id == record.target_profile_id
                            else ProfileState.INSTALLED_DISABLED
                        )
                    }
                )
                for profile in self.runtime.policy.profiles
            )
            if sum(profile.state is ProfileState.ENABLED for profile in profiles) != 1:
                raise RuntimeError("virtual eUICC update violated one-active-profile invariant")
            switched_policy = self.runtime.policy.model_copy(update={"profiles": profiles})
            switched_observable = self.runtime.observable.model_copy(
                update={"active_profile_id": record.target_profile_id}
            )
            effect_result = self.fleet.apply_profile_effect(
                switched_observable,
                cause=transition_id,
                registration_threshold=switched_policy.registration_threshold,
                telemetry_threshold=switched_policy.telemetry_threshold,
            )
            if effect_result.registration is None or effect_result.telemetry is None:
                raise RuntimeError("profile effect did not produce both layer checks")
            recovery = RecoveryVerifier.verify(effect_result.registration, effect_result.telemetry)
            final_state = (
                TransitionState.SUCCEEDED if recovery.service_restored else TransitionState.FAILED
            )
            result = record.model_copy(
                update={
                    "states": sent_states
                    + (
                        TransitionState.ACKNOWLEDGED,
                        TransitionState.ENABLED,
                        TransitionState.VERIFYING,
                        final_state,
                    ),
                    "terminal": True,
                }
            )
            self.runtime.observable = effect_result.observable
            self.runtime.policy = switched_policy.model_copy(
                update={"in_flight_transition_id": None}
            )
            self.runtime.transitions[transition_id] = result
            return EuiccDispatchResult(
                result,
                effect_result.registration,
                effect_result.telemetry,
                recovery,
                False,
            )

    def _finish(self, record: TransitionRecord) -> None:
        self.runtime.transitions[record.transition_id] = record
        self.runtime.policy = self.runtime.policy.model_copy(
            update={"in_flight_transition_id": None}
        )
