# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Production adapter around the canonical strict loopback Decider client."""

from __future__ import annotations

import hashlib
import os
import stat
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, TypeVar

from pydantic import Field, StringConstraints, field_validator, model_validator

from patterns.capability_aware_router.decider_client import (
    DeciderClient,
    DeciderHttpStatusError,
    DeciderProtocolError,
    DeciderTransportError,
    HealthResponse,
    decode_json_object,
)
from patterns.capability_aware_router.schemas import (
    ChoiceDecision,
    QuestionOption,
    TypedChoiceQuestion,
)
from simshift.decision.projection import observable_projection
from simshift.domain.models import ObservableIncident, StrictFrozenModel

SOURCE_COMMIT = "930e6d5de16309be32579f5631a7369a3322140c"
CHECKPOINT_COMMIT = "216d1ccb46a9e9b036eb9187b248db98480f77d4"
BASE_COMMIT = "b1485b2fa6dfa1287294f269f5fb618e03d52d7c"
DECISION_INSTRUCTIONS = (
    "Given the current cellular connectivity symptoms, existing diagnostic evidence, and "
    "admissible tools, which next tool is most useful for safely advancing service restoration? "
    "Choose one listed tool. Profile evaluation neither authorizes nor executes a profile change."
)
HexSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
RelativePath = Annotated[str, StringConstraints(min_length=1, max_length=1000)]
_ResultT = TypeVar("_ResultT")
EvidenceSink = Callable[[str, dict[str, Any]], None]


class DeploymentReference(StrictFrozenModel):
    repository: str = Field(min_length=1, max_length=300)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")


class ExpectedHealth(StrictFrozenModel):
    model: str = Field(min_length=1, max_length=300)
    checkpoint: str = Field(min_length=1, max_length=1000)
    base_model: str = Field(min_length=1, max_length=300)
    device: str = Field(min_length=1, max_length=100)
    max_length: Literal[4096]
    num_slots: Literal[24]
    vision: Literal[False]


class FileManifestEntry(StrictFrozenModel):
    path: RelativePath
    bytes: int = Field(ge=0, le=16 * 1024**3)
    sha256: HexSha

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        _validate_relative_path(value)
        return value


class FileManifest(StrictFrozenModel):
    schema_version: Literal["1.0"]
    files: tuple[FileManifestEntry, ...] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_order(self) -> FileManifest:
        paths = [entry.path for entry in self.files]
        if paths != sorted(paths, key=lambda item: item.encode("utf-8")):
            raise ValueError("file manifest paths must be sorted by UTF-8 bytes")
        if len(set(paths)) != len(paths):
            raise ValueError("file manifest paths must be unique")
        return self


class LogicalArtifact(StrictFrozenModel):
    logical_name: str = Field(min_length=1, max_length=100)
    paths: tuple[RelativePath, ...] = Field(min_length=1, max_length=128)
    merkle_root: HexSha | None = None

    @model_validator(mode="after")
    def validate_paths(self) -> LogicalArtifact:
        for path in self.paths:
            _validate_relative_path(path)
        if tuple(sorted(self.paths, key=lambda item: item.encode("utf-8"))) != self.paths:
            raise ValueError("logical artifact paths must be sorted by UTF-8 bytes")
        if len(set(self.paths)) != len(self.paths):
            raise ValueError("logical artifact paths must be unique")
        if (len(self.paths) > 1) != (self.merkle_root is not None):
            raise ValueError("multi-file logical artifacts require exactly one Merkle root")
        return self


class TrustedDeciderManifest(StrictFrozenModel):
    schema_version: Literal["1.1"]
    source: DeploymentReference
    checkpoint: DeploymentReference
    base: DeploymentReference
    expected_health: ExpectedHealth
    file_manifest_path: RelativePath
    file_manifest_sha256: HexSha
    provenance_path: RelativePath
    logical_artifacts: tuple[LogicalArtifact, ...] = Field(min_length=5, max_length=16)

    @model_validator(mode="after")
    def validate_pins(self) -> TrustedDeciderManifest:
        _validate_relative_path(self.file_manifest_path)
        _validate_relative_path(self.provenance_path)
        if self.source.commit != SOURCE_COMMIT:
            raise ValueError("unexpected Decider source commit")
        if self.checkpoint.commit != CHECKPOINT_COMMIT:
            raise ValueError("unexpected checkpoint commit")
        if self.base.commit != BASE_COMMIT:
            raise ValueError("unexpected base-model commit")
        names = {artifact.logical_name for artifact in self.logical_artifacts}
        required = {
            "source_snapshot",
            "adapter_snapshot",
            "base_snapshot",
            "model_provenance",
            "dependency_lock",
        }
        if not required <= names:
            raise ValueError("manifest is missing required logical artifacts")
        if len(names) != len(self.logical_artifacts):
            raise ValueError("logical artifact names must be unique")
        provenance = next(
            artifact
            for artifact in self.logical_artifacts
            if artifact.logical_name == "model_provenance"
        )
        if provenance.paths != (self.provenance_path,):
            raise ValueError("model provenance artifact must match provenance_path")
        return self


class ManifestError(ValueError):
    """The local trusted manifest is missing or structurally invalid."""


class DependencyIdentityError(RuntimeError):
    """The local artifacts or endpoint do not match trusted expectations."""


class DeciderUnavailable(RuntimeError):
    """Retryable Decider failures exhausted the bounded attempts."""


def _validate_relative_path(value: str) -> None:
    pure = PurePosixPath(value)
    if (
        value != pure.as_posix()
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("artifact paths must be normalized relative POSIX paths")


def _read_bounded(path: Path, limit: int, description: str) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ManifestError(f"cannot read {description}: {error}") from error
    if len(raw) > limit:
        raise ManifestError(f"{description} exceeds {limit} bytes")
    return raw


def _resolve_regular_file(root: Path, relative: str) -> Path:
    candidate = root / relative
    try:
        metadata = os.lstat(candidate)
    except OSError as error:
        raise DependencyIdentityError(f"artifact is missing: {relative}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise DependencyIdentityError(f"artifact is not a regular non-symlink file: {relative}")
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise DependencyIdentityError(f"artifact escapes the manifest root: {relative}") from error
    return candidate


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as error:
        raise DependencyIdentityError(f"cannot hash artifact {path.name}: {error}") from error
    return size, digest.hexdigest()


def _merkle_root(entries: tuple[FileManifestEntry, ...]) -> str:
    leaves = []
    for entry in entries:
        leaf = (
            entry.path.encode("utf-8")
            + b"\0"
            + str(entry.bytes).encode("ascii")
            + b"\0"
            + bytes.fromhex(entry.sha256)
        )
        leaves.append(hashlib.sha256(leaf).digest())
    return hashlib.sha256(b"".join(leaves)).hexdigest()


def _verify_provenance(
    root: Path,
    manifest: TrustedDeciderManifest,
    files: dict[str, FileManifestEntry],
) -> None:
    provenance_entry = files[manifest.provenance_path]
    provenance_raw = _read_bounded(
        _resolve_regular_file(root, manifest.provenance_path), 64 * 1024, "model provenance"
    )
    if hashlib.sha256(provenance_raw).hexdigest() != provenance_entry.sha256:
        raise DependencyIdentityError("model provenance hash does not match file manifest")
    try:
        provenance = decode_json_object(provenance_raw)
    except DeciderProtocolError as error:
        raise DependencyIdentityError("model provenance is not strict JSON") from error
    if provenance.get("base_model") != manifest.base.repository:
        raise DependencyIdentityError("model provenance base_model does not match manifest")
    if provenance.get("base_model_revision") != manifest.base.commit:
        raise DependencyIdentityError("declared inferred base revision does not match manifest")
    revision_note = provenance.get("base_model_revision_note")
    if not isinstance(revision_note, str) or not revision_note.startswith("inferred:"):
        raise DependencyIdentityError("base revision provenance must remain qualified as inferred")

    adapter = next(
        artifact
        for artifact in manifest.logical_artifacts
        if artifact.logical_name == "adapter_snapshot"
    )
    by_name = {PurePosixPath(path).name: files[path].sha256 for path in adapter.paths}
    expected_digests = {
        "adapter_model.safetensors": provenance.get("adapter_sha256"),
        "head.safetensors": provenance.get("head_sha256"),
        "strands_decider_config.json": provenance.get("hobson_config_sha256"),
        "train_config.json": provenance.get("train_config_sha256"),
    }
    for name, expected in expected_digests.items():
        if not isinstance(expected, str) or by_name.get(name) != expected:
            raise DependencyIdentityError(f"model provenance does not bind {name}")


def load_trusted_manifest(path: Path) -> tuple[TrustedDeciderManifest, str]:
    try:
        manifest_metadata = os.lstat(path)
    except OSError as error:
        raise ManifestError(f"cannot read Decider manifest: {error}") from error
    if not stat.S_ISREG(manifest_metadata.st_mode):
        raise ManifestError("Decider manifest must be a regular non-symlink file")
    raw = _read_bounded(path, 256 * 1024, "Decider manifest")
    try:
        decode_json_object(raw)
        manifest = TrustedDeciderManifest.model_validate_json(raw)
    except (DeciderProtocolError, ValueError) as error:
        raise ManifestError(f"invalid Decider manifest: {error}") from error

    root = path.parent
    file_manifest_raw = _read_bounded(
        _resolve_regular_file(root, manifest.file_manifest_path),
        2 * 1024 * 1024,
        "Decider file manifest",
    )
    if hashlib.sha256(file_manifest_raw).hexdigest() != manifest.file_manifest_sha256:
        raise DependencyIdentityError("Decider file manifest hash does not match trust anchor")
    try:
        decode_json_object(file_manifest_raw)
        file_manifest = FileManifest.model_validate_json(file_manifest_raw)
    except (DeciderProtocolError, ValueError) as error:
        raise DependencyIdentityError(f"invalid Decider file manifest: {error}") from error

    files = {entry.path: entry for entry in file_manifest.files}
    referenced = {path for artifact in manifest.logical_artifacts for path in artifact.paths}
    missing = referenced - files.keys()
    if missing:
        raise DependencyIdentityError(
            f"logical artifacts are absent from file manifest: {sorted(missing)}"
        )
    if manifest.provenance_path not in files:
        raise DependencyIdentityError("model provenance is absent from file manifest")

    for entry in file_manifest.files:
        actual_size, actual_hash = _sha256_file(_resolve_regular_file(root, entry.path))
        if actual_size != entry.bytes or actual_hash != entry.sha256:
            raise DependencyIdentityError(f"artifact content mismatch: {entry.path}")
    for artifact in manifest.logical_artifacts:
        if artifact.merkle_root is not None:
            entries = tuple(files[item] for item in artifact.paths)
            if _merkle_root(entries) != artifact.merkle_root:
                raise DependencyIdentityError(
                    f"logical artifact Merkle root mismatch: {artifact.logical_name}"
                )
    _verify_provenance(root, manifest, files)
    return manifest, hashlib.sha256(raw).hexdigest()


class SimshiftDeciderAdapter:
    """Verify endpoint identity, project public state, and retry transient failures."""

    status = "REAL"
    detail = "strict loopback Decider"

    def __init__(
        self,
        *,
        origin: str,
        manifest_path: Path,
        client: DeciderClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.manifest, self.manifest_sha256 = load_trusted_manifest(manifest_path)
        self.client = client or DeciderClient(origin)
        self.sleep = sleep
        self.health: HealthResponse | None = None
        self.evidence: list[dict[str, Any]] = []

    @property
    def capacity(self) -> int:
        return self.manifest.expected_health.num_slots

    def initialize(
        self,
        *,
        evidence_sink: EvidenceSink | None = None,
    ) -> HealthResponse:
        if self.health is not None:
            return self.health
        health, attempt = self._retry(
            self.client.health,
            operation="health",
            decision_id=None,
            evidence_sink=evidence_sink,
        )
        expected = self.manifest.expected_health
        actual = {
            "model": health.model,
            "checkpoint": health.checkpoint,
            "base_model": health.base_model,
            "device": health.device,
            "max_length": health.max_length,
            "num_slots": health.num_slots,
            "vision": health.vision,
        }
        if actual != expected.model_dump(mode="json"):
            raise DependencyIdentityError("Decider health does not match the trusted manifest")
        exchange = self.client.last_exchange
        if exchange is None or exchange.path != "/health":
            raise RuntimeError("canonical Decider client did not retain health evidence")
        body = decode_json_object(exchange.response_body)
        health_evidence = {
            "manifest_hash": self.manifest_sha256,
            "expected": expected.model_dump(mode="json"),
            "actual": actual,
            "consistent": True,
            "attempt": attempt,
            "response_hash": hashlib.sha256(exchange.response_body).hexdigest(),
            "response_body_utf8": exchange.response_body.decode("utf-8"),
            "body": body,
        }
        self.health = health
        self.evidence.append({"event": "decider_health_checked", **health_evidence})
        if evidence_sink is not None:
            evidence_sink("decider_health_checked", health_evidence)
        return health

    def choose(
        self,
        observable: ObservableIncident,
        options: tuple[QuestionOption, ...],
        *,
        decision_id: str | None = None,
        evidence_sink: EvidenceSink | None = None,
    ) -> ChoiceDecision:
        health = self.initialize(evidence_sink=evidence_sink)
        question = TypedChoiceQuestion(
            name="next_recovery_step",
            instructions=DECISION_INSTRUCTIONS,
            options=options,
        )
        state = observable_projection(observable)
        decision, attempt = self._retry(
            lambda: self.client.choose(
                state=state,
                question=question,
                expected_model=health.model,
            ),
            operation="choice",
            decision_id=decision_id,
            evidence_sink=evidence_sink,
        )
        exchange = self.client.last_exchange
        if exchange is None or exchange.path != "/v1/systemone" or exchange.request_body is None:
            raise RuntimeError("canonical Decider client did not retain choice evidence")
        request = decode_json_object(exchange.request_body)
        response = decode_json_object(exchange.response_body)
        request_evidence = {
            "decision_id": decision_id or "untraced",
            "request_hash": hashlib.sha256(exchange.request_body).hexdigest(),
            "request_body_utf8": exchange.request_body.decode("utf-8"),
            "request": request,
            "attempt": attempt,
        }
        response_evidence = {
            "decision_id": decision_id or "untraced",
            "response_hash": hashlib.sha256(exchange.response_body).hexdigest(),
            "response_body_utf8": exchange.response_body.decode("utf-8"),
            "body": response,
            "model_choice": decision.model_choice,
            "probabilities": dict(decision.probabilities),
            "confidence": decision.confidence,
            "usage": decision.usage.model_dump(mode="json"),
            "latency_ms": decision.latency_ms,
            "client_latency_ms": decision.client_latency_ms,
            "extensions": dict(decision.extensions),
        }
        self.evidence.extend(
            [
                {"event": "decider_request", **request_evidence},
                {"event": "decider_response", **response_evidence},
            ]
        )
        if evidence_sink is not None:
            evidence_sink("decider_request", request_evidence)
            evidence_sink("decider_response", response_evidence)
        return decision

    def _retry(
        self,
        operation_call: Callable[[], _ResultT],
        *,
        operation: Literal["health", "choice"],
        decision_id: str | None,
        evidence_sink: EvidenceSink | None,
    ) -> tuple[_ResultT, int]:
        for attempt in range(1, 4):
            try:
                result = operation_call()
                self.evidence.append(
                    {"event": "decider_attempt", "operation": operation, "attempt": attempt}
                )
                return result, attempt
            except DeciderHttpStatusError as error:
                if not error.retryable:
                    raise
                retryable: Exception = error
            except DeciderTransportError as error:
                retryable = error
            retry_evidence = {
                "operation": operation,
                "decision_id": decision_id,
                "attempt": attempt,
                "error_class": type(retryable).__name__,
                "retrying": attempt < 3,
            }
            self.evidence.append({"event": "decider_retry", **retry_evidence})
            if evidence_sink is not None:
                evidence_sink("decider_retry", retry_evidence)
            if attempt == 3:
                raise DeciderUnavailable("Decider unavailable after three attempts") from retryable
            self.sleep(0.25 if attempt == 1 else 0.50)
        raise AssertionError("unreachable retry loop")


__all__ = [
    "BASE_COMMIT",
    "CHECKPOINT_COMMIT",
    "DECISION_INSTRUCTIONS",
    "DeciderUnavailable",
    "DependencyIdentityError",
    "FileManifest",
    "FileManifestEntry",
    "LogicalArtifact",
    "ManifestError",
    "SOURCE_COMMIT",
    "SimshiftDeciderAdapter",
    "TrustedDeciderManifest",
    "load_trusted_manifest",
]
