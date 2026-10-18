# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Duplicate-safe fixture loading, truth splitting, and incident state storage."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Final, cast

from pydantic import ValidationError

from simshift.domain.enums import (
    Action,
    DeliveryOutcome,
    ManagementKind,
    ProfileState,
    Reachability,
    RegistrationStatus,
    ScenarioId,
    TelemetryStatus,
)
from simshift.domain.models import (
    BlockedProposalAudit,
    EvaluatorTruth,
    ObservableIncident,
    PolicyMetadata,
    ScenarioFixtureEnvelope,
    TransitionRecord,
)

_MAX_FIXTURE_BYTES: Final = 256 * 1024
_TOP_LEVEL_KEYS: Final = {
    "schema_version",
    "fixture_revision",
    "scenario_id",
    "default_seed",
    "observable_initial_state",
    "policy_metadata",
    "_evaluator_truth",
}
_EXPECTED_EFFECT_KEYS: Final = {
    (Action.RETRY_CONNECTION, 1),
    (Action.RETRY_CONNECTION, 2),
    (Action.TRY_ALLOWED_OPERATOR, 1),
    (Action.INVESTIGATE_DEVICE, 1),
    (Action.INVESTIGATE_DATA_PATH, 1),
    (Action.EVALUATE_PROFILE_CHANGE, 1),
    (Action.ESCALATE_OR_WAIT, 1),
}
_TRUTH_PATH_SEGMENTS: Final = {
    "leakage_canary",
    "hidden_cause",
    "acceptable_next_actions",
    "effects",
    "action",
    "occurrence",
    "evidence_added",
    "registration_probability",
    "telemetry_probability",
    "delivery_outcome",
    "target_profile_id",
}


class FixtureError(ValueError):
    """A fixture is not safe or internally consistent."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise FixtureError(f"non-finite JSON number: {value}")


def _has_external_reference(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return "://" in lowered or lowered.startswith(("www.", "urn:"))
    if isinstance(value, list):
        return any(_has_external_reference(item) for item in value)
    if isinstance(value, dict):
        return any(_has_external_reference(item) for item in value.values())
    return False


def _sanitized_truth_validation_error(error: ValidationError) -> FixtureError:
    codes: list[str] = []
    for detail in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        path_parts = [
            str(part)
            if isinstance(part, int) or part in _TRUTH_PATH_SEGMENTS
            else "<unexpected_field>"
            for part in detail["loc"]
        ]
        path = ".".join(path_parts) if path_parts else "<model>"
        error_type = detail.get("type", "validation_error")
        codes.append(f"{path}:{error_type}")
    summary = ", ".join(dict.fromkeys(codes)) or "<model>:validation_error"
    return FixtureError(f"evaluator truth validation failed: {summary}")


class TruthHandle:
    """Opaque capability passed only to the virtual fleet engine."""

    __slots__ = ("__truth",)

    def __init__(self, truth: EvaluatorTruth) -> None:
        self.__truth = truth

    def __repr__(self) -> str:
        return "TruthHandle(<opaque>)"


def _resolve_truth(handle: TruthHandle) -> EvaluatorTruth:
    """Simulator-only package hook; application code must not call this."""

    return cast(EvaluatorTruth, handle._TruthHandle__truth)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class ScenarioParts:
    """Separated public state, policy state, and opaque evaluator capability."""

    observable: ObservableIncident
    policy: PolicyMetadata
    truth_handle: TruthHandle
    fixture_revision: str
    default_seed: int


@dataclass
class IncidentRuntime:
    """One lock-protected in-memory synthetic incident aggregate."""

    observable: ObservableIncident
    policy: PolicyMetadata
    truth_handle: TruthHandle
    fixture_revision: str
    default_seed: int
    lock: RLock = field(default_factory=RLock, repr=False)
    transitions: dict[str, TransitionRecord] = field(default_factory=dict)
    audits: dict[str, BlockedProposalAudit] = field(default_factory=dict)

    @classmethod
    def from_parts(cls, parts: ScenarioParts) -> IncidentRuntime:
        return cls(
            observable=parts.observable,
            policy=parts.policy,
            truth_handle=parts.truth_handle,
            fixture_revision=parts.fixture_revision,
            default_seed=parts.default_seed,
        )


class ScenarioRepository:
    """Load the two normative local fixtures without exposing evaluator truth."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[3] / "scenarios"

    def path_for(self, scenario_id: ScenarioId | str) -> Path:
        scenario = ScenarioId(scenario_id)
        return self.root / (
            "br_profile.json" if scenario is ScenarioId.BR_PROFILE else "offline.json"
        )

    def load(self, scenario: ScenarioId | str | Path) -> ScenarioParts:
        if isinstance(scenario, Path):
            expected_scenario = None
            path = scenario
        else:
            expected_scenario = ScenarioId(scenario)
            path = self.path_for(expected_scenario)
        try:
            raw_bytes = path.read_bytes()
        except OSError as error:
            raise FixtureError(f"cannot read fixture {path.name}: {error}") from error
        if len(raw_bytes) > _MAX_FIXTURE_BYTES:
            raise FixtureError("fixture exceeds 256 KiB")
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FixtureError("fixture must be UTF-8") from error
        try:
            raw = json.loads(
                text,
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_constant,
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise FixtureError(f"invalid fixture JSON: {error}") from error
        if not isinstance(raw, dict) or set(raw) != _TOP_LEVEL_KEYS:
            raise FixtureError("fixture must contain exactly the seven documented top-level keys")
        if _has_external_reference(raw):
            raise FixtureError("fixtures cannot contain URLs or external references")

        truth_raw = raw.pop("_evaluator_truth")
        try:
            envelope = ScenarioFixtureEnvelope.model_validate_json(
                json.dumps(raw, separators=(",", ":"), allow_nan=False)
            )
        except ValueError as error:
            raise FixtureError(f"fixture schema validation failed: {error}") from error
        try:
            truth = EvaluatorTruth.model_validate_json(
                json.dumps(truth_raw, separators=(",", ":"), allow_nan=False)
            )
        except ValidationError as error:
            raise _sanitized_truth_validation_error(error) from error
        except (TypeError, ValueError) as error:
            raise FixtureError(
                "evaluator truth validation failed: <model>:invalid_value"
            ) from error
        self._validate_cross_fields(envelope, truth)
        if expected_scenario is not None and envelope.scenario_id is not expected_scenario:
            raise FixtureError("fixture scenario ID does not match the requested scenario")
        return ScenarioParts(
            observable=envelope.observable_initial_state,
            policy=envelope.policy_metadata,
            truth_handle=TruthHandle(truth),
            fixture_revision=envelope.fixture_revision,
            default_seed=envelope.default_seed,
        )

    def load_all(self) -> dict[ScenarioId, ScenarioParts]:
        parts = {scenario: self.load(scenario) for scenario in ScenarioId}
        truths = [_resolve_truth(item.truth_handle) for item in parts.values()]
        canaries = [truth.leakage_canary for truth in truths]
        if len(set(canaries)) != len(canaries):
            raise FixtureError("fixture canaries must be unique")
        return parts

    def load_runtime(self, scenario: ScenarioId | str) -> IncidentRuntime:
        return IncidentRuntime.from_parts(self.load(scenario))

    @staticmethod
    def _validate_cross_fields(envelope: ScenarioFixtureEnvelope, truth: EvaluatorTruth) -> None:
        observable = envelope.observable_initial_state
        policy = envelope.policy_metadata
        if envelope.scenario_id is not observable.incident_id:
            raise FixtureError("envelope and observable scenario IDs must match")
        if (
            observable.observation_revision != 0
            or observable.connection_retry_count != 0
            or observable.transition_count != 0
            or any(observable.action_counts.values())
            or policy.in_flight_transition_id is not None
            or policy.used_transition_ids
            or policy.consumed_approval_ids
        ):
            raise FixtureError("fixture initial counters and transaction state must be empty")

        enabled = [profile for profile in policy.profiles if profile.state is ProfileState.ENABLED]
        if len(enabled) != 1 or enabled[0].profile_id != observable.active_profile_id:
            raise FixtureError("exactly one profile must be enabled and observable")
        if any(profile.owner_id != policy.owner_id for profile in policy.profiles):
            raise FixtureError("all profiles must belong to the policy owner")
        if any(
            profile.state is not ProfileState.INSTALLED_DISABLED
            for profile in policy.profiles
            if profile.profile_id != observable.active_profile_id
        ):
            raise FixtureError("every non-active profile must be installed-disabled")

        selected = [operator for operator in policy.operators if operator.currently_selected]
        if len(selected) != 1 or selected[0].operator_id not in enabled[0].allowed_operator_ids:
            raise FixtureError("exactly one selected operator must belong to the active profile")
        alternatives = any(
            operator.available
            and operator.permitted_on_active_profile
            and not operator.currently_selected
            for operator in policy.operators
        )
        if observable.allowed_alternative_operator_available != alternatives:
            raise FixtureError("observable alternative-operator availability is inconsistent")
        disabled_exists = any(
            profile.state is ProfileState.INSTALLED_DISABLED for profile in policy.profiles
        )
        if observable.alternative_profile_installed != disabled_exists:
            raise FixtureError("observable alternate-profile inventory is inconsistent")

        expected_reachability = (
            Reachability.REACHABLE if policy.management.reachable else Reachability.UNREACHABLE
        )
        if (
            observable.ipa_available != policy.ipa_available
            or observable.eim_associated != policy.eim_associated
            or observable.management_reachability is not expected_reachability
        ):
            raise FixtureError("observable management facts must equal policy facts")
        management = policy.management
        if management.kind is ManagementKind.NONE:
            if management.reachable or management.age_seconds or management.max_age_seconds:
                raise FixtureError("NONE management channel must be unreachable and zero-aged")
        elif management.max_age_seconds <= 0:
            raise FixtureError("management channels require a positive maximum age")
        if management.reachable and management.age_seconds > management.max_age_seconds:
            raise FixtureError("reachable management evidence cannot already be stale")

        registration_pass = observable.attach_success_rate >= policy.registration_threshold
        telemetry_pass = observable.telemetry_ack_rate >= policy.telemetry_threshold
        if registration_pass != (observable.registration_status is RegistrationStatus.REGISTERED):
            raise FixtureError("registration status and threshold are inconsistent")
        if telemetry_pass != (observable.telemetry_status is TelemetryStatus.ACKED):
            raise FixtureError("telemetry status and threshold are inconsistent")

        operator_ids = {operator.operator_id for operator in policy.operators}
        profile_ids = {profile.profile_id for profile in policy.profiles}
        if any(
            operator_id not in operator_ids
            for profile in policy.profiles
            for operator_id in profile.allowed_operator_ids
        ):
            raise FixtureError("profile references an unknown operator")
        if {
            (effect.action, effect.occurrence) for effect in truth.effects
        } != _EXPECTED_EFFECT_KEYS:
            raise FixtureError("fixture must define the complete occurrence-indexed effect set")
        active_id = observable.active_profile_id
        for effect in truth.effects:
            diagnostic = effect.action in {
                Action.INVESTIGATE_DEVICE,
                Action.INVESTIGATE_DATA_PATH,
                Action.ESCALATE_OR_WAIT,
            }
            state_changing = effect.action in {
                Action.RETRY_CONNECTION,
                Action.TRY_ALLOWED_OPERATOR,
                Action.EVALUATE_PROFILE_CHANGE,
            }
            if diagnostic and (
                effect.registration_probability is not None
                or effect.telemetry_probability is not None
                or effect.delivery_outcome is not DeliveryOutcome.NOT_APPLICABLE
                or effect.target_profile_id is not None
            ):
                raise FixtureError("diagnostic and escalation effects cannot mutate telecom state")
            if state_changing and (
                effect.registration_probability is None or effect.telemetry_probability is None
            ):
                raise FixtureError("state-changing effects require both probabilities")
            if effect.action is Action.EVALUATE_PROFILE_CHANGE:
                if (
                    effect.delivery_outcome is DeliveryOutcome.NOT_APPLICABLE
                    or effect.target_profile_id not in profile_ids
                    or effect.target_profile_id == active_id
                ):
                    raise FixtureError("profile effect requires a different installed target")
                target = next(
                    p for p in policy.profiles if p.profile_id == effect.target_profile_id
                )
                if target.state is not ProfileState.INSTALLED_DISABLED:
                    raise FixtureError("profile effect target must be installed-disabled")
            elif (
                effect.target_profile_id is not None
                or effect.delivery_outcome is not DeliveryOutcome.NOT_APPLICABLE
            ):
                raise FixtureError("only profile evaluation may define target or delivery")

        public_strings = {
            str(value)
            for enum_type in (
                Action,
                DeliveryOutcome,
                ManagementKind,
                ProfileState,
                Reachability,
                RegistrationStatus,
                ScenarioId,
                TelemetryStatus,
            )
            for value in enum_type
        }
        public_strings.update(profile_ids)
        public_strings.update(operator_ids)
        if truth.leakage_canary in public_strings:
            raise FixtureError("evaluator canary must not equal a public token")
