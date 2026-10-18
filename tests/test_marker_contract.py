# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Protect the exact opt-in skip contract."""

from __future__ import annotations

import pytest

from tests.integration.conftest import require_opt_in, required_environment


@pytest.mark.parametrize(
    "variable",
    [
        "SIMSHIFT_RUN_REAL_DECIDER",
        "SIMSHIFT_RUN_PRODUCTION_PATH",
        "SIMSHIFT_RUN_AWS_INTEGRATION",
    ],
)
def test_absent_opt_in_has_actionable_exact_skip(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(pytest.skip.Exception, match=rf"^set {variable}=1$"):
        require_opt_in(variable)


def test_missing_prerequisite_fails_after_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRANDS_DECIDER_MANIFEST", raising=False)
    with pytest.raises(pytest.fail.Exception, match="required after opt-in"):
        required_environment("STRANDS_DECIDER_MANIFEST")
