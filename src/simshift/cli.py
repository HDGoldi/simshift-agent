# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Local CLI for fixture validation, forced policy checks, and bounded runs."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from patterns.capability_aware_router.decider_client import (
    DeciderConfigurationError,
    DeciderProtocolError,
    DeciderTransportError,
)
from simshift.config import RunConfig, collect_environment_evidence
from simshift.decision.coordinator import DecisionCoordinator
from simshift.domain.enums import Action, GateReason, ScenarioId
from simshift.domain.models import BlockedProposalAudit
from simshift.integrations.bedrock import (
    DeterministicLocalExplainer,
    StrandsBedrockExplainer,
)
from simshift.integrations.decider_http import (
    DeciderUnavailable,
    DependencyIdentityError,
    ManifestError,
    SimshiftDeciderAdapter,
)
from simshift.integrations.strands_tools import build_tool_host
from simshift.orchestration.dispatch import DirectDispatcher
from simshift.orchestration.runner import SimshiftRunner
from simshift.orchestration.services import ToolServices
from simshift.policy.profile_transition import (
    TransitionCoordinator,
    materialize_approval,
    prepare_profile_transition,
)
from simshift.scenarios.repository import FixtureError, ScenarioRepository
from simshift.tracing.recorder import TraceDestinationError, TraceRecorder


def _uint32(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 2**32 - 1:
        raise argparse.ArgumentTypeError("seed must be an unsigned 32-bit integer")
    return parsed


def _confidence(value: str) -> float:
    parsed = float(value)
    if not parsed == parsed or parsed in (float("inf"), float("-inf")) or not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("confidence floor must be finite and in [0, 1]")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simshift")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "validate-fixtures", help="validate both normative local scenario fixtures"
    )

    policy = subcommands.add_parser(
        "policy-check", help="force one profile proposal through deterministic gates"
    )
    policy.add_argument("--scenario", choices=[item.value for item in ScenarioId], required=True)
    policy.add_argument("--seed", type=_uint32, required=True)
    policy.add_argument(
        "--action",
        choices=[Action.EVALUATE_PROFILE_CHANGE.value],
        required=True,
    )
    policy.add_argument("--approval", choices=("granted", "denied"), default="denied")

    run = subcommands.add_parser("run", help="run the bounded local-first recovery coordinator")
    run.add_argument("--scenario", choices=[item.value for item in ScenarioId], required=True)
    run.add_argument("--seed", type=_uint32)
    run.add_argument("--decider-url", required=True)
    run.add_argument("--decider-manifest", type=Path, required=True)
    run.add_argument(
        "--explainer", choices=("local-test-double", "bedrock"), required=True
    )
    run.add_argument("--trace-out", type=Path, required=True)
    run.add_argument("--approval", choices=("granted", "denied"), default="denied")
    run.add_argument("--max-steps", type=int, choices=range(1, 5), default=4)
    run.add_argument("--confidence-floor", type=_confidence, default=0.20)
    return parser


def _validate_fixtures() -> int:
    try:
        loaded = ScenarioRepository().load_all()
    except FixtureError as error:
        print(json.dumps({"status": "INVALID", "error": str(error)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "VALID",
                "scenarios": sorted(scenario.value for scenario in loaded),
            },
            sort_keys=True,
        )
    )
    return 0


def _policy_check(args: argparse.Namespace) -> int:
    runtime = ScenarioRepository().load_runtime(args.scenario)
    initial_observable = runtime.observable
    initial_policy = runtime.policy
    config = RunConfig(
        scenario_id=ScenarioId(args.scenario),
        fixture_revision=runtime.fixture_revision,
        seed=args.seed,
        approval=args.approval,
    )
    proposal = prepare_profile_transition(
        runtime.observable,
        runtime.policy,
        run_id=config.run_id,
        tool_call_id="policy-check",
    ).model_copy(update={"prepared_observation_revision": runtime.observable.observation_revision})
    approval = materialize_approval(proposal, granted=args.approval == "granted")
    committed = TransitionCoordinator(runtime).commit(proposal, approval)
    if not isinstance(committed.outcome, BlockedProposalAudit):
        result = {
            "status": "APPROVED",
            "reason": GateReason.PASS.value,
            "transition_id": committed.outcome.transition_id,
            "initial_profile": initial_observable.active_profile_id,
            "final_profile": runtime.observable.active_profile_id,
            "profile_unchanged": runtime.observable.active_profile_id
            == initial_observable.active_profile_id,
        }
    else:
        reasons = [
            gate.reason.value
            for gate in committed.outcome.final_gate_results
            if gate.reason is not GateReason.PASS
        ]
        result = {
            "status": "BLOCKED",
            "reason": reasons[0],
            "reasons": reasons,
            "transition_id": None,
            "initial_profile": initial_observable.active_profile_id,
            "final_profile": runtime.observable.active_profile_id,
            "profile_unchanged": runtime.observable.active_profile_id
            == initial_observable.active_profile_id,
            "state_unchanged": runtime.observable == initial_observable
            and runtime.policy == initial_policy,
            "approval_consumed": committed.outcome.approval_consumed,
            "command_created": committed.outcome.command_created,
        }
    print(json.dumps(result, sort_keys=True))
    return 0


def _run(args: argparse.Namespace) -> int:
    runtime = ScenarioRepository().load_runtime(args.scenario)
    seed = runtime.default_seed if args.seed is None else args.seed
    config = RunConfig(
        scenario_id=ScenarioId(args.scenario),
        fixture_revision=runtime.fixture_revision,
        seed=seed,
        approval=args.approval,
        max_steps=args.max_steps,
        confidence_floor=args.confidence_floor,
    )
    recorder = TraceRecorder(args.trace_out)
    recorder.preflight()
    explainer: DeterministicLocalExplainer | StrandsBedrockExplainer
    if args.explainer == "local-test-double":
        explainer = DeterministicLocalExplainer()
    else:
        region = os.environ.get("BEDROCK_REGION")
        model_reference = os.environ.get("BEDROCK_INFERENCE_PROFILE") or os.environ.get(
            "BEDROCK_MODEL_ID"
        )
        if not region or not model_reference:
            raise ManifestError(
                "bedrock explainer requires BEDROCK_REGION and "
                "BEDROCK_INFERENCE_PROFILE or BEDROCK_MODEL_ID"
            )
        explainer = StrandsBedrockExplainer(
            region_name=region,
            model_reference=model_reference,
        )
    adapter = SimshiftDeciderAdapter(
        origin=args.decider_url,
        manifest_path=args.decider_manifest,
    )
    services = ToolServices(runtime, run_id=config.run_id, seed=seed)
    agent, host_model = build_tool_host(services)
    dispatcher = DirectDispatcher(agent)
    coordinator = DecisionCoordinator(
        provider=adapter,
        dispatcher=dispatcher,
        confidence_floor=config.confidence_floor,
    )
    environment_evidence = collect_environment_evidence(
        project_root=Path(__file__).resolve().parents[2],
        trusted_manifest_sha256=adapter.manifest_sha256,
        explainer_mode=args.explainer,
        bedrock_region=explainer.region_name if args.explainer == "bedrock" else None,
        bedrock_model_reference=(
            explainer.model_reference if args.explainer == "bedrock" else None
        ),
    )
    result = SimshiftRunner(
        runtime=runtime,
        config=config,
        coordinator=coordinator,
        environment_evidence=environment_evidence,
        explainer=explainer,
    ).run()
    if host_model.invocation_count != 0:
        raise RuntimeError("inert Strands tool-host model was unexpectedly invoked")

    for event in result.events:
        recorder.append(event)
    recorder.write()

    evidence = {
        "final_status": result.status,
        "reason": result.reason,
        "steps": result.steps,
        "decision_count": result.decision_count,
        "dispatch_count": result.dispatch_count,
    }
    print(
        json.dumps(
            {
                **evidence,
                "final_profile": result.final_profile,
                "trace": str(args.trace_out),
                "explanation": result.explanation,
                "explanation_error": result.explanation_error,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-fixtures":
            return _validate_fixtures()
        if args.command == "policy-check":
            return _policy_check(args)
        if args.command == "run":
            return _run(args)
    except (
        DeciderConfigurationError,
        FixtureError,
        ManifestError,
        TraceDestinationError,
        ValueError,
    ) as error:
        print(json.dumps({"status": "INVALID", "error": str(error)}, sort_keys=True))
        return 2
    except (
        DeciderProtocolError,
        DeciderTransportError,
        DependencyIdentityError,
        DeciderUnavailable,
    ) as error:
        print(json.dumps({"status": "DEPENDENCY_ERROR", "error": str(error)}, sort_keys=True))
        return 3
    except RuntimeError as error:
        print(json.dumps({"status": "INTERNAL_ERROR", "error": str(error)}, sort_keys=True))
        return 4
    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
