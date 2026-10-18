# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

from simshift.tracing.recorder import TraceRecorder
from tests.unit.test_trace_events import run_started


def test_atomic_jsonl_write_has_one_valid_line(tmp_path: Path) -> None:
    target = tmp_path / "trace.jsonl"
    recorder = TraceRecorder(target)
    recorder.append(run_started())
    recorder.write()
    lines = target.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "run_started"
    assert not list(tmp_path.glob("*.tmp"))
