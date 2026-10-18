# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Stable action registry shared by SIMShift request builders."""

from types import MappingProxyType

from patterns.capability_aware_router.schemas import QuestionOption
from simshift.domain.enums import Action

ACTION_REGISTRY_VERSION = "simshift-actions-v1"

TOOL_NAME_BY_ACTION = MappingProxyType(
    {
        Action.RETRY_CONNECTION: "simulate_retry_with_backoff",
        Action.TRY_ALLOWED_OPERATOR: "simulate_operator_reselection",
        Action.INVESTIGATE_DEVICE: "query_firmware_modem_diagnostics",
        Action.INVESTIGATE_DATA_PATH: "query_apn_session_app_diagnostics",
        Action.EVALUATE_PROFILE_CHANGE: "prepare_guarded_profile_transition",
        Action.ESCALATE_OR_WAIT: "defer_or_escalate",
    }
)

ACTION_OPTIONS = (
    QuestionOption(
        label=Action.RETRY_CONNECTION.value,
        description="Retry the reachable remote connection with bounded backoff.",
    ),
    QuestionOption(
        label=Action.TRY_ALLOWED_OPERATOR.value,
        description="Try another currently permitted operator for the active profile.",
    ),
    QuestionOption(
        label=Action.INVESTIGATE_DEVICE.value,
        description="Inspect cached firmware and modem diagnostics.",
    ),
    QuestionOption(
        label=Action.INVESTIGATE_DATA_PATH.value,
        description="Inspect cached APN, session, and application diagnostics.",
    ),
    QuestionOption(
        label=Action.EVALUATE_PROFILE_CHANGE.value,
        description="Prepare a guarded proposal for an installed alternate profile.",
    ),
    QuestionOption(
        label=Action.ESCALATE_OR_WAIT.value,
        description="Stop automation safely and escalate or wait for more evidence.",
    ),
)
