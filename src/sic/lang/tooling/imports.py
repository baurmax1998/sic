"""Schnittstellen für externe Funktionen, Typen und Berechnungen."""
from __future__ import annotations

from ..calculation import CalculationSpec
from ..types import (
    FunctionType, ListType, MapType, NullableType, RecordType, Type,
    TypeVariable, format_type, prune,
)
from .analysis import describe_program
from .rendering import render_interface


def _import_type(type_: Type, variables: dict[int, str]) -> str:
    type_ = prune(type_)
    if isinstance(type_, TypeVariable):
        if type_.identifier not in variables:
            index = len(variables)
            variables[type_.identifier] = chr(ord("T") + index) if index < 26 else f"T{index}"
        return variables[type_.identifier]
    if isinstance(type_, ListType):
        return f"List<{_import_type(type_.element, variables)}>"
    if isinstance(type_, MapType):
        return f"Map<{_import_type(type_.key, variables)}, {_import_type(type_.value, variables)}>"
    if isinstance(type_, NullableType):
        return f"{_import_type(type_.inner, variables)}?"
    if isinstance(type_, FunctionType):
        parameters = ", ".join(_import_type(item, variables) for item in type_.parameters)
        return f"({parameters}) -> {_import_type(type_.result, variables)}"
    if isinstance(type_, RecordType):
        if type_.name:
            return ".".join(reversed(type_.name.split("::")))
        fields = " ".join(
            f"{_import_type(value, variables)} {name};"
            for name, value in type_.fields.items()
        )
        return f"record {{ {fields} }}"
    rendered = format_type(type_)
    return ".".join(reversed(rendered.split("::"))) if "::" in rendered else rendered


def _type_import_paths(*types: Type) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()

    def visit(type_: Type) -> None:
        type_ = prune(type_)
        name: str | None = None
        if isinstance(type_, RecordType):
            name = type_.name
            for field_type in type_.fields.values():
                visit(field_type)
        elif hasattr(type_, "name"):
            candidate = getattr(type_, "name")
            name = candidate if isinstance(candidate, str) else None
        if name and "::" in name:
            path = tuple(name.split("::"))
            if path not in seen:
                seen.add(path)
                found.append(path)
        if isinstance(type_, ListType):
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
    return found


def _import_header(package: str, dependencies: list[tuple[str, ...]]) -> list[str]:
    lines = [
        "// Generated import interface; do not edit.",
        "",
        f"package {package};",
        "",
    ]
    if dependencies:
        lines.extend(f"import {'.'.join(reversed(path))};" for path in dependencies)
        lines.append("")
    return lines


def _render_external_import(
    external: object, package: str, dependencies: list[tuple[str, ...]],
) -> str:
    variables: dict[int, str] = {}
    function = external.type
    parameter_types = [_import_type(item, variables) for item in function.parameters]
    result = _import_type(function.result, variables)
    generic = f"<{', '.join(variables.values())}>" if variables else ""
    names = external.parameter_names or tuple(
        f"arg{index}" for index in range(len(parameter_types))
    )
    lines = _import_header(package, dependencies)
    if parameter_types:
        lines.append(f"{result} {external.symbol}{generic}(")
        for index, (name, type_) in enumerate(zip(names, parameter_types)):
            comma = "," if index != len(parameter_types) - 1 else ""
            lines.append(f"    {type_} {name}{comma}")
        lines.append(");")
    else:
        lines.append(f"{result} {external.symbol}{generic}();")
    if external.effect_outputs:
        lines.append("    emits {")
        for output in external.effect_outputs:
            lines.append(
                f"        {_import_type(output.effect.payload, variables)} "
                f"{output.name}: {'::'.join(output.effect.identity)};"
            )
        lines.append("    }")
    if external.automatic_listeners:
        lines.append("    automatically listens {")
        for listener in external.automatic_listeners:
            lines.append(
                f"        {'::'.join(listener.effect.identity)} "
                f"by {listener.payload_parameter};"
            )
        lines.append("    }")
    if external.effect_outputs or external.automatic_listeners:
        lines[-1] += ";"
    lines.append("")
    return "\n".join(lines)


def _render_effect_import(symbol: str, payload: Type, package: str) -> str:
    lines = _import_header(package, [])
    lines.append(f"effect {symbol}: {_import_type(payload, {})};")
    lines.append("")
    return "\n".join(lines)


def _render_type_import(
    symbol: str, type_: Type, package: str, dependencies: list[tuple[str, ...]],
) -> str:
    variables: dict[int, str] = {}
    type_ = prune(type_)
    lines = _import_header(package, dependencies)
    if isinstance(type_, RecordType):
        lines.append(f"record {symbol} {{")
        for name, field_type in type_.fields.items():
            lines.append(f"    {_import_type(field_type, variables)} {name};")
        lines.append("}")
    else:
        rendered = _import_type(type_, variables)
        lines.append(f"type {symbol} = {rendered};" if rendered != symbol else f"type {symbol};")
    lines.append("")
    return "\n".join(lines)


def _render_calculation_import(spec: CalculationSpec, path: tuple[str, ...]) -> str:
    source = "/".join(reversed(path)) + ".sic"
    description = describe_program(spec.checked, source)
    description["calculations"] = [
        calculation for calculation in description["calculations"]
        if calculation["name"] == spec.symbol
    ]
    return render_interface(description)
