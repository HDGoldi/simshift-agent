# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Opt-in fixtures for real local dependencies."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from patterns.capability_aware_router.decider_client import DeciderClient

_ROOT = Path(__file__).resolve().parents[2]


def require_opt_in(variable: str) -> None:
    """Skip only when an explicit opt-in is absent."""

    if os.environ.get(variable) != "1":
        pytest.skip(f"set {variable}=1")


def required_environment(variable: str) -> str:
    value = os.environ.get(variable)
    if not value:
        pytest.fail(f"{variable} is required after opt-in", pytrace=False)
    return value


@pytest.fixture
def real_decider_endpoint(request: pytest.FixtureRequest) -> Iterator[tuple[str, Path]]:
    """Use an existing service or start the explicitly pinned local runtime."""

    if request.node.get_closest_marker("aws_integration") is not None:
        require_opt_in("SIMSHIFT_RUN_AWS_INTEGRATION")
    elif request.node.get_closest_marker("production_path") is not None:
        require_opt_in("SIMSHIFT_RUN_PRODUCTION_PATH")
    else:
        require_opt_in("SIMSHIFT_RUN_REAL_DECIDER")
    manifest = Path(required_environment("STRANDS_DECIDER_MANIFEST"))
    if not manifest.is_file():
        pytest.fail(f"STRANDS_DECIDER_MANIFEST is not a file: {manifest}", pytrace=False)
    configured_url = os.environ.get("STRANDS_DECIDER_URL")
    process: subprocess.Popen[str] | None = None
    url = configured_url or "http://127.0.0.1:8099"
    if configured_url is None:
        for variable in ("STRANDS_DECIDER_MODEL_DIR", "STRANDS_DECIDER_PYTHON", "HF_HOME"):
            required_environment(variable)
        process = subprocess.Popen(
            [str(_ROOT / "scripts" / "run-local-decider.sh")],
            cwd=_ROOT,
            env=os.environ.copy(),
            text=True,
        )
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(
                    f"local Decider exited during startup with status {process.returncode}",
                    pytrace=False,
                )
            try:
                DeciderClient(url, connect_timeout=1, read_timeout=2).health()
                break
            except Exception:  # startup polling must tolerate incomplete service initialization
                time.sleep(1)
        else:
            process.terminate()
            pytest.fail("local Decider did not become healthy within 300 seconds", pytrace=False)
    try:
        yield url, manifest
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
