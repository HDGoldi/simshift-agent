# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest

from patterns.capability_aware_router.decider_client import (
    DeciderConfigurationError,
    DeciderProtocolError,
)
from simshift.cli import build_parser, main
from simshift.integrations.bedrock import DeterministicLocalExplainer
from simshift.integrations.decider_http import DeciderUnavailable
from simshift.scenarios.repository import ScenarioRepository
from tests.fakes.decider import InjectedChoiceProvider


def test_cli_exposes_three_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["validate-fixtures"]).command == "validate-fixtures"
    assert parser.parse_args(
        [
            "policy-check",
            "--scenario",
            "OFFLINE",
            "--seed",
            "1",
            "--action",
            "evaluate_profile_change",
        ]
    ).command == "policy-check"


def test_validate_fixtures_remains_machine_readable(capsys) -> None:
    assert main(["validate-fixtures"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VALID"


def _string_values(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(_string_values(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(_string_values(item) for item in value.values()))
    return set()


@pytest.mark.parametrize(
    ("malformation", "expected_code"),
    [
        ("duplicate_action", "<model>:value_error"),
        ("invalid_hidden_cause", "hidden_cause:enum"),
        (
            "invalid_effect_probability",
            "effects.0.registration_probability:less_than_equal",
        ),
    ],
)
def test_validate_fixtures_sanitizes_evaluator_truth_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    malformation: str,
    expected_code: str,
) -> None:
    source_repository = ScenarioRepository()
    fixture = json.loads(source_repository.path_for("BR_PROFILE").read_text())
    truth = fixture["_evaluator_truth"]
    prohibited = _string_values(truth) | {"0.995", "0.99"}
    if malformation == "duplicate_action":
        truth["acceptable_next_actions"].append(truth["acceptable_next_actions"][0])
    elif malformation == "invalid_hidden_cause":
        truth["hidden_cause"] = "EVAL_ONLY_INVALID_HIDDEN_CAUSE"
        prohibited.add(truth["hidden_cause"])
    else:
        truth["effects"][0]["registration_probability"] = 1.23456789
        prohibited.add("1.23456789")

    (tmp_path / "br_profile.json").write_text(json.dumps(fixture))
    (tmp_path / "offline.json").write_text(
        source_repository.path_for("OFFLINE").read_text()
    )
    malformed_repository = source_repository.__class__(tmp_path)
    monkeypatch.setattr(
        "simshift.cli.ScenarioRepository", lambda: malformed_repository
    )

    assert main(["validate-fixtures"]) == 2
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["status"] == "INVALID"
    assert expected_code in output["error"]
    assert captured.err == ""
    emitted = captured.out + captured.err
    assert all(secret not in emitted for secret in prohibited)


def test_validate_fixtures_sanitizes_evaluator_duplicate_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    source_repository = ScenarioRepository()
    duplicate_key = "EVAL_ONLY_DUPLICATE_KEY_CANARY"
    source = source_repository.path_for("BR_PROFILE").read_text()
    malformed = source.replace(
        '  "_evaluator_truth": {',
        f'  "_evaluator_truth": {{\n    "{duplicate_key}": 1,\n    "{duplicate_key}": 2,',
    )
    (tmp_path / "br_profile.json").write_text(malformed)
    (tmp_path / "offline.json").write_text(
        source_repository.path_for("OFFLINE").read_text()
    )
    malformed_repository = source_repository.__class__(tmp_path)
    monkeypatch.setattr(
        "simshift.cli.ScenarioRepository", lambda: malformed_repository
    )

    assert main(["validate-fixtures"]) == 2
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output == {"error": "duplicate JSON key", "status": "INVALID"}
    assert captured.err == ""
    assert duplicate_key not in captured.out + captured.err


def test_run_rejects_invalid_seed_before_dependencies() -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "run",
                "--scenario",
                "BR_PROFILE",
                "--seed",
                "-1",
                "--decider-url",
                "http://127.0.0.1:9000",
                "--decider-manifest",
                "manifest.json",
                "--explainer",
                "local-test-double",
                "--trace-out",
                "trace.jsonl",
            ]
        )
    assert error.value.code == 2


class _Adapter(InjectedChoiceProvider):
    manifest_sha256 = "a" * 64

    def __init__(self, **kwargs) -> None:
        del kwargs
        super().__init__("evaluate_profile_change")


class _Bedrock:
    status = "REAL"
    detail = "injected CLI Bedrock"
    provider = "Amazon Bedrock"
    region_name = "test-region-1"
    model_reference = "test-model"
    fail = False

    def __init__(self, **kwargs) -> None:
        del kwargs
        self.invocation_count = 0

    def request_evidence(self, observable, evidence):
        assert observable and evidence
        return {
            "prompt_hash": "b" * 64,
            "provider": self.provider,
            "region": self.region_name,
            "model_reference": self.model_reference,
        }

    def explain(self, observable, evidence):
        assert observable and evidence
        self.invocation_count += 1
        if self.fail:
            raise TimeoutError("injected")
        return "bedrock CLI explanation"


def _run_args(trace: Path, explainer: str = "local-test-double") -> list[str]:
    return [
        "run",
        "--scenario",
        "BR_PROFILE",
        "--seed",
        "20261018",
        "--approval",
        "granted",
        "--decider-url",
        "http://127.0.0.1:8099",
        "--decider-manifest",
        "manifest.json",
        "--explainer",
        explainer,
        "--trace-out",
        str(trace),
    ]


def test_cli_local_explanation_is_part_of_run_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr("simshift.cli.SimshiftDeciderAdapter", _Adapter)
    trace = tmp_path / "local.jsonl"
    assert main(_run_args(trace)) == 0
    output = json.loads(capsys.readouterr().out)
    assert "SIMULATED SIMShift outcome" in output["explanation"]
    first = json.loads(trace.read_text().splitlines()[0])
    payload = first["payload"]
    assert payload["provenance"]["explainer_model"] == {
        "configured": True,
        "detail": "deterministic local explanation",
        "invoked": False,
        "status": "LOCAL_TEST_DOUBLE",
    }
    assert payload["environment_evidence"]["trusted_manifest_sha256"] == "a" * 64
    assert payload["environment_evidence"]["lockfile_sha256"] != "a" * 64
    assert payload["environment_evidence_hash"] != "a" * 64


@pytest.mark.parametrize("fails", [False, True])
def test_cli_bedrock_success_and_failure_are_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    fails: bool,
) -> None:
    monkeypatch.setattr("simshift.cli.SimshiftDeciderAdapter", _Adapter)
    monkeypatch.setattr("simshift.cli.StrandsBedrockExplainer", _Bedrock)
    monkeypatch.setenv("BEDROCK_REGION", "test-region-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    _Bedrock.fail = fails
    trace = tmp_path / f"bedrock-{fails}.jsonl"
    assert main(_run_args(trace, "bedrock")) == 0
    output = json.loads(capsys.readouterr().out)
    event_types = [json.loads(line)["event_type"] for line in trace.read_text().splitlines()]
    if fails:
        assert output["explanation"] is None
        assert output["explanation_error"] == "TimeoutError"
        assert "bedrock_unavailable" in event_types
    else:
        assert output["explanation"] == "bedrock CLI explanation"
        assert output["explanation_error"] is None
        assert "bedrock_result" in event_types


def test_cli_denied_run_records_configured_but_uninvoked_local_explainer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    instances: list[DeterministicLocalExplainer] = []

    class CountingLocalExplainer(DeterministicLocalExplainer):
        def __init__(self) -> None:
            super().__init__()
            instances.append(self)

    monkeypatch.setattr("simshift.cli.SimshiftDeciderAdapter", _Adapter)
    monkeypatch.setattr("simshift.cli.DeterministicLocalExplainer", CountingLocalExplainer)
    trace = tmp_path / "denied-local.jsonl"
    args = _run_args(trace)
    args[args.index("granted")] = "denied"
    assert main(args) == 0
    capsys.readouterr()
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [event["event_type"] for event in events][-2:] == [
        "proposal_blocked",
        "run_escalated",
    ]
    assert events[0]["payload"]["provenance"]["explainer_model"]["configured"] is True
    assert events[0]["payload"]["provenance"]["explainer_model"]["invoked"] is False
    assert events[-1]["payload"]["explainer_invoked"] is False
    assert instances[0].invocation_count == 0


def test_cli_denied_run_does_not_invoke_injected_bedrock_explainer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    instances: list[_Bedrock] = []

    class CountingBedrock(_Bedrock):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            instances.append(self)

    monkeypatch.setattr("simshift.cli.SimshiftDeciderAdapter", _Adapter)
    monkeypatch.setattr("simshift.cli.StrandsBedrockExplainer", CountingBedrock)
    monkeypatch.setenv("BEDROCK_REGION", "test-region-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    trace = tmp_path / "denied-bedrock.jsonl"
    args = _run_args(trace, "bedrock")
    args[args.index("granted")] = "denied"
    assert main(args) == 0
    capsys.readouterr()
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [event["event_type"] for event in events][-2:] == [
        "proposal_blocked",
        "run_escalated",
    ]
    assert events[0]["payload"]["provenance"]["explainer_model"]["configured"] is True
    assert events[0]["payload"]["provenance"]["explainer_model"]["invoked"] is False
    assert events[-1]["payload"]["explainer_invoked"] is False
    assert instances[0].invocation_count == 0


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (DeciderConfigurationError("invalid origin"), "INVALID", 2),
        (DeciderProtocolError("malformed response"), "DEPENDENCY_ERROR", 3),
        (DeciderUnavailable("retries exhausted"), "DEPENDENCY_ERROR", 3),
    ],
)
def test_cli_maps_decider_failures_to_documented_exit_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    error: Exception,
    expected_status: str,
    expected_code: int,
) -> None:
    class FailingAdapter:
        def __init__(self, **kwargs) -> None:
            del kwargs
            raise error

    monkeypatch.setattr("simshift.cli.SimshiftDeciderAdapter", FailingAdapter)
    assert main(_run_args(tmp_path / "trace.jsonl")) == expected_code
    assert json.loads(capsys.readouterr().out)["status"] == expected_status


def test_cli_preflights_unwritable_destination_before_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    called = False

    class UnexpectedAdapter:
        def __init__(self, **kwargs) -> None:
            nonlocal called
            del kwargs
            called = True

    parent = tmp_path / "not-a-directory"
    parent.write_text("file")
    monkeypatch.setattr("simshift.cli.SimshiftDeciderAdapter", UnexpectedAdapter)
    assert main(_run_args(parent / "trace.jsonl")) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID"
    assert called is False
