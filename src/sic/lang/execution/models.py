"""Werte einer SIC-Ausführung."""
from dataclasses import dataclass
from typing import Any

from ..effects import EffectMessage, EffectSubscription


@dataclass(frozen=True)
class ExecutionResult:
    goal: str
    value: Any
    effects: tuple[EffectMessage, ...] = ()
    subscriptions: tuple[EffectSubscription, ...] = ()
