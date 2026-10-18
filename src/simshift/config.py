# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Deterministic behavior identity separated from environment evidence."""

from __future__ import annotations

import hashlib
import json
import platform
from importlib import metadata
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from simshift.decision.options import ACTION_REGISTRY_VERSION
from simshift.domain.enums import ScenarioId
from simshift.domain.models import StrictFrozenModel
from simshift.simulator.engine import SIMULATOR_VERSION

GATE_POLICY_VERSION = "profile-gates-v1"


class RunConfig(StrictFrozenModel):
    scenario_id: ScenarioId
    fixture_revision: str = Field(min_length=1, max_length=32)
    seed: int = Field(ge=0, le=2**32 - 1)
    approval: Literal["granted", "denied"] = "denied"
    max_steps: int = Field(default=4, ge=1, le=4)
    confidence_floor: float = Field(default=0.20, ge=0.0, le=1.0)
    action_registry_version: str = ACTION_REGISTRY_VERSION
    simulator_version: str = SIMULATOR_VERSION
    gate_policy_version: str = GATE_POLICY_VERSION

    @field_validator("confidence_floor")
    @classmethod
    def finite_confidence(cls, value: float) -> float:
        if not value == value or value in (float("inf"), float("-inf")):
            raise ValueError("confidence floor must be finite")
        return value

    @property
    def behavior_config_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))

    @property
    def run_id(self) -> str:
        value = f"run\0{self.scenario_id.value}\0{self.behavior_config_hash}"
        return hashlib.sha256(value.encode()).hexdigest()[:24]


class EnvironmentEvidence(StrictFrozenModel):
    lockfile_sha256: str
    source_revision: str | None = None
    decider_endpoint_class: Literal["LOOPBACK"] = "LOOPBACK"
    trusted_manifest_sha256: str | None = None
    explainer_mode: Literal["local-test-double", "bedrock"]
    bedrock_region: str | None = None
    bedrock_model_reference: str | None = None
    trace_destination_class: Literal["LOCAL_FILE"] = "LOCAL_FILE"
    dependency_versions: dict[str, str]

    @property
    def environment_evidence_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


def collect_environment_evidence(
    *,
    project_root: Path,
    trusted_manifest_sha256: str,
    explainer_mode: Literal["local-test-double", "bedrock"],
    bedrock_region: str | None = None,
    bedrock_model_reference: str | None = None,
) -> EnvironmentEvidence:
    """Capture reproducible local inputs without invoking Git or external services."""

    lockfile = project_root / "uv.lock"
    try:
        lockfile_sha256 = hashlib.sha256(lockfile.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError(f"cannot hash uv.lock: {error}") from error
    versions = {"python": platform.python_version()}
    for distribution in ("mypy", "pydantic", "pytest", "ruff", "strands-agents"):
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError as error:
            raise ValueError(f"required distribution is not installed: {distribution}") from error
    return EnvironmentEvidence(
        lockfile_sha256=lockfile_sha256,
        trusted_manifest_sha256=trusted_manifest_sha256,
        explainer_mode=explainer_mode,
        bedrock_region=bedrock_region,
        bedrock_model_reference=bedrock_model_reference,
        dependency_versions=versions,
    )


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
