"""Statische Analyse der Abhängigkeiten zwischen Top-Level-Bindings."""
from __future__ import annotations
from dataclasses import fields, is_dataclass
from typing import Iterable

from . import ast
from .errors import LangError


class LangDependencyError(LangError):
    pass


class LangDefinitionOrderError(LangError):
    pass


def expression_names(expression: ast.Expr, local: frozenset[str] = frozenset()) -> set[str]:
    """Sammelt unqualifizierte freie Namen eines Ausdrucks."""
    if isinstance(expression, ast.Name):
        return set() if expression.origin or expression.name in local else {expression.name}
    if isinstance(expression, ast.Lambda):
        return expression_names(expression.body, local | frozenset(expression.parameters))
    if isinstance(expression, ast.LocalLet):
        return (
            expression_names(expression.value, local)
            | expression_names(expression.body, local | {expression.name})
        )
    if isinstance(expression, ast.OutputAccess):
        return expression_names(expression.captured.call, local)
    if isinstance(expression, ast.MatchExpr):
        result = expression_names(expression.value, local)
        for case in expression.cases:
            case_local = local
            if isinstance(case.pattern, ast.BindingPattern):
                case_local = local | {case.pattern.name}
            result.update(expression_names(case.body, case_local))
        return result
    result: set[str] = set()
    if is_dataclass(expression):
        for descriptor in fields(expression):
            value = getattr(expression, descriptor.name)
            result.update(_names_in_value(value, local))
    return result


def _names_in_value(value: object, local: frozenset[str]) -> set[str]:
    if isinstance(value, ast.Expr):
        return expression_names(value, local)
    if isinstance(value, ast.NamedArgument):
        return expression_names(value.value, local)
    if isinstance(value, tuple):
        result: set[str] = set()
        for item in value:
            if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], ast.Expr):
                result.update(expression_names(item[1], local))
            else:
                result.update(_names_in_value(item, local))
        return result
    return set()


def check_definition_order(program: ast.Program) -> None:
    """Erzwingt: Ziel zuerst, danach ausschließlich bereits benötigte Namen."""
    if not program.bindings or not program.bindings[0].is_goal:
        binding = program.bindings[0] if program.bindings else None
        error = LangDefinitionOrderError("Das goal muss die erste Definition sein")
        if binding is not None and binding.span is not None:
            error.attach(binding.span.start, binding.span.end)
        raise error

    required = expression_names(program.bindings[0].value)
    for declaration in program.emits:
        required.update(expression_names(declaration.payload))
    for declaration in program.listeners:
        if declaration.filter is not None:
            required.update(expression_names(declaration.filter))
    index = 1
    while index < len(program.bindings):
        binding = program.bindings[index]
        group = [binding]
        if isinstance(binding.value, ast.OutputAccess):
            captured = binding.value.captured
            while (
                index + len(group) < len(program.bindings)
                and isinstance(program.bindings[index + len(group)].value, ast.OutputAccess)
                and program.bindings[index + len(group)].value.captured is captured
            ):
                group.append(program.bindings[index + len(group)])
        if not any(item.name in required for item in group):
            error = LangDefinitionOrderError(
                f"{binding.name!r} wird definiert, bevor der Name benötigt wird"
            )
            if binding.span is not None:
                error.attach(binding.span.start, binding.span.end)
            raise error
        for item in group:
            required.discard(item.name)
        required.update(expression_names(binding.value))
        index += len(group)


def dependency_graph(program: ast.Program) -> dict[str, set[str]]:
    names = {binding.name for binding in program.bindings}
    return {
        binding.name: expression_names(binding.value) & names
        for binding in program.bindings
    }


def check_dependency_cycles(program: ast.Program) -> dict[str, set[str]]:
    graph = dependency_graph(program)
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            start = visiting.index(name)
            cycle = visiting[start:] + [name]
            error = LangDependencyError(
                "Unzulässiger Abhängigkeitszyklus: " + " -> ".join(cycle)
            )
            binding = next(item for item in program.bindings if item.name == name)
            if binding.span is not None:
                error.attach(binding.span.start, binding.span.end)
            raise error
        if name in visited:
            return
        visiting.append(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.pop()
        visited.add(name)

    for name in graph:
        visit(name)
    return graph
