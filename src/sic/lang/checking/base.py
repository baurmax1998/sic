"""Programmprüfung, Berechnungen und Fehlerausgänge."""
from __future__ import annotations
from dataclasses import fields, is_dataclass
from .. import ast
from ..calculation import CalculationSpec, ErrorSpec
from ..dependencies import check_definition_order, check_dependency_cycles, expression_names
from ..effects import EffectOutputSpec, EffectSpec
from ..errors import LangNameError, LangTypeError
from ..registry import ExternalFunction, ModuleRegistry
from .models import CaptureInfo, CheckedListener, CheckedProgram
from ..types import (
    BOOL, FLOAT, INT, NULL, STRING, FunctionType, ListType, MapType,
    NullableType, Primitive, RecordType, Type, TypeVariable, format_type, prune,
    unify,
)


class TypeCheckerBase:
    def __init__(self, registry: ModuleRegistry | None = None):
        self.registry = registry or ModuleRegistry()
        self.counter = 0
        self.records: dict[str, RecordType] = {}
        self.bindings: dict[str, Type] = {}
        self.inputs: dict[str, Type] = {}
        self.direct_errors: dict[str, tuple[ErrorSpec, ...]] = {}
        self.error_payloads: dict[str, Type | None] = {}
        self.call_specs: dict[int, CalculationSpec] = {}
        self.external_calls: dict[int, ExternalFunction] = {}
        self.captures: dict[int, CaptureInfo] = {}
        self.capture_types: dict[int, dict[str, Type]] = {}
        self.local_effects: dict[str, EffectSpec] = {}
        self.effect_outputs: list[EffectOutputSpec] = []
        self.emit_effects: dict[str, EffectSpec] = {}
        self.listeners: list[CheckedListener] = []
        self.void_effects: set[tuple[str, ...]] = set()
        self.ignore_effects: set[tuple[str, ...]] = set()
        self.completion_dependencies: set[str] = set()
        self.program: ast.Program | None = None

    def fresh(self) -> TypeVariable:
        result = TypeVariable(self.counter)
        self.counter += 1
        return result

    def from_ref(self, reference: ast.TypeRef) -> Type:
        if reference.origin:
            result = self.registry.resolve_type(reference.name, reference.origin)
        elif reference.name == "Bool": result: Type = BOOL
        elif reference.name == "Int": result = INT
        elif reference.name == "Float": result = FLOAT
        elif reference.name == "String": result = STRING
        elif reference.name == "List":
            result = ListType(self.from_ref(reference.arguments[0]))
        elif reference.name == "Map":
            result = MapType(
                self.from_ref(reference.arguments[0]),
                self.from_ref(reference.arguments[1]),
            )
        elif reference.arguments:
            raise LangTypeError(f"Unbekannter parametrisierter Typ {reference.name}")
        else:
            result = self.records.setdefault(reference.name, RecordType(reference.name))
        return NullableType(result) if reference.nullable else result

    def check(self, program: ast.Program) -> CheckedProgram:
        for declaration in program.effects:
            self.local_effects[declaration.name] = EffectSpec(
                declaration.name, ("__local_effect__", declaration.name),
                self.from_ref(declaration.payload),
            )
        if not program.bindings:
            return CheckedProgram(
                program, {}, dict(self.records), {}, {}, {}, {}, {}, (), {}, (),
                frozenset(), frozenset(), frozenset(),
            )
        check_definition_order(program)
        check_dependency_cycles(program)
        self.program = program
        # Deklarationsannotationen werden absichtlich noch nicht angewandt:
        # Frühere Verwendungen dürfen den Typ zuerst festlegen. So kann eine
        # spätere, redundante Annotation zuverlässig erkannt werden.
        for binding in program.bindings:
            self.bindings[binding.name] = self.fresh()
        self.prepare_errors(program)
        # Mehrfachausgänge müssen vor dem Goal bekannt sein, damit dortige
        # Präsenzprüfungen (`fehler != null`) korrekt verengt werden können.
        for binding in program.bindings:
            if isinstance(binding.value, ast.OutputAccess):
                unify(self.bindings[binding.name], self.infer_capture(binding.value, self.bindings))
        for binding in program.bindings:
            try:
                expected = self.bindings[binding.name]
                if binding.annotation is not None:
                    declared = self.from_ref(binding.annotation)
                    existing = prune(expected)
                    if (
                        self.is_fully_resolved(existing)
                        and format_type(existing) == format_type(declared)
                    ):
                        raise LangTypeError(
                            f"Redundante Typannotation bei {binding.name!r}; "
                            f"der Typ {format_type(existing)} wurde bereits festgelegt"
                        )
                    unify(expected, declared, binding.name)
                inferred = self.infer(binding.value, self.bindings, expected)
                unify(expected, inferred, binding.name)
            except (LangNameError, LangTypeError) as exc:
                span = binding.value.span
                if span is not None:
                    exc.attach(span.start, span.end)
                raise
        self.prepare_effects(program)
        for name, type_ in {**self.bindings, **self.inputs}.items():
            self.require_resolved(type_, name, set())
        return CheckedProgram(
            program, dict(self.bindings), dict(self.records), dict(self.inputs),
            dict(self.direct_errors), dict(self.call_specs), dict(self.external_calls),
            dict(self.captures), tuple(self.effect_outputs), dict(self.emit_effects),
            tuple(self.listeners), frozenset(self.void_effects),
            frozenset(self.ignore_effects), frozenset(self.completion_dependencies),
        )

    def resolve_effect_name(self, name: ast.Name) -> EffectSpec:
        if name.origin:
            return self.registry.resolve_effect(name.name, name.origin)
        try:
            return self.local_effects[name.name]
        except KeyError as exc:
            raise LangNameError(f"Unbekannter Effekt {name.name}") from exc

    def prepare_effects(self, program: ast.Program) -> None:
        for declaration in program.emits:
            effect = self.resolve_effect_name(declaration.effect)
            self.infer(declaration.payload, self.bindings, effect.payload)
            self.effect_outputs.append(EffectOutputSpec(declaration.name, effect))
            self.emit_effects[declaration.name] = effect
            self.completion_dependencies.update(expression_names(declaration.payload))
        for declaration in program.listeners:
            effect = self.resolve_effect_name(declaration.effect)
            if declaration.filter is not None:
                self.infer(declaration.filter, self.bindings, effect.payload)
                self.completion_dependencies.update(expression_names(declaration.filter))
            self.listeners.append(CheckedListener(declaration, effect))
        for declaration in program.voids:
            self.void_effects.add(self.resolve_effect_name(declaration.effect).identity)
        for declaration in program.ignores:
            self.ignore_effects.add(self.resolve_effect_name(declaration.effect).identity)

    def prepare_errors(self, program: ast.Program) -> None:
        """Reserviert Nutzwerttypen und ordnet Fehler ihren Definitionen zu."""
        def collect(value: object) -> list[ErrorSpec]:
            found: list[ErrorSpec] = []
            if isinstance(value, ast.ErrorExpr):
                payload = self.error_payloads.get(value.name)
                if value.payload is not None:
                    if value.name in self.error_payloads and payload is None:
                        raise LangTypeError(f"Fehler {value.name!r} wird mit und ohne Nutzwert verwendet")
                    payload = payload or self.fresh()
                elif value.name in self.error_payloads and payload is not None:
                    raise LangTypeError(f"Fehler {value.name!r} wird mit und ohne Nutzwert verwendet")
                self.error_payloads[value.name] = payload
                found.append(ErrorSpec(value.name, ("__local__", value.name), payload))
                if value.payload is not None:
                    found.extend(collect(value.payload))
                return found
            if isinstance(value, ast.Call) and isinstance(value.function, ast.Name) and value.function.origin:
                if self.registry.has_calculation(value.function.name, value.function.origin):
                    spec = self.registry.resolve_calculation(value.function.name, value.function.origin)
                    overrides = {item.name for item in value.arguments if isinstance(item, ast.NamedArgument)}
                    found.extend(spec.possible_errors(overrides))
            if isinstance(value, ast.NamedArgument):
                return collect(value.value)
            if isinstance(value, ast.Expr) and is_dataclass(value):
                for descriptor in fields(value):
                    if descriptor.name != "span":
                        found.extend(collect(getattr(value, descriptor.name)))
            elif isinstance(value, tuple):
                for item in value:
                    found.extend(collect(item))
            return found

        for binding in program.bindings:
            unique = {error.identity: error for error in collect(binding.value)}
            self.direct_errors[binding.name] = tuple(unique.values())

    def local_spec(self, symbol: str) -> CalculationSpec:
        assert self.program is not None
        dependencies = {
            binding.name: expression_names(binding.value)
            for binding in self.program.bindings
        }
        # Noch nicht besuchte freie Namen erhalten beim Prüfen des Arguments
        # ihren Typ und werden in dasselbe Interface aufgenommen.
        is_goal = symbol == self.program.goal.name
        return CalculationSpec(
            symbol, (), self.bindings, self.inputs, dependencies,
            self.direct_errors, None,
            tuple(self.effect_outputs) if is_goal else (),
            tuple(self.listeners) if is_goal else (),
            frozenset(self.void_effects), frozenset(self.ignore_effects),
            set(self.completion_dependencies) if is_goal else set(),
        )

    def calculation_spec(self, call: ast.Call) -> CalculationSpec | None:
        if not isinstance(call.function, ast.Name):
            return None
        name = call.function
        if name.origin:
            if self.registry.has_calculation(name.name, name.origin):
                return self.registry.resolve_calculation(name.name, name.origin)
            return None
        if name.name in self.bindings and any(isinstance(arg, ast.NamedArgument) for arg in call.arguments):
            return self.local_spec(name.name)
        return None

    def infer_calculation_call(
        self, call: ast.Call, scope: dict[str, Type], expected: Type | None = None
    ) -> tuple[Type, CalculationSpec]:
        spec = self.calculation_spec(call)
        if spec is None:
            raise LangTypeError("Benannte Argumente benötigen eine aufrufbare Berechnung")
        if any(not isinstance(argument, ast.NamedArgument) for argument in call.arguments):
            raise LangTypeError("Berechnungsaufrufe dürfen benannte und positionale Argumente nicht mischen")
        arguments = list(call.arguments)
        names = [argument.name for argument in arguments]
        if len(names) != len(set(names)):
            raise LangTypeError("Aufruf enthält ein Argument mehrfach")
        allowed = spec.allowed_arguments()
        unknown = set(names) - allowed
        if unknown:
            raise LangNameError(f"Unbekanntes Argument {sorted(unknown)[0]!r} für {spec.symbol!r}")
        missing = spec.required_inputs(set(names))
        if missing:
            raise LangNameError(
                f"Aufruf von {spec.symbol!r} benötigt: {', '.join(sorted(missing))}"
            )
        for argument in arguments:
            argument_type = spec.output_types.get(argument.name)
            if argument_type is None:
                argument_type = spec.input_types.get(argument.name)
            if argument_type is None:
                argument_type = self.inputs.setdefault(argument.name, self.fresh())
                spec.input_types[argument.name] = argument_type
            self.infer(argument.value, scope, argument_type)
        result = spec.result_type
        if expected is not None:
            self.assign(expected, result)
            result = expected
        self.call_specs[id(call)] = spec
        return result, spec

    def infer_capture(self, access: ast.OutputAccess, scope: dict[str, Type]) -> Type:
        key = id(access.captured)
        if key not in self.capture_types:
            call = access.captured.call
            external = None
            if isinstance(call.function, ast.Name) and call.function.origin:
                if self.registry.has_function(call.function.name, call.function.origin):
                    external = self.registry.resolve(call.function.name, call.function.origin)
            if external is not None:
                # Der normale Ausdrucksprüfer validiert positionale und benannte Argumente.
                self.infer(call, scope, external.type.result)
                spec: CalculationSpec | ExternalFunction = external
                errors: tuple[ErrorSpec, ...] = ()
                effects = tuple(
                    EffectOutputSpec(item.name, item.effect)
                    for item in external.effect_outputs
                )
                normal_types = {external.symbol: external.type.result}
                normal_targets = {external.symbol: external.symbol}
                symbol = external.symbol
            else:
                _, calculation = self.infer_calculation_call(call, scope)
                spec = calculation
                errors = calculation.possible_errors({
                    item.name for item in call.arguments
                    if isinstance(item, ast.NamedArgument)
                })
                effects = calculation.possible_effects()
                normal_types = {
                    name: calculation.output_types[name]
                    for name in ({calculation.symbol} | (
                        calculation.allowed_arguments() & set(calculation.output_types)
                    ))
                }
                normal_targets = {name: name for name in normal_types}
                symbol = calculation.symbol
            by_name: dict[str, list[ErrorSpec]] = {}
            for error in errors:
                by_name.setdefault(error.name, []).append(error)
            effects_by_name = {effect.name: effect for effect in effects}
            caught: dict[str, ErrorSpec] = {}
            caught_effects: dict[str, EffectOutputSpec] = {}
            types: dict[str, Type] = {}
            recognized = set(by_name) | set(effects_by_name) | set(normal_types)
            aliases = [name for name in access.captured.outputs if name not in recognized]
            if len(aliases) == 1 and symbol not in access.captured.outputs:
                normal_types[aliases[0]] = (
                    spec.type.result if isinstance(spec, ExternalFunction)
                    else spec.result_type
                )
                normal_targets[aliases[0]] = symbol
            elif aliases:
                raise LangNameError(
                    f"Berechnung {symbol!r} besitzt keinen Ausgang {aliases[0]!r}"
                )
            for name in access.captured.outputs:
                matches = by_name.get(name, [])
                if len(matches) > 1:
                    raise LangTypeError(f"Fehlerausgang {name!r} ist mehrdeutig")
                if matches:
                    caught[name] = matches[0]
                    types[name] = NullableType(matches[0].payload or BOOL)
                elif name in effects_by_name:
                    caught_effects[name] = effects_by_name[name]
                    types[name] = ListType(effects_by_name[name].effect.payload)
                elif name in normal_types:
                    types[name] = normal_types[name]
                else:
                    raise LangNameError(f"Berechnung {symbol!r} besitzt keinen Ausgang {name!r}")
            if caught:
                for name in access.captured.outputs:
                    if name not in caught and name not in caught_effects:
                        types[name] = self.as_nullable(types[name])
            self.capture_types[key] = types
            self.captures[key] = CaptureInfo(
                spec, caught, caught_effects,
                {name: target for name, target in normal_targets.items() if name in types},
            )
        return self.capture_types[key][access.name]

    def is_fully_resolved(self, type_: Type, seen: set[int] | None = None) -> bool:
        seen = set() if seen is None else seen
        type_ = prune(type_)
        if id(type_) in seen:
            return True
        seen.add(id(type_))
        if isinstance(type_, TypeVariable):
            return False
        if isinstance(type_, ListType):
            return self.is_fully_resolved(type_.element, seen)
        if isinstance(type_, MapType):
            return self.is_fully_resolved(type_.key, seen) and self.is_fully_resolved(type_.value, seen)
        if isinstance(type_, NullableType):
            return self.is_fully_resolved(type_.inner, seen)
        if isinstance(type_, FunctionType):
            return all(self.is_fully_resolved(item, seen) for item in [*type_.parameters, type_.result])
        if isinstance(type_, RecordType):
            return all(self.is_fully_resolved(item, seen) for item in type_.fields.values())
        return True

    def require_resolved(self, type_: Type, context: str, seen: set[int]) -> None:
        type_ = prune(type_)
        if id(type_) in seen:
            return
        seen.add(id(type_))
        if isinstance(type_, TypeVariable):
            raise LangTypeError(f"Typ von {context!r} ist nicht eindeutig; Annotation erforderlich")
        if isinstance(type_, ListType):
            self.require_resolved(type_.element, context, seen)
        elif isinstance(type_, MapType):
            self.require_resolved(type_.key, context, seen)
            self.require_resolved(type_.value, context, seen)
        elif isinstance(type_, NullableType):
            self.require_resolved(type_.inner, context, seen)
        elif isinstance(type_, FunctionType):
            for item in [*type_.parameters, type_.result]:
                self.require_resolved(item, context, seen)
        elif isinstance(type_, RecordType):
            for field_name, field_type in type_.fields.items():
                self.require_resolved(field_type, f"{context}.{field_name}", seen)
