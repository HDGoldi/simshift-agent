# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Canonical strict one-attempt client for the loopback Strands Decider API."""

from __future__ import annotations

import http.client
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from .schemas import ChoiceDecision, FrozenModel, JSONValue, TypedChoiceQuestion, Usage

MAX_RESPONSE_BYTES = 65_536
MAX_STATE_BYTES = 24 * 1024
MAX_REQUEST_BYTES = 32 * 1024
CONNECT_TIMEOUT_SECONDS = 2.0
READ_TIMEOUT_SECONDS = 30.0


class DeciderError(RuntimeError):
    """Base class for canonical Decider client failures."""


class DeciderConfigurationError(DeciderError):
    """The endpoint or local request configuration is invalid."""


class DeciderTransportError(DeciderError):
    """The one-attempt HTTP exchange did not complete."""


class DeciderProtocolError(DeciderError):
    """The HTTP or JSON response violates the canonical contract."""


class DeciderHttpStatusError(DeciderProtocolError):
    """Decider returned a non-success status."""

    def __init__(self, status: int) -> None:
        super().__init__(f"Decider returned HTTP {status}")
        self.status = status
        self.retryable = status in {408, 429} or 500 <= status <= 599


class HealthResponse(FrozenModel):
    """Validated upstream health data and bounded unknown extensions."""

    status: Literal["ok"]
    model: str = Field(min_length=1, max_length=300)
    checkpoint: str = Field(min_length=1, max_length=1000)
    base_model: str = Field(min_length=1, max_length=300)
    device: str = Field(min_length=1, max_length=100)
    max_length: int = Field(ge=1)
    num_slots: int = Field(ge=1, le=255)
    vision: bool
    prefix_cache: bool
    extensions: dict[str, JSONValue] = Field(default_factory=dict)

    @field_validator("extensions")
    @classmethod
    def copy_extensions(cls, value: dict[str, JSONValue]) -> dict[str, JSONValue]:
        return dict(value)


ConnectionFactory = Callable[[str, int, float], Any]


@dataclass(frozen=True)
class DeciderExchange:
    """Exact request and validated response bytes from one HTTP exchange."""

    method: Literal["GET", "POST"]
    path: str
    request_body: bytes | None
    response_body: bytes
    client_latency_ms: float


def _default_connection_factory(
    host: str, port: int, timeout: float
) -> http.client.HTTPConnection:
    return http.client.HTTPConnection(host, port, timeout=timeout)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is forbidden")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def decode_json_object(body: bytes) -> dict[str, Any]:
    """Decode strict UTF-8, finite JSON with duplicate detection at every depth."""

    try:
        text = body.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise DeciderProtocolError("response is not strict duplicate-free finite JSON") from error
    if not isinstance(value, dict):
        raise DeciderProtocolError("response JSON must be an object")
    return value


def _bounded_extension(value: Any, *, depth: int = 1) -> JSONValue:
    if depth > 4:
        raise DeciderProtocolError("response extension exceeds maximum depth 4")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        if len(value) > 1000:
            raise DeciderProtocolError("response extension string exceeds 1000 characters")
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DeciderProtocolError("response extensions must be finite")
        return value
    if isinstance(value, list):
        if len(value) > 16:
            raise DeciderProtocolError("response extension array exceeds 16 items")
        return [_bounded_extension(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 16:
            raise DeciderProtocolError("response extension object exceeds 16 keys")
        bounded: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 1000:
                raise DeciderProtocolError("response extension keys must be bounded strings")
            bounded[key] = _bounded_extension(item, depth=depth + 1)
        return bounded
    raise DeciderProtocolError("response extension contains a non-JSON value")


def _extensions(payload: dict[str, Any], known: set[str]) -> dict[str, JSONValue]:
    unknown = {key: value for key, value in payload.items() if key not in known}
    if len(unknown) > 16:
        raise DeciderProtocolError("response has more than 16 extension fields")
    return {key: _bounded_extension(value) for key, value in unknown.items()}


def _number(value: Any, field_name: str, *, minimum: float, maximum: float | None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DeciderProtocolError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise DeciderProtocolError(f"{field_name} is outside its allowed range")
    if maximum is not None and number > maximum:
        raise DeciderProtocolError(f"{field_name} is outside its allowed range")
    return number


def _non_negative_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DeciderProtocolError(f"{field_name} must be a non-negative integer")
    return value


class DeciderClient:
    """Strict client for one health check and one-attempt choice requests."""

    def __init__(
        self,
        origin: str,
        *,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = READ_TIMEOUT_SECONDS,
        connection_factory: ConnectionFactory = _default_connection_factory,
    ) -> None:
        self._host, self._port, self.origin = self._validate_origin(origin)
        if connect_timeout <= 0 or not math.isfinite(connect_timeout):
            raise DeciderConfigurationError("connect timeout must be finite and positive")
        if read_timeout <= 0 or not math.isfinite(read_timeout):
            raise DeciderConfigurationError("read timeout must be finite and positive")
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._connection_factory = connection_factory
        self.last_exchange: DeciderExchange | None = None

    @staticmethod
    def _validate_origin(origin: str) -> tuple[str, int, str]:
        if not isinstance(origin, str) or not origin:
            raise DeciderConfigurationError("Decider origin must be a non-empty string")
        if origin != origin.strip() or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in origin
        ):
            raise DeciderConfigurationError("Decider origin contains whitespace or controls")
        if not origin.startswith("http://") or "?" in origin or "#" in origin:
            raise DeciderConfigurationError("Decider origin must use exact plain HTTP syntax")
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError as error:
            raise DeciderConfigurationError("Decider origin has an invalid port") from error
        if (
            parsed.scheme != "http"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or port is None
            or not 1 <= port <= 65_535
        ):
            raise DeciderConfigurationError("Decider origin is not an allowed loopback origin")
        host = parsed.hostname
        if host not in {"127.0.0.1", "::1"}:
            raise DeciderConfigurationError("Decider host must be literal 127.0.0.1 or ::1")
        expected_netloc = f"127.0.0.1:{port}" if host == "127.0.0.1" else f"[::1]:{port}"
        if parsed.netloc != expected_netloc:
            raise DeciderConfigurationError("Decider origin must use canonical literal syntax")
        normalized = f"http://{expected_netloc}"
        return host, port, normalized

    def health(self) -> HealthResponse:
        """Call and strictly validate exact ``GET /health``."""

        payload, _ = self._request_json("GET", "/health", None)
        known = {
            "status",
            "model",
            "checkpoint",
            "base_model",
            "device",
            "max_length",
            "num_slots",
            "vision",
            "prefix_cache",
        }
        required = known
        missing = required - payload.keys()
        if missing:
            raise DeciderProtocolError(f"health response is missing {sorted(missing)!r}")
        for field_name in ("status", "model", "checkpoint", "base_model", "device"):
            value = payload[field_name]
            if not isinstance(value, str) or not value:
                raise DeciderProtocolError(f"health {field_name} must be a non-empty string")
        max_length = _non_negative_integer(payload["max_length"], "health max_length")
        slots = _non_negative_integer(payload["num_slots"], "health num_slots")
        if max_length == 0 or not 1 <= slots <= 255:
            raise DeciderProtocolError("health capacity fields are outside allowed ranges")
        if not isinstance(payload["vision"], bool) or not isinstance(payload["prefix_cache"], bool):
            raise DeciderProtocolError("health boolean fields must be booleans")
        try:
            return HealthResponse(
                status=payload["status"],
                model=payload["model"],
                checkpoint=payload["checkpoint"],
                base_model=payload["base_model"],
                device=payload["device"],
                max_length=max_length,
                num_slots=slots,
                vision=payload["vision"],
                prefix_cache=payload["prefix_cache"],
                extensions=_extensions(payload, known),
            )
        except ValueError as error:
            raise DeciderProtocolError("health response failed schema validation") from error

    def choose(
        self,
        *,
        state: JSONValue,
        question: TypedChoiceQuestion,
        expected_model: str,
    ) -> ChoiceDecision:
        """Submit one choice and validate all routing-relevant response semantics."""

        if not isinstance(expected_model, str) or not expected_model:
            raise DeciderConfigurationError("expected model must be a non-empty trusted value")
        if not isinstance(state, (str, list, dict)):
            raise DeciderConfigurationError("state must be a JSON string, object, or array")
        try:
            state_bytes = json.dumps(
                state,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise DeciderConfigurationError("state must contain only finite JSON values") from error
        if len(state_bytes) > MAX_STATE_BYTES:
            raise DeciderConfigurationError("serialized state exceeds 24 KiB")
        request_object = {
            "state": state,
            "questions": {
                question.name: {
                    "type": "choice",
                    "instructions": question.instructions,
                    "criteria": {
                        option.label: option.description for option in question.options
                    },
                }
            },
        }
        try:
            body = json.dumps(
                request_object,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise DeciderConfigurationError(
                "request must contain only finite JSON values"
            ) from error
        if len(body) > MAX_REQUEST_BYTES:
            raise DeciderConfigurationError("serialized request exceeds 32 KiB")
        payload, client_latency_ms = self._request_json("POST", "/v1/systemone", body)
        return self._parse_decision(
            payload,
            question=question,
            expected_model=expected_model,
            client_latency_ms=client_latency_ms,
        )

    def _request_json(
        self, method: Literal["GET", "POST"], path: str, body: bytes | None
    ) -> tuple[dict[str, Any], float]:
        headers = {"Accept": "application/json", "Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            headers["Content-Length"] = str(len(body))
        connection = self._connection_factory(self._host, self._port, self._connect_timeout)
        self.last_exchange = None
        started = time.monotonic()
        try:
            connection.connect()
            if connection.sock is None:
                raise DeciderTransportError("connection completed without a socket")
            connection.sock.settimeout(self._read_timeout)
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                raise DeciderHttpStatusError(response.status)
            content_length = response.getheader("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length, 10)
                except ValueError as error:
                    raise DeciderProtocolError("Content-Length is not an integer") from error
                if declared_length < 0 or declared_length > MAX_RESPONSE_BYTES:
                    raise DeciderProtocolError("response exceeds the 64 KiB body limit")
            chunks: list[bytes] = []
            total = 0
            while total <= MAX_RESPONSE_BYTES:
                chunk = response.read(min(8192, MAX_RESPONSE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise DeciderProtocolError("response exceeds the 64 KiB body limit")
            response_body = b"".join(chunks)
            payload = decode_json_object(response_body)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self.last_exchange = DeciderExchange(
                method=method,
                path=path,
                request_body=body,
                response_body=response_body,
                client_latency_ms=elapsed_ms,
            )
            return payload, elapsed_ms
        except DeciderError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException, EOFError) as error:
            raise DeciderTransportError("Decider HTTP exchange failed") from error
        finally:
            connection.close()

    @staticmethod
    def _parse_decision(
        payload: dict[str, Any],
        *,
        question: TypedChoiceQuestion,
        expected_model: str,
        client_latency_ms: float,
    ) -> ChoiceDecision:
        known_top = {"model", "answers", "usage", "latency_ms"}
        missing = {"model", "answers", "usage"} - payload.keys()
        if missing:
            raise DeciderProtocolError(f"decision response is missing {sorted(missing)!r}")
        model = payload["model"]
        if not isinstance(model, str) or not model or model != expected_model:
            raise DeciderProtocolError("decision model does not match trusted health")
        answers = payload["answers"]
        if not isinstance(answers, dict) or set(answers) != {question.name}:
            raise DeciderProtocolError("decision answers must contain exactly the requested key")
        answer = answers[question.name]
        if not isinstance(answer, dict) or set(answer) != {
            "type",
            "choice",
            "probabilities",
            "confidence",
        }:
            raise DeciderProtocolError("choice answer has unexpected or missing fields")
        if answer["type"] != "choice":
            raise DeciderProtocolError("answer type must be choice")
        labels = tuple(option.label for option in question.options)
        choice = answer["choice"]
        if not isinstance(choice, str) or choice not in labels:
            raise DeciderProtocolError("model choice is not one of the submitted options")
        raw_probabilities = answer["probabilities"]
        if not isinstance(raw_probabilities, dict) or set(raw_probabilities) != set(labels):
            raise DeciderProtocolError("probability keys must exactly match submitted options")
        probabilities = {
            label: _number(
                raw_probabilities[label],
                f"probability {label}",
                minimum=0.0,
                maximum=1.0,
            )
            for label in labels
        }
        if abs(sum(probabilities.values()) - 1.0) > 0.002:
            raise DeciderProtocolError("probabilities do not sum to one within tolerance")
        maximum = max(probabilities.values())
        if round(probabilities[choice], 4) != round(maximum, 4):
            raise DeciderProtocolError("chosen option is not maximal at four-decimal precision")
        confidence = _number(
            answer["confidence"], "confidence", minimum=0.0, maximum=1.0
        )
        expected_confidence = (len(labels) * maximum - 1.0) / (len(labels) - 1.0)
        if abs(confidence - expected_confidence) > 0.002:
            raise DeciderProtocolError("confidence does not match the canonical formula")
        usage = payload["usage"]
        if not isinstance(usage, dict) or set(usage) != {"input_tokens", "output_tokens"}:
            raise DeciderProtocolError("usage has unexpected or missing fields")
        parsed_usage = Usage(
            input_tokens=_non_negative_integer(usage["input_tokens"], "input_tokens"),
            output_tokens=_non_negative_integer(usage["output_tokens"], "output_tokens"),
        )
        latency = None
        if "latency_ms" in payload:
            latency = _number(payload["latency_ms"], "latency_ms", minimum=0.0, maximum=None)
        try:
            return ChoiceDecision(
                model=model,
                model_choice=choice,
                probabilities=MappingProxyType(probabilities),
                confidence=confidence,
                usage=parsed_usage,
                latency_ms=latency,
                client_latency_ms=client_latency_ms,
                extensions=MappingProxyType(_extensions(payload, known_top)),
            )
        except ValueError as error:
            raise DeciderProtocolError("decision response failed schema validation") from error


__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "DeciderClient",
    "DeciderConfigurationError",
    "DeciderError",
    "DeciderExchange",
    "DeciderHttpStatusError",
    "DeciderProtocolError",
    "DeciderTransportError",
    "HealthResponse",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "MAX_STATE_BYTES",
    "READ_TIMEOUT_SECONDS",
    "decode_json_object",
]
