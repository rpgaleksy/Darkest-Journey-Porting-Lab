"""Explicit provider contracts for external RPG Maker runtime services.

The trace interpreter deliberately does not own a window system, keyboard
queue, or movement engine.  These small contracts let a caller supply those
services without making the interpreter guess their result.  A provider
returns a deterministic :class:`ProviderDecision`; the trace applies only
the state changes explicitly present in that decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Protocol, Sequence


PROVIDER_STATUSES = frozenset(
    {"completed", "awaiting_input", "unsupported", "invalid_data"}
)


@dataclass(frozen=True)
class ProviderDecision:
    """One deterministic result returned by an external service."""

    status: str = "completed"
    reason: str = "provider completed the command"
    wait_frames: int = 0
    value: Optional[int] = None
    character_updates: Mapping[int, Mapping[str, object]] = field(default_factory=dict)
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in PROVIDER_STATUSES:
            raise ValueError(f"invalid provider status {self.status!r}")
        if (
            isinstance(self.wait_frames, bool)
            or not isinstance(self.wait_frames, int)
            or self.wait_frames < 0
        ):
            raise ValueError("provider wait_frames must be a non-negative integer")
        if self.status != "completed" and self.wait_frames:
            raise ValueError("only completed provider decisions may wait")
        if self.value is not None and (
            isinstance(self.value, bool) or not isinstance(self.value, int)
        ):
            raise ValueError("provider value must be an integer or None")
        if not isinstance(self.character_updates, Mapping):
            raise ValueError("provider character_updates must be a mapping")
        if not isinstance(self.detail, Mapping):
            raise ValueError("provider detail must be a mapping")
        for character_id, update in self.character_updates.items():
            if (
                isinstance(character_id, bool)
                or not isinstance(character_id, int)
                or character_id < 1
            ):
                raise ValueError("provider character IDs must be positive integers")
            if not isinstance(update, Mapping):
                raise ValueError("provider character updates must be mappings")

    @classmethod
    def complete(
        cls,
        *,
        wait_frames: int = 0,
        value: Optional[int] = None,
        character_updates: Optional[Mapping[int, Mapping[str, object]]] = None,
        detail: Optional[Mapping[str, object]] = None,
        reason: str = "provider completed the command",
    ) -> "ProviderDecision":
        """Return a successful result, optionally after a deterministic wait."""

        return cls(
            status="completed",
            reason=reason,
            wait_frames=wait_frames,
            value=value,
            character_updates=character_updates or {},
            detail=detail or {},
        )

    @classmethod
    def awaiting_input(
        cls,
        reason: str = "provider is waiting for external input",
        *,
        detail: Optional[Mapping[str, object]] = None,
    ) -> "ProviderDecision":
        """Return an intentional interactive checkpoint."""

        return cls(status="awaiting_input", reason=reason, detail=detail or {})

    @classmethod
    def unsupported(
        cls,
        reason: str = "provider cannot handle the command",
        *,
        detail: Optional[Mapping[str, object]] = None,
    ) -> "ProviderDecision":
        """Return a provider-specific unsupported result."""

        return cls(status="unsupported", reason=reason, detail=detail or {})

    @classmethod
    def invalid_data(
        cls,
        reason: str = "provider rejected the command data",
        *,
        detail: Optional[Mapping[str, object]] = None,
    ) -> "ProviderDecision":
        """Return a provider-specific data validation failure."""

        return cls(status="invalid_data", reason=reason, detail=detail or {})


class MessageProvider(Protocol):
    """Display a message or advance a message continuation."""

    def show_message(self, command: Mapping[str, object], context: Any) -> ProviderDecision:
        """Handle one ``ShowMessage`` or continuation command."""


class KeyboardProvider(Protocol):
    """Supply one key result for an RPG Maker ``KeyInputProc`` command."""

    def read_key(self, command: Mapping[str, object], context: Any) -> ProviderDecision:
        """Return the raw key code to store in the command's target variable."""


class MovementProvider(Protocol):
    """Resolve one movement route or its completion barrier."""

    def move_event(self, command: Mapping[str, object], context: Any) -> ProviderDecision:
        """Handle ``MoveEvent`` and ``ProceedWithMovement`` commands."""


@dataclass(frozen=True)
class RuntimeProviders:
    """Optional external services used by :class:`EventTraceRunner`."""

    message: Optional[MessageProvider] = None
    keyboard: Optional[KeyboardProvider] = None
    movement: Optional[MovementProvider] = None


class ScriptedRuntimeProviders:
    """Small deterministic provider useful for tests and replay profiles.

    Each service consumes one decision per command.  Once its queue is empty,
    the configured default result is returned; the default is an explicit
    ``awaiting_input`` checkpoint so a script cannot silently invent state.
    Calls are retained as compact diagnostics for replay tests.
    """

    def __init__(
        self,
        *,
        messages: Sequence[ProviderDecision] = (),
        keys: Sequence[ProviderDecision] = (),
        movements: Sequence[ProviderDecision] = (),
        default: Optional[ProviderDecision] = None,
    ) -> None:
        self._messages: List[ProviderDecision] = list(messages)
        self._keys: List[ProviderDecision] = list(keys)
        self._movements: List[ProviderDecision] = list(movements)
        self._default = default or ProviderDecision.awaiting_input(
            "scripted provider has no decision for this command"
        )
        self.calls: List[dict] = []

    def _take(
        self,
        queue: List[ProviderDecision],
        kind: str,
        command: Mapping[str, object],
    ) -> ProviderDecision:
        decision = queue.pop(0) if queue else self._default
        self.calls.append(
            {
                "kind": kind,
                "code": command.get("code"),
                "decision": decision.status,
            }
        )
        return decision

    def show_message(self, command: Mapping[str, object], context: Any) -> ProviderDecision:
        del context
        return self._take(self._messages, "message", command)

    def read_key(self, command: Mapping[str, object], context: Any) -> ProviderDecision:
        del context
        return self._take(self._keys, "keyboard", command)

    def move_event(self, command: Mapping[str, object], context: Any) -> ProviderDecision:
        del context
        return self._take(self._movements, "movement", command)


__all__ = [
    "KeyboardProvider",
    "MessageProvider",
    "MovementProvider",
    "ProviderDecision",
    "RuntimeProviders",
    "ScriptedRuntimeProviders",
]
