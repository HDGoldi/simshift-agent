# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import json

from simshift.cli import main


def test_offline_forced_profile_proposal_blocks_without_mutation(capsys) -> None:
    exit_code = main(
        [
            "policy-check",
            "--scenario",
            "OFFLINE",
            "--seed",
            "20261019",
            "--action",
            "evaluate_profile_change",
            "--approval",
            "granted",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "MANAGEMENT_UNREACHABLE"
    assert result["transition_id"] is None
    assert result["profile_unchanged"] is True
    assert result["state_unchanged"] is True
    assert result["approval_consumed"] is False
    assert result["command_created"] is False
