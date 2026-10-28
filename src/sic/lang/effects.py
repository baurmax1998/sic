"""Typisierte Änderungsmeldungen und ihre Laufzeitabonnements."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .types import Type


@dataclass(frozen=True)
class EffectSpec:
    name: str
    identity: tuple[str, ...]
    payload: Type


@dataclass(frozen=True)
class EffectOutputSpec:
    name: str
    effect: EffectSpec


@dataclass(frozen=True)
class EffectMessage:
    effect: EffectSpec
    payload: Any
    output: str


@dataclass(frozen=True)
class EffectSubscription:
    effect: EffectSpec
    filter: Any = None
    filtered: bool = False
    automatic: bool = False

    def matches(self, message: EffectMessage) -> bool:
        return (
            self.effect.identity == message.effect.identity
            and (not self.filtered or self.filter == message.payload)
        )


@dataclass(frozen=True)
class ExternalEffectOutput:
    """Effekt einer externen Funktion; der Payload stammt aus einem Argument."""
    name: str
    effect: EffectSpec
    payload_parameter: str
    normalize: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class ExternalAutoListener:
    effect: EffectSpec
    payload_parameter: str
    normalize: Callable[[Any], Any] | None = None
