# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Route a document-processing task through a real loopback Decider service."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence

from ..decider_client import DeciderClient
from ..filters import filter_options
from ..router import CapabilityAwareRouter, ToolRegistry
from ..schemas import DecisionPolicy, QuestionOption

OPTIONS = (
    QuestionOption(label="extract_text", description="Extract text with the local parser."),
    QuestionOption(label="inspect_metadata", description="Inspect document metadata."),
    QuestionOption(label="request_human_review", description="Send the document for human review."),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capability-aware document processing through a loopback Decider."
    )
    parser.add_argument(
        "--decider-url",
        default=os.environ.get("STRANDS_DECIDER_URL"),
        help="literal loopback origin; defaults to STRANDS_DECIDER_URL",
    )
    parser.add_argument(
        "--parser-available",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="include or remove the local text-extraction capability",
    )
    parser.add_argument(
        "--confidence-floor",
        type=float,
        default=0.20,
        help="minimum confidence before falling back to human review (default: 0.20)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.decider_url:
        build_parser().error("--decider-url or STRANDS_DECIDER_URL is required")

    client = DeciderClient(args.decider_url)
    health = client.health()
    filtered = filter_options(
        OPTIONS,
        lambda option: (
            "LOCAL_TEXT_PARSER_UNAVAILABLE"
            if option.label == "extract_text" and not args.parser_available
            else None
        ),
    )
    calls: list[str] = []

    def callback(label: str) -> str:
        calls.append(label)
        return label

    def bind_callback(label: str) -> Callable[[], str]:
        def invoke() -> str:
            return callback(label)

        return invoke

    registry = ToolRegistry(
        {option.label: bind_callback(option.label) for option in OPTIONS}
    )
    router = CapabilityAwareRouter(
        client=client,
        trusted_num_slots=health.num_slots,
        expected_model=health.model,
        registry=registry,
        policy=DecisionPolicy(
            min_confidence=args.confidence_floor,
            fallback_label="request_human_review",
        ),
    )
    result = router.route_filtered(
        filtered=filtered,
        state={
            "document_kind": "invoice",
            "parser_available": args.parser_available,
            "review_required": False,
        },
        question_name="next_document_step",
        instructions="Choose one available document-processing action.",
    )
    print(
        json.dumps(
            {
                "model_choice": (
                    result.trace.decision.model_choice if result.trace.decision else None
                ),
                "effective_choice": (
                    result.trace.effective.effective_choice if result.trace.effective else None
                ),
                "callback_calls": calls,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
