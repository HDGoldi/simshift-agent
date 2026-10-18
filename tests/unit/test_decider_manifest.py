# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from patterns.capability_aware_router.decider_client import HealthResponse
from simshift.integrations.decider_http import (
    BASE_COMMIT,
    CHECKPOINT_COMMIT,
    SOURCE_COMMIT,
    DependencyIdentityError,
    ManifestError,
    SimshiftDeciderAdapter,
    load_trusted_manifest,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _merkle(entries: list[dict[str, object]]) -> str:
    leaves = []
    for entry in entries:
        leaf = (
            str(entry["path"]).encode()
            + b"\0"
            + str(entry["bytes"]).encode()
            + b"\0"
            + bytes.fromhex(str(entry["sha256"]))
        )
        leaves.append(hashlib.sha256(leaf).digest())
    return hashlib.sha256(b"".join(leaves)).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object], list[dict[str, object]]]:
    contents = {
        "artifacts/adapter_model.safetensors": b"adapter",
        "artifacts/head.safetensors": b"head",
        "artifacts/strands_decider_config.json": b"config",
        "artifacts/train_config.json": b"train",
        "base/model.safetensors": b"base",
        "locks/runtime.txt": b"runtime==1\n",
        "source/server.py": b"server\n",
    }
    provenance = {
        "adapter_sha256": _sha(contents["artifacts/adapter_model.safetensors"]),
        "head_sha256": _sha(contents["artifacts/head.safetensors"]),
        "hobson_config_sha256": _sha(contents["artifacts/strands_decider_config.json"]),
        "train_config_sha256": _sha(contents["artifacts/train_config.json"]),
        "base_model": "Qwen/Qwen3.5-2B-Base",
        "base_model_revision": BASE_COMMIT,
        "base_model_revision_note": "inferred: test fixture has no immutable repository binding",
    }
    contents["artifacts/provenance.json"] = json.dumps(
        provenance, sort_keys=True, separators=(",", ":")
    ).encode()
    for relative, content in contents.items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    entries = [
        {"path": path, "bytes": len(content), "sha256": _sha(content)}
        for path, content in sorted(contents.items())
    ]
    file_manifest = {"schema_version": "1.0", "files": entries}
    file_manifest_raw = json.dumps(
        file_manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    (tmp_path / "files.manifest.json").write_bytes(file_manifest_raw)
    adapter_paths = [
        "artifacts/adapter_model.safetensors",
        "artifacts/head.safetensors",
        "artifacts/strands_decider_config.json",
        "artifacts/train_config.json",
    ]
    adapter_entries = [
        next(entry for entry in entries if entry["path"] == path)
        for path in adapter_paths
    ]
    manifest: dict[str, object] = {
        "schema_version": "1.1",
        "source": {"repository": "source", "commit": SOURCE_COMMIT},
        "checkpoint": {"repository": "checkpoint", "commit": CHECKPOINT_COMMIT},
        "base": {"repository": "Qwen/Qwen3.5-2B-Base", "commit": BASE_COMMIT},
        "expected_health": {
            "model": "model-v1-216d1ccb",
            "checkpoint": "/model",
            "base_model": "Qwen/Qwen3.5-2B-Base",
            "device": "cpu",
            "max_length": 4096,
            "num_slots": 24,
            "vision": False,
        },
        "file_manifest_path": "files.manifest.json",
        "file_manifest_sha256": _sha(file_manifest_raw),
        "provenance_path": "artifacts/provenance.json",
        "logical_artifacts": [
            {"logical_name": "source_snapshot", "paths": ["source/server.py"]},
            {
                "logical_name": "adapter_snapshot",
                "paths": adapter_paths,
                "merkle_root": _merkle(adapter_entries),
            },
            {"logical_name": "base_snapshot", "paths": ["base/model.safetensors"]},
            {
                "logical_name": "model_provenance",
                "paths": ["artifacts/provenance.json"],
            },
            {"logical_name": "dependency_lock", "paths": ["locks/runtime.txt"]},
        ],
    }
    path = tmp_path / "decider-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest, entries


def test_manifest_chain_verifies_files_roots_and_provenance(tmp_path: Path) -> None:
    path, _, _ = _fixture(tmp_path)
    loaded, digest = load_trusted_manifest(path)
    assert loaded.file_manifest_path == "files.manifest.json"
    assert digest == _sha(path.read_bytes())


def test_changed_file_manifest_bytes_fail(tmp_path: Path) -> None:
    path, _, _ = _fixture(tmp_path)
    with (tmp_path / "files.manifest.json").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(DependencyIdentityError, match="trust anchor"):
        load_trusted_manifest(path)


def test_changed_artifact_or_merkle_root_fails(tmp_path: Path) -> None:
    path, manifest, _ = _fixture(tmp_path)
    (tmp_path / "base/model.safetensors").write_bytes(b"changed")
    with pytest.raises(DependencyIdentityError, match="content mismatch"):
        load_trusted_manifest(path)

    path, manifest, _ = _fixture(tmp_path / "root")
    artifacts = manifest["logical_artifacts"]
    assert isinstance(artifacts, list)
    artifacts[1]["merkle_root"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DependencyIdentityError, match="Merkle root"):
        load_trusted_manifest(path)


def test_unsafe_path_and_modified_provenance_fail(tmp_path: Path) -> None:
    path, manifest, _ = _fixture(tmp_path)
    manifest["file_manifest_path"] = "../files.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ManifestError, match="normalized relative"):
        load_trusted_manifest(path)

    path, manifest, entries = _fixture(tmp_path / "provenance")
    provenance_path = path.parent / "artifacts/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["base_model_revision"] = "0" * 40
    provenance_raw = json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode()
    provenance_path.write_bytes(provenance_raw)
    entry = next(item for item in entries if item["path"] == "artifacts/provenance.json")
    entry.update(bytes=len(provenance_raw), sha256=_sha(provenance_raw))
    file_manifest_raw = json.dumps(
        {"schema_version": "1.0", "files": entries},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    (path.parent / "files.manifest.json").write_bytes(file_manifest_raw)
    manifest["file_manifest_sha256"] = _sha(file_manifest_raw)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DependencyIdentityError, match="base revision"):
        load_trusted_manifest(path)


def test_health_mismatch_fails_after_artifact_verification(tmp_path: Path) -> None:
    path, _, _ = _fixture(tmp_path)
    health = HealthResponse(
        status="ok",
        model="wrong-model",
        checkpoint="/model",
        base_model="Qwen/Qwen3.5-2B-Base",
        device="cpu",
        max_length=4096,
        num_slots=24,
        vision=False,
        prefix_cache=True,
    )
    client = SimpleNamespace(health=lambda: health, last_exchange=None)
    adapter = SimshiftDeciderAdapter(
        origin="http://127.0.0.1:8099",
        manifest_path=path,
        client=client,  # type: ignore[arg-type]
        sleep=lambda _: None,
    )
    with pytest.raises(DependencyIdentityError, match="health"):
        adapter.initialize()
