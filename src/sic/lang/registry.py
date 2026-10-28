"""Register für externe, vollständig qualifizierte Funktionen."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from .calculation import CalculationSpec, ErrorSpec
from .effects import EffectOutputSpec, EffectSpec, ExternalAutoListener, ExternalEffectOutput
from .errors import LangNameError
from .types import FunctionType, Type, clone_type


@dataclass(frozen=True)
class ExternalFunction:
    symbol: str
    origin: tuple[str, ...]
    type: FunctionType
    implementation: Callable[..., Any]
    parameter_names: tuple[str, ...] = ()
    effect_outputs: tuple[ExternalEffectOutput, ...] = ()
    automatic_listeners: tuple[ExternalAutoListener, ...] = ()

    @property
    def path(self) -> tuple[str, ...]:
        return (self.symbol, *self.origin)


class ModuleRegistry:
    def __init__(self) -> None:
        self._functions: dict[tuple[str, ...], ExternalFunction] = {}
        self._calculations: dict[tuple[str, ...], CalculationSpec] = {}
        self._types: dict[tuple[str, ...], Type] = {}
        self._effects: dict[tuple[str, ...], EffectSpec] = {}

    def register_effect(self, symbol: str, origin: tuple[str, ...], payload: Type) -> EffectSpec:
        path = (symbol, *origin)
        if path in self._effects:
            raise ValueError(f"Effekt {'::'.join(path)} ist bereits registriert")
        effect = EffectSpec(symbol, path, payload)
        self._effects[path] = effect
        return effect

    def resolve_effect(self, symbol: str, origin: tuple[str, ...]) -> EffectSpec:
        path = (symbol, *origin)
        try:
            effect = self._effects[path]
        except KeyError as exc:
            raise LangNameError(f"Unbekannter Effekt {'::'.join(path)}") from exc
        return EffectSpec(effect.name, effect.identity, clone_type(effect.payload))

    def register_type(self, symbol: str, origin: tuple[str, ...], type_: Type) -> None:
        """Registriert einen qualifizierten Typ, etwa ``Page::web``."""
        path = (symbol, *origin)
        if path in self._types:
            raise ValueError(f"Typ {'::'.join(path)} ist bereits registriert")
        self._types[path] = type_

    def resolve_type(self, symbol: str, origin: tuple[str, ...]) -> Type:
        path = (symbol, *origin)
        try:
            return clone_type(self._types[path])
        except KeyError as exc:
            raise LangNameError(f"Unbekannter externer Typ {'::'.join(path)}") from exc

    def register(
        self, symbol: str, origin: tuple[str, ...], type_: FunctionType,
        implementation: Callable[..., Any], parameter_names: tuple[str, ...] = (),
        effect_outputs: tuple[ExternalEffectOutput, ...] = (),
        automatic_listeners: tuple[ExternalAutoListener, ...] = (),
    ) -> None:
        if parameter_names and len(parameter_names) != len(type_.parameters):
            raise ValueError("Parameternamen und Funktionstyp haben unterschiedliche Länge")
        external = ExternalFunction(
            symbol, tuple(origin), type_, implementation, tuple(parameter_names),
            tuple(effect_outputs), tuple(automatic_listeners),
        )
        if external.path in self._functions or external.path in self._calculations:
            raise ValueError(f"Externe Funktion {'::'.join(external.path)} ist bereits registriert")
        self._functions[external.path] = external

    def resolve(self, symbol: str, origin: tuple[str, ...]) -> ExternalFunction:
        path = (symbol, *origin)
        try:
            external = self._functions[path]
        except KeyError as exc:
            raise LangNameError(f"Unbekannte externe Funktion {'::'.join(path)}") from exc
        # Generische Typvariablen einer Signatur dürfen sich nicht zwischen
        # unabhängigen Aufrufen gegenseitig festlegen.
        return ExternalFunction(
            external.symbol,
            external.origin,
            clone_type(external.type),
            external.implementation,
            external.parameter_names,
            tuple(
                ExternalEffectOutput(
                    item.name,
                    EffectSpec(item.effect.name, item.effect.identity, clone_type(item.effect.payload)),
                    item.payload_parameter, item.normalize,
                )
                for item in external.effect_outputs
            ),
            tuple(
                ExternalAutoListener(
                    EffectSpec(item.effect.name, item.effect.identity, clone_type(item.effect.payload)),
                    item.payload_parameter, item.normalize,
                )
                for item in external.automatic_listeners
            ),
        )

    def register_source(self, module: str, package: str, source: str) -> None:
        """Kompiliert eine Datei und exportiert ihr Goal, Lets und Effekte."""
        from .checker import check
        from .parser import parse

        program = parse(source)
        origin = (module, package)
        # Effektdeklarationen müssen bereits während der Prüfung desselben
        # Moduls über ihren Herkunftspfad auflösbar sein.
        from .checking.base import TypeCheckerBase
        resolver = TypeCheckerBase(self)
        for declaration in program.effects:
            self.register_effect(
                declaration.name, origin, resolver.from_ref(declaration.payload)
            )
        if not program.bindings:
            return
        checked = check(program, self)
        dependencies = {
            binding.name: _all_expression_names(binding.value)
            for binding in checked.program.bindings
        }
        for binding in checked.program.bindings:
            # Direkte importierte Fehler behalten ihre ursprüngliche Identität.
            direct = tuple(
                original if original.identity[:1] != ("__local__",) else
                ErrorSpec(original.name, (*origin, original.name), original.payload)
                for original in checked.direct_errors.get(binding.name, ())
            )
            checked.direct_errors[binding.name] = direct
        for binding in checked.program.bindings:
            spec = CalculationSpec(
                binding.name, origin, dict(checked.bindings), dict(checked.inputs),
                dependencies, dict(checked.direct_errors), checked,
                tuple(checked.effect_outputs) if binding.is_goal else (),
                tuple(checked.listeners) if binding.is_goal else (),
                frozenset(checked.void_effects), frozenset(checked.ignore_effects),
                set(checked.completion_dependencies) if binding.is_goal else set(),
            )
            path = (binding.name, *origin)
            if path in self._functions or path in self._calculations:
                raise ValueError(f"Export {'::'.join(path)} ist bereits registriert")
            self._calculations[path] = spec
            # Wenn Modul und Goal gleich heißen, ist `layout::frontend`
            # eindeutig; `layout::layout::frontend` bleibt als voller Pfad
            # verfügbar, muss innerhalb eines Pakets aber nicht geschrieben werden.
            if binding.is_goal and binding.name == module:
                short_path = (binding.name, package)
                if (
                    short_path in self._functions
                    or short_path in self._calculations
                ):
                    raise ValueError(f"Export {'::'.join(short_path)} ist bereits registriert")
                self._calculations[short_path] = spec

    # Verständlicher Alias für Projektintegrationen.
    register_module = register_source

    def resolve_calculation(self, symbol: str, origin: tuple[str, ...]) -> CalculationSpec:
        path = (symbol, *origin)
        try:
            calculation = self._calculations[path]
        except KeyError as exc:
            raise LangNameError(f"Unbekannte Berechnung {'::'.join(path)}") from exc
        variables = {}
        return CalculationSpec(
            calculation.symbol,
            calculation.origin,
            {name: clone_type(type_, variables) for name, type_ in calculation.output_types.items()},
            {name: clone_type(type_, variables) for name, type_ in calculation.input_types.items()},
            calculation.dependencies,
            {
                name: tuple(ErrorSpec(error.name, error.identity,
                                      clone_type(error.payload, variables) if error.payload else None)
                            for error in errors)
                for name, errors in calculation.direct_errors.items()
            },
            calculation.checked,
            tuple(
                EffectOutputSpec(
                    output.name,
                    EffectSpec(
                        output.effect.name, output.effect.identity,
                        clone_type(output.effect.payload, variables),
                    ),
                )
                for output in calculation.effect_outputs
            ),
            calculation.listeners,
            calculation.void_effects,
            calculation.ignore_effects,
            set(calculation.completion_dependencies),
        )

    def has_calculation(self, symbol: str, origin: tuple[str, ...]) -> bool:
        return (symbol, *origin) in self._calculations

    def has_function(self, symbol: str, origin: tuple[str, ...]) -> bool:
        return (symbol, *origin) in self._functions

    def has_type(self, symbol: str, origin: tuple[str, ...]) -> bool:
        return (symbol, *origin) in self._types

    def has_effect(self, symbol: str, origin: tuple[str, ...]) -> bool:
        return (symbol, *origin) in self._effects

    def paths(self) -> tuple[tuple[str, ...], ...]:
        return tuple(sorted((*self._functions, *self._calculations, *self._types, *self._effects)))


def _all_expression_names(expression):
    """Freie Namen einschließlich noch nicht definierter Eingaben."""
    from .dependencies import expression_names
    return expression_names(expression)
