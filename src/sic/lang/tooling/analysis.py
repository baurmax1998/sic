"""Ableitung des nicht-flachen Schnittstellenmodells aus geprüften SIC-Programmen."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from itertools import combinations
import json
from pathlib import Path
import re
from typing import Iterable

from .. import ast
from ..calculation import CalculationSpec, ErrorSpec
from ..checker import CheckedProgram
from ..types import (
    FunctionType, ListType, MapType, NullableType, RecordType, Type,
    format_type, prune,
)


def _calculation(checked: CheckedProgram, symbol: str) -> CalculationSpec:
    from ..dependencies import expression_names

    is_goal = symbol == checked.program.goal.name
    return CalculationSpec(
        symbol=symbol,
        origin=(),
        output_types=dict(checked.bindings),
        input_types=dict(checked.inputs),
        dependencies={
            binding.name: expression_names(binding.value)
            for binding in checked.program.bindings
        },
        direct_errors=dict(checked.direct_errors),
        checked=checked,
        effect_outputs=checked.effect_outputs if is_goal else (),
        listeners=checked.listeners if is_goal else (),
        void_effects=checked.void_effects,
        ignore_effects=checked.ignore_effects,
        completion_dependencies=set(checked.completion_dependencies) if is_goal else set(),
    )


def _reachable_outputs(spec: CalculationSpec) -> set[str]:
    found = {spec.symbol}

    def visit(name: str) -> None:
        for dependency in spec.dependencies.get(name, set()):
            if dependency in spec.output_types and dependency not in found:
                found.add(dependency)
                visit(dependency)

    visit(spec.symbol)
    return found


def _default_order(spec: CalculationSpec, checked: CheckedProgram) -> list[str]:
    """Ordnet Defaults nach ihren Voraussetzungen und danach wie im Quelltext."""
    source_index = {
        binding.name: index for index, binding in enumerate(checked.program.bindings)
    }
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        for dependency in sorted(
            spec.dependencies.get(name, set()),
            key=lambda item: source_index.get(item, len(source_index)),
        ):
            if dependency not in spec.output_types or dependency in visited:
                continue
            visited.add(dependency)
            visit(dependency)
            ordered.append(dependency)

    visit(spec.symbol)
    return ordered


def _active_overrides(spec: CalculationSpec, selected: set[str]) -> set[str]:
    """Entfernt Overrides, deren Vorfahr bereits den Teilgraphen abschneidet."""
    active: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for dependency in spec.dependencies.get(name, set()):
            if dependency in selected:
                active.add(dependency)
            elif dependency in spec.output_types:
                visit(dependency)

    visit(spec.symbol)
    return active


def _input_variants(spec: CalculationSpec) -> list[tuple[set[str], set[str]]]:
    """Liefert jeden wirksamen Schnitt durch den Abhängigkeitsgraphen.

    Der erste Wert ist die Menge überschriebener Zwischenwerte, der zweite die
    tatsächlich zu übergebende Argumentmenge einschließlich freier Eingaben.
    """
    internal = sorted(_reachable_outputs(spec) - {spec.symbol})
    variants: list[tuple[set[str], set[str]]] = []
    for size in range(len(internal) + 1):
        for items in combinations(internal, size):
            selected = set(items)
            if _active_overrides(spec, selected) != selected:
                continue
            arguments = selected | spec.required_inputs(selected)
            variants.append((selected, arguments))
    variants.sort(key=lambda item: (len(item[1]), sorted(item[1]), sorted(item[0])))
    return variants


def _interface_type(type_: Type) -> str:
    type_ = prune(type_)
    if isinstance(type_, ListType):
        return f"List<{_interface_type(type_.element)}>"
    if isinstance(type_, MapType):
        return f"Map<{_interface_type(type_.key)}, {_interface_type(type_.value)}>"
    if isinstance(type_, NullableType):
        return f"{_interface_type(type_.inner)}?"
    if isinstance(type_, RecordType):
        if type_.name:
            return type_.name
        fields = " ".join(
            f"{_interface_type(field_type)} {name};"
            for name, field_type in type_.fields.items()
        )
        return f"record {{ {fields} }}"
    if isinstance(type_, FunctionType):
        parameters = ", ".join(_interface_type(item) for item in type_.parameters)
        return f"({parameters}) -> {_interface_type(type_.result)}"
    return format_type(type_)


def _type_ref(reference: ast.TypeRef) -> str:
    name = "::".join((reference.name, *reference.origin))
    if reference.arguments:
        name += "<" + ", ".join(_type_ref(item) for item in reference.arguments) + ">"
    return name + ("?" if reference.nullable else "")


def _error_value(error: ErrorSpec) -> dict[str, object]:
    return {
        "name": error.name,
        "type": _interface_type(error.payload) if error.payload is not None else "Bool",
        "payload": error.payload is not None,
        "identity": "::".join(error.identity),
    }


def _collect_records(types: Iterable[Type]) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    visiting: set[int] = set()

    def visit(type_: Type) -> None:
        type_ = prune(type_)
        if id(type_) in visiting:
            return
        visiting.add(id(type_))
        if isinstance(type_, RecordType):
            for field_type in type_.fields.values():
                visit(field_type)
            if type_.name:
                records[type_.name] = {
                    name: _interface_type(field_type)
                    for name, field_type in sorted(type_.fields.items())
                }
        elif isinstance(type_, ListType):
            visit(type_.element)
        elif isinstance(type_, MapType):
            visit(type_.key)
            visit(type_.value)
        elif isinstance(type_, NullableType):
            visit(type_.inner)
        elif isinstance(type_, FunctionType):
            for item in (*type_.parameters, type_.result):
                visit(item)

    for item in types:
        visit(item)
    return dict(sorted(records.items()))


def _program_imports(program: object) -> list[dict[str, object]]:
    """Sammelt qualifizierte Typen und Symbole in Quelltextreihenfolge."""
    imports: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()

    def add(name: str, origin: tuple[str, ...]) -> None:
        # SIC adressiert vom Symbol zur Herkunft (`write_json::files::std`).
        # Imports verwenden die aus C#/Java/TypeScript vertraute Richtung.
        path = (name, *origin)
        if path not in seen:
            seen.add(path)
            imports.append({
                "name": ".".join(reversed(path)),
                "path": path,
            })

    def visit(value: object) -> None:
        # Bei Top-Level-Bindings steht die Annotation syntaktisch vor dem Wert,
        # obwohl das AST-Feld ``value`` aus Laufzeitgründen zuerst definiert ist.
        if isinstance(value, ast.Binding):
            visit(value.annotation)
            visit(value.value)
            return
        if isinstance(value, ast.LocalLet):
            visit(value.annotation)
            visit(value.value)
            visit(value.body)
            return
        if isinstance(value, ast.Name) and value.origin:
            add(value.name, value.origin)
        elif isinstance(value, ast.TypeRef) and value.origin:
            add(value.name, value.origin)
        if is_dataclass(value):
            for descriptor in fields(value):
                if descriptor.name != "span":
                    visit(getattr(value, descriptor.name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                visit(item)

    visit(program)
    return imports


def _default_text(expression: object, dependencies: set[str]) -> str:
    """Zeigt Konstanten direkt und sonst die abgeleiteten Abhängigkeiten an."""
    if isinstance(expression, ast.Literal):
        if expression.value is None:
            return "null"
        if isinstance(expression.value, bool):
            return str(expression.value).lower()
        if isinstance(expression.value, str):
            return json.dumps(expression.value, ensure_ascii=False)
        return str(expression.value)
    if (
        isinstance(expression, ast.Unary)
        and expression.operator == "-"
        and isinstance(expression.operand, ast.Literal)
    ):
        return f"-{expression.operand.value}"
    arguments = ", ".join(sorted(dependencies))
    return f"derive({arguments})"


def describe_program(checked: CheckedProgram, source: str) -> dict[str, object]:
    """Erzeugt die vollständige Schnittstellenbeschreibung eines Programms."""
    calculations: list[dict[str, object]] = []
    binding_by_name = {binding.name: binding for binding in checked.program.bindings}
    all_types: list[Type] = [*checked.bindings.values(), *checked.inputs.values()]
    all_types.extend(effect.effect.payload for effect in checked.effect_outputs)
    for errors in checked.direct_errors.values():
        all_types.extend(error.payload for error in errors if error.payload is not None)

    for binding in checked.program.bindings:
        spec = _calculation(checked, binding.name)
        reachable = _reachable_outputs(spec)
        # Die Reihenfolge folgt den Deklarationen im Quelltext statt der
        # Iteration über Sets. Das Goal steht dadurch zuerst, danach die Lets.
        output_names = [
            item.name for item in checked.program.bindings
            if item.name in reachable
        ]
        signatures: list[dict[str, object]] = []
        for overrides, arguments in _input_variants(spec):
            errors = sorted(
                spec.possible_errors(overrides),
                key=lambda error: (error.name, error.identity),
            )
            signatures.append({
                "inputs": {
                    name: _interface_type(
                        spec.output_types[name]
                        if name in spec.output_types else spec.input_types[name]
                    )
                    for name in sorted(arguments)
                },
                "overrides": sorted(overrides),
                "outputs": {
                    name: _interface_type(spec.output_types[name])
                    for name in output_names
                },
                "errors": [_error_value(error) for error in errors],
                "effects": [
                    {
                        "name": output.name,
                        "effect": "::".join(output.effect.identity),
                        "type": _interface_type(output.effect.payload),
                    }
                    for output in spec.possible_effects()
                ],
            })
        calculations.append({
            "name": binding.name,
            "type": _interface_type(spec.result_type),
            "goal": binding.is_goal,
            "defaults": {
                name: _default_text(
                    binding_by_name[name].value,
                    spec.dependencies.get(name, set()),
                )
                for name in _default_order(spec, checked)
            },
            "signatures": signatures,
        })

    return {
        "format": "sic-interface-v1",
        "source": source,
        "goal": checked.program.goal.name if checked.program.bindings else None,
        "package": _package_name(source),
        "imports": _program_imports(checked.program),
        "types": _collect_records(all_types),
        "effects": [
            {"name": effect.name, "type": _type_ref(effect.payload)}
            for effect in checked.program.effects
        ],
        "calculations": calculations,
    }


def _identifier(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return f"_{name}" if name[:1].isdigit() else name


def _package_name(source: str) -> str:
    path = Path(source)
    directories = () if path.parent.parts == (".",) else path.parent.parts
    return ".".join((*(_identifier(part) for part in directories), _identifier(path.stem)))
