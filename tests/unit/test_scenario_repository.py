# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import pytest

from simshift.scenarios.repository import FixtureError, ScenarioRepository


def test_normative_fixtures_load_as_split_parts() -> None:
    parts = ScenarioRepository().load_all()
    assert set(item.observable.incident_id for item in parts.values()) == set(parts)
    assert "opaque" in repr(next(iter(parts.values())).truth_handle)
    assert "EVAL_ONLY" not in repr(next(iter(parts.values())).truth_handle)


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    fixture = tmp_path / "bad.json"
    fixture.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(FixtureError, match="duplicate JSON key"):
        ScenarioRepository().load(fixture)


def test_cross_field_mismatch_is_rejected(tmp_path: Path) -> None:
    source = ScenarioRepository().path_for("BR_PROFILE").read_text()
    fixture = tmp_path / "bad.json"
    fixture.write_text(source.replace('"incident_id": "BR_PROFILE"', '"incident_id": "OFFLINE"', 1))
    with pytest.raises(FixtureError, match="scenario IDs"):
        ScenarioRepository().load(fixture)
