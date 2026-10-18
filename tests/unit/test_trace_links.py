# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json

import pytest

from simshift.tracing.events import ComponentStatus, TraceEvent, validate_event_sequence
from tests.unit.test_trace_events import run_started


def _exact(value: dict[str, object]) -> tuple[str, str]:
    text = json.dumps(value, separators=(",", ":"))
    return text, hashlib.sha256(text.encode()).hexdigest()


def _request(sequence: int = 1) -> TraceEvent:
    request = {
        "state": {},
        "questions": {
            "next_recovery_step": {
                "type": "choice",
                "instructions": "test",
                "criteria": {"x": "test option"},
            }
        },
    }
    body, digest = _exact(request)
    return TraceEvent.create(
        run_id="a" * 24,
        sequence=sequence,
        event_type="decider_request",
        component="decider",
        component_status=ComponentStatus.REAL,
        payload={
            "decision_id": "d1",
            "request_hash": digest,
            "request_body_utf8": body,
            "request": request,
            "attempt": 1,
        },
    )


def _response(sequence: int = 2) -> TraceEvent:
    response = {
        "model": "test-decider",
        "answers": {
            "next_recovery_step": {
                "type": "choice",
                "choice": "x",
                "probabilities": {"x": 1.0},
                "confidence": 1.0,
            }
        },
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    body, digest = _exact(response)
    return TraceEvent.create(
        run_id="a" * 24,
        sequence=sequence,
        event_type="decider_response",
        component="decider",
        component_status=ComponentStatus.REAL,
        payload={
            "decision_id": "d1",
            "response_hash": digest,
            "response_body_utf8": body,
            "body": response,
            "model_choice": "x",
            "probabilities": {"x": 1.0},
            "confidence": 1.0,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


def test_response_without_request_is_rejected() -> None:
    with pytest.raises(ValueError, match="no request"):
        validate_event_sequence((run_started(), _response(sequence=1)))


def test_request_response_link_is_valid() -> None:
    validate_event_sequence((run_started(), _request(), _response()))


def test_exact_wire_hash_is_recomputed_during_sequence_validation() -> None:
    request = _request().model_copy(
        update={
            "payload": _request().payload
            | {"request_body_utf8": _request().payload["request_body_utf8"] + " "}
        }
    )
    with pytest.raises(ValueError, match="request_hash does not match"):
        validate_event_sequence((run_started(), request))


def test_exact_wire_json_rejects_duplicate_keys() -> None:
    request = _request()
    duplicate_body = '{"state":{},"state":[],"questions":{}}'
    duplicate_payload = request.payload | {
        "request_body_utf8": duplicate_body,
        "request_hash": hashlib.sha256(duplicate_body.encode()).hexdigest(),
    }
    with pytest.raises(ValueError, match="duplicate-free"):
        validate_event_sequence(
            (run_started(), request.model_copy(update={"payload": duplicate_payload}))
        )


def test_response_semantics_must_match_recorded_decision() -> None:
    response = _response()
    mismatched = response.model_copy(
        update={"payload": response.payload | {"model_choice": "other"}}
    )
    with pytest.raises(ValueError, match="choice fields"):
        validate_event_sequence((run_started(), _request(), mismatched))
