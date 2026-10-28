"""Schnittstellen aufrufbarer zielorientierter Berechnungen."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from .effects import EffectOutputSpec, EffectSpec
from .types import Type


@dataclass(frozen=True)
class ErrorSpec:
    """Ein benannter Fehler; ``payload`` ist bei ``err name`` nicht gesetzt."""
    name: str
    identity: tuple[str, ...]
    payload: Type | None = None


@dataclass
class CalculationSpec:
    """Nicht-flache Schnittstelle eines Goals oder Lets."""
    symbol: str
    origin: tuple[str, ...]
    output_types: dict[str, Type]
    input_types: dict[str, Type]
    dependencies: dict[str, set[str]]
    direct_errors: dict[str, tuple[ErrorSpec, ...]]
    checked: Any = None
    effect_outputs: tuple[EffectOutputSpec, ...] = ()
    listeners: tuple[Any, ...] = ()
    void_effects: frozenset[tuple[str, ...]] = frozenset()
    ignore_effects: frozenset[tuple[str, ...]] = frozenset()
    completion_dependencies: set[str] = field(default_factory=set)

    @property
    def result_type(self) -> Type:
        return self.output_types[self.symbol]

    def required_inputs(self, overrides: set[str] | frozenset[str] = frozenset()) -> set[str]:
        """Ermittelt Eingaben; ein Override schneidet seinen Teilgraphen ab."""
        required: set[str] = set()
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in overrides:
                return
            if name not in self.output_types:
                required.add(name)
                return
            if name in visiting:  # Zyklen wurden bereits vom Checker abgelehnt.
                return
            visiting.add(name)
            for dependency in self.dependencies.get(name, set()):
                visit(dependency)
            visiting.remove(name)

        visit(self.symbol)
        for dependency in self.completion_dependencies:
            if dependency != self.symbol:
                visit(dependency)
        return required

    def allowed_arguments(self) -> set[str]:
        reachable: set[str] = set()

        def visit(name: str) -> None:
            for dependency in self.dependencies.get(name, set()):
                if dependency in reachable:
                    continue
                reachable.add(dependency)
                if dependency in self.output_types:
                    visit(dependency)

        visit(self.symbol)
        for dependency in self.completion_dependencies:
            if dependency != self.symbol:
                reachable.add(dependency)
                if dependency in self.output_types:
                    visit(dependency)
        return reachable

    def possible_errors(self, overrides: set[str] | frozenset[str] = frozenset()) -> tuple[ErrorSpec, ...]:
        found: dict[tuple[str, ...], ErrorSpec] = {}
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in overrides or name not in self.output_types or name in visiting:
                return
            visiting.add(name)
            for error in self.direct_errors.get(name, ()):
                found[error.identity] = error
            for dependency in self.dependencies.get(name, set()):
                visit(dependency)
            visiting.remove(name)

        visit(self.symbol)
        return tuple(found.values())

    def possible_effects(self) -> tuple[EffectOutputSpec, ...]:
        return self.effect_outputs
