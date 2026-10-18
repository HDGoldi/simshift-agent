# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Buffered validation and atomic JSONL persistence."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from simshift.decision.projection import assert_no_evaluator_leak

from .events import TraceEvent, validate_event_sequence


class TraceDestinationError(ValueError):
    """The configured trace destination cannot be written before a run."""


class TraceWriteError(RuntimeError):
    """The validated trace could not be committed atomically."""


class TraceRecorder:
    """Collect strict events and atomically replace one local trace file."""

    def __init__(self, destination: Path, *, evaluator_canaries: tuple[str, ...] = ()) -> None:
        self.destination = destination
        self.evaluator_canaries = evaluator_canaries
        self._events: list[TraceEvent] = []

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def preflight(self) -> None:
        """Prove the destination directory is writable before dependencies run."""

        temporary_name: str | None = None
        try:
            self.destination.parent.mkdir(parents=True, exist_ok=True)
            if self.destination.exists() and not self.destination.is_file():
                raise OSError("trace destination is not a regular file")
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.destination.parent,
                prefix=f".{self.destination.name}.preflight.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write("")
                temporary.flush()
                os.fsync(temporary.fileno())
        except OSError as error:
            raise TraceDestinationError(f"trace destination is not writable: {error}") from error
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    def append(self, event: TraceEvent) -> None:
        if self._events and event.run_id != self._events[0].run_id:
            raise ValueError("all events must share one run ID")
        if event.sequence != len(self._events):
            raise ValueError("event sequence must be contiguous")
        encoded = event.model_dump(mode="json", exclude_none=True)
        assert_no_evaluator_leak(encoded, canaries=self.evaluator_canaries)
        self._events.append(event)

    def write(self) -> None:
        events = tuple(self._events)
        validate_event_sequence(events)
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.destination.parent,
                prefix=f".{self.destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                for event in events:
                    json.dump(
                        event.model_dump(mode="json", exclude_none=True),
                        temporary,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self.destination)
            temporary_name = None
            directory_fd = os.open(self.destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            raise TraceWriteError(f"trace commit failed: {error}") from error
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)


__all__ = ["TraceDestinationError", "TraceRecorder", "TraceWriteError"]
