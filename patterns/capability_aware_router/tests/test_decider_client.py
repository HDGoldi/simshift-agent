# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import json
from typing import Any

import pytest

from patterns.capability_aware_router.decider_client import (
    DeciderClient,
    DeciderConfigurationError,
    DeciderProtocolError,
)
from patterns.capability_aware_router.schemas import QuestionOption, TypedChoiceQuestion


class FakeSocket:
    def __init__(self) -> None:
        self.timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout


class FakeResponse:
    def __init__(
        self, body: bytes, *, status: int = 200, content_length: str | None = None
    ) -> None:
        self.status = status
        self._body = body
        self._offset = 0
        self._content_length = content_length

    def getheader(self, name: str) -> str | None:
        return self._content_length if name == "Content-Length" else None

    def read(self, amount: int) -> bytes:
        chunk = self._body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.sock = FakeSocket()
        self.response = response
        self.request_data: tuple[str, str, bytes | None, dict[str, str]] | None = None
        self.closed = False

    def connect(self) -> None:
        return None

    def request(
        self, method: str, path: str, body: bytes | None, headers: dict[str, str]
    ) -> None:
        self.request_data = (method, path, body, headers)

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def _question() -> TypedChoiceQuestion:
    return TypedChoiceQuestion(
        name="next_step",
        instructions="Choose one option.",
        options=(
            QuestionOption(label="inspect", description="Inspect"),
            QuestionOption(label="review", description="Review"),
        ),
    )


def _decision_payload(**answer_updates: Any) -> bytes:
    answer = {
        "type": "choice",
        "choice": "inspect",
        "probabilities": {"inspect": 0.6, "review": 0.4},
        "confidence": 0.2,
    }
    answer.update(answer_updates)
    return json.dumps(
        {
            "model": "model-v1",
            "answers": {"next_step": answer},
            "usage": {"input_tokens": 2, "output_tokens": 1},
            "latency_ms": 3.0,
        }
    ).encode()


def _client(response: FakeResponse) -> tuple[DeciderClient, FakeConnection]:
    connection = FakeConnection(response)
    client = DeciderClient(
        "http://127.0.0.1:8000",
        connection_factory=lambda _host, _port, _timeout: connection,
    )
    return client, connection


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.2:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000/custom",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000?x=1",
    ],
)
def test_rejects_noncanonical_origins(origin: str) -> None:
    with pytest.raises(DeciderConfigurationError):
        DeciderClient(origin)


def test_choice_request_and_response_are_validated() -> None:
    client, connection = _client(FakeResponse(_decision_payload()))
    decision = client.choose(
        state={"kind": "invoice"},
        question=_question(),
        expected_model="model-v1",
    )
    assert decision.model_choice == "inspect"
    assert decision.confidence == 0.2
    assert connection.request_data is not None
    method, path, body, headers = connection.request_data
    assert (method, path) == ("POST", "/v1/systemone")
    assert headers["Content-Length"] == str(len(body or b""))
    assert connection.sock.timeout == 30.0
    assert connection.closed


def test_health_requires_exact_core_fields_and_preserves_extensions() -> None:
    body = json.dumps(
        {
            "status": "ok",
            "model": "model-v1",
            "checkpoint": "/models/model-v1",
            "base_model": "base/model",
            "device": "cpu",
            "max_length": 4096,
            "num_slots": 24,
            "vision": False,
            "prefix_cache": True,
            "temperature": 1.0,
        }
    ).encode()
    client, connection = _client(FakeResponse(body))
    health = client.health()
    assert health.num_slots == 24
    assert health.extensions == {"temperature": 1.0}
    assert connection.request_data is not None
    assert connection.request_data[:2] == ("GET", "/health")


@pytest.mark.parametrize(
    "body",
    [
        b'{"model":"a","model":"b"}',
        b'{"outer":{"key":1,"key":2}}',
        b'{"value":NaN}',
        b"[]",
        b"not-json",
        b"\xff",
    ],
)
def test_malformed_json_never_produces_a_decision(body: bytes) -> None:
    client, connection = _client(FakeResponse(body))
    with pytest.raises(DeciderProtocolError):
        client.choose(state={}, question=_question(), expected_model="model-v1")
    assert connection.closed


def test_rejects_oversized_http_body_before_or_during_read() -> None:
    client, _ = _client(FakeResponse(b"{}", content_length="65537"))
    with pytest.raises(DeciderProtocolError, match="64 KiB"):
        client.health()
    client, _ = _client(FakeResponse(b"x" * 65_537))
    with pytest.raises(DeciderProtocolError, match="64 KiB"):
        client.health()


@pytest.mark.parametrize(
    "updates",
    [
        {"confidence": 0.3},
        {"confidence": float("inf")},
        {"probabilities": {"inspect": 0.4, "review": 0.6}},
        {"probabilities": {"inspect": 0.7, "review": 0.7}},
        {"choice": "forbidden"},
    ],
)
def test_invalid_choice_probability_or_confidence_never_dispatches(updates: dict[str, Any]) -> None:
    client, _ = _client(FakeResponse(_decision_payload(**updates)))
    with pytest.raises(DeciderProtocolError):
        client.choose(state={}, question=_question(), expected_model="model-v1")
