# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Deterministic telecom capability filtering from public facts only."""

from __future__ import annotations

from patterns.capability_aware_router.filters import filter_options
from patterns.capability_aware_router.schemas import FilterResult, QuestionOption
from simshift.domain.enums import Action, ProfileState, Reachability
from simshift.domain.models import ObservableIncident, PolicyMetadata

from .options import ACTION_OPTIONS


class SimshiftCapabilityFilter:
    """A state-bound implementation of the portable capability filter protocol."""

    def __init__(self, observable: ObservableIncident, policy: PolicyMetadata) -> None:
        self.observable = observable
        self.policy = policy

    def filter(self, options: tuple[QuestionOption, ...] = ACTION_OPTIONS) -> FilterResult:
        return filter_actions(self.observable, self.policy, options)


def filter_actions(
    observable: ObservableIncident,
    policy: PolicyMetadata,
    options: tuple[QuestionOption, ...] = ACTION_OPTIONS,
) -> FilterResult:
    """Return stable eligible/removal partitions without consulting evaluator truth."""

    def reason(option: QuestionOption) -> str | None:
        action = Action(option.label)
        if action is Action.RETRY_CONNECTION:
            if observable.management_reachability is Reachability.UNREACHABLE:
                return "REMOTE_COMMAND_PATH_UNAVAILABLE"
            if observable.connection_retry_count >= 2:
                return "RETRY_LIMIT_REACHED"
        elif action is Action.TRY_ALLOWED_OPERATOR:
            selected = next(
                operator for operator in policy.operators if operator.currently_selected
            )
            alternative = any(
                operator.operator_id != selected.operator_id
                and operator.permitted_on_active_profile
                and operator.available
                for operator in policy.operators
            )
            if not alternative:
                return "NO_ALLOWED_ALTERNATE_OPERATOR"
        elif action in {Action.INVESTIGATE_DEVICE, Action.INVESTIGATE_DATA_PATH}:
            if observable.action_counts[action] >= 1:
                return "DIAGNOSTIC_ALREADY_PERFORMED"
        elif action is Action.EVALUATE_PROFILE_CHANGE:
            has_target = any(
                profile.state is ProfileState.INSTALLED_DISABLED
                and profile.profile_id != observable.active_profile_id
                for profile in policy.profiles
            )
            if not has_target:
                return "NO_INSTALLED_TARGET"
            if observable.management_reachability is Reachability.UNREACHABLE:
                return "MANAGEMENT_UNREACHABLE"
            if observable.transition_count >= policy.max_transitions:
                return "TRANSITION_LIMIT_REACHED"
            if policy.in_flight_transition_id is not None:
                return "TRANSITION_IN_FLIGHT"
        return None

    return filter_options(options, reason)
