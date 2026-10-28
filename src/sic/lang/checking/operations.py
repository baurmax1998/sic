"""Typregeln für Zuweisungen, Operatoren und Collections."""
from __future__ import annotations
from dataclasses import fields, is_dataclass
from .. import ast
from ..calculation import CalculationSpec, ErrorSpec
from ..dependencies import check_definition_order, check_dependency_cycles
from ..errors import LangNameError, LangTypeError
from ..registry import ExternalFunction, ModuleRegistry
from ..types import (
    BOOL, FLOAT, INT, NULL, STRING, FunctionType, ListType, MapType,
    NullableType, Primitive, RecordType, Type, TypeVariable, format_type, prune,
    unify,
)


class OperationInferenceMixin:
    def assign(self, expected: Type, actual: Type) -> None:
        expected, actual = prune(expected), prune(actual)
        if isinstance(expected, NullableType):
            if actual == NULL:
                return
            if isinstance(actual, NullableType):
                unify(expected.inner, actual.inner)
            else:
                unify(expected.inner, actual)
            return
        unify(expected, actual)

    def as_nullable(self, type_: Type) -> NullableType:
        type_ = prune(type_)
        return type_ if isinstance(type_, NullableType) else NullableType(type_)

    def narrow_scopes(
        self, condition: ast.Expr, scope: dict[str, Type]
    ) -> tuple[dict[str, Type], dict[str, Type]]:
        then_scope, else_scope = dict(scope), dict(scope)
        if isinstance(condition, ast.Binary) and condition.operator in {"==", "!="}:
            name = None
            if isinstance(condition.left, ast.Name) and isinstance(condition.right, ast.Literal) and condition.right.value is None:
                name = condition.left.name
            elif isinstance(condition.right, ast.Name) and isinstance(condition.left, ast.Literal) and condition.left.value is None:
                name = condition.right.name
            if name in scope:
                current = prune(scope[name])
                if isinstance(current, NullableType):
                    non_null_scope = then_scope if condition.operator == "!=" else else_scope
                    non_null_scope[name] = current.inner
        return then_scope, else_scope

    def infer_binary(self, expression: ast.Binary, scope: dict[str, Type], expected: Type | None) -> Type:
        operator = expression.operator
        if operator == "??":
            result = expected or self.fresh()
            self.infer(expression.left, scope, NullableType(result))
            self.infer(expression.right, scope, result)
            return result
        if operator in {"and", "or"}:
            self.infer(expression.left, scope, BOOL); self.infer(expression.right, scope, BOOL)
            return BOOL
        if operator in {"<", "<=", ">", ">="}:
            operand = prune(self.infer(expression.left, scope))
            if operand not in (INT, FLOAT, STRING):
                raise LangTypeError(f"{operator!r} unterstützt nicht {format_type(operand)}")
            self.infer(expression.right, scope, operand)
            return BOOL
        if operator in {"==", "!="}:
            operand = self.infer(expression.left, scope)
            self.infer(expression.right, scope, operand)
            return BOOL
        if operator in {"-", "*", "%", "/"}:
            wanted = prune(expected) if expected is not None else None
            if wanted not in (INT, FLOAT):
                wanted = prune(self.infer(expression.left, scope))
            if wanted not in (INT, FLOAT):
                raise LangTypeError(f"{operator!r} benötigt Int oder Float")
            if operator == "/" and wanted != FLOAT:
                raise LangTypeError("'/' benötigt Float-Operanden")
            self.infer(expression.left, scope, wanted)
            self.infer(expression.right, scope, wanted)
            return wanted
        if operator == "+":
            wanted = prune(expected) if expected is not None else None
            if isinstance(wanted, ListType):
                self.infer(expression.left, scope, wanted)
                self.infer(expression.right, scope, wanted)
                return wanted
            if wanted not in (INT, FLOAT, STRING):
                left = prune(self.infer(expression.left, scope))
                if left not in (INT, FLOAT, STRING) and not isinstance(left, ListType):
                    raise LangTypeError("'+' benötigt Zahlen, Strings oder Listen")
                wanted = left
            self.infer(expression.left, scope, wanted)
            self.infer(expression.right, scope, wanted)
            return wanted
        raise LangTypeError(f"Unbekannter Operator {operator}")

    def infer_method(self, expression: ast.MethodCall, scope: dict[str, Type], expected: Type | None) -> Type:
        collection = prune(self.infer(expression.value, scope))
        if isinstance(collection, TypeVariable):
            collection.instance = ListType(self.fresh())
            collection = collection.instance
        if isinstance(collection, MapType):
            if expression.name == "keys" and not expression.arguments:
                return ListType(collection.key)
            if expression.name == "values" and not expression.arguments:
                return ListType(collection.value)
            if expression.name == "get" and len(expression.arguments) == 1:
                self.infer(expression.arguments[0], scope, collection.key)
                return NullableType(collection.value)
            if expression.name == "contains_key" and len(expression.arguments) == 1:
                self.infer(expression.arguments[0], scope, collection.key)
                return BOOL
            raise LangTypeError(f"Unbekannte Map-Operation .{expression.name}")
        if not isinstance(collection, ListType):
            raise LangTypeError(f".{expression.name} benötigt eine Liste oder Map")
        element = collection.element
        if expression.name == "filter" and len(expression.arguments) == 1:
            self.infer(expression.arguments[0], scope, FunctionType([element], BOOL))
            return collection
        if expression.name == "map" and len(expression.arguments) == 1:
            mapped = prune(expected).element if isinstance(prune(expected), ListType) else self.fresh()
            self.infer(expression.arguments[0], scope, FunctionType([element], mapped))
            return ListType(mapped)
        if expression.name == "flat_map" and len(expression.arguments) == 1:
            mapped = prune(expected).element if isinstance(prune(expected), ListType) else self.fresh()
            self.infer(expression.arguments[0], scope, FunctionType([element], ListType(mapped)))
            return ListType(mapped)
        if expression.name == "sum" and not expression.arguments:
            numeric = prune(element)
            if numeric not in (INT, FLOAT):
                raise LangTypeError("sum benötigt List<Int> oder List<Float>")
            return numeric
        if expression.name == "fold" and len(expression.arguments) == 2:
            accumulator = self.infer(expression.arguments[0], scope, expected)
            self.infer(expression.arguments[1], scope, FunctionType([accumulator, element], accumulator))
            return accumulator
        if expression.name in {"any", "all"} and len(expression.arguments) == 1:
            self.infer(expression.arguments[0], scope, FunctionType([element], BOOL))
            return BOOL
        if expression.name == "count" and not expression.arguments:
            return INT
        if expression.name in {"take", "drop"} and len(expression.arguments) == 1:
            self.infer(expression.arguments[0], scope, INT)
            return collection
        if expression.name in {"first", "last"} and not expression.arguments:
            return NullableType(element)
        if expression.name == "find" and len(expression.arguments) == 1:
            self.infer(expression.arguments[0], scope, FunctionType([element], BOOL))
            return NullableType(element)
        if expression.name == "sort" and not expression.arguments:
            if prune(element) not in (INT, FLOAT, STRING):
                raise LangTypeError("sort benötigt vergleichbare Elemente")
            return collection
        if expression.name == "group_by" and len(expression.arguments) == 1:
            key = self.fresh()
            self.infer(expression.arguments[0], scope, FunctionType([element], key))
            return MapType(key, ListType(element))
        raise LangTypeError(f"Unbekannte oder falsch verwendete Listenoperation .{expression.name}")
