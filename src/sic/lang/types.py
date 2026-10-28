"""Interne Typrepräsentation und Unifikation."""
from __future__ import annotations
from dataclasses import dataclass, field
from .errors import LangTypeError


class Type: pass


@dataclass(frozen=True)
class Primitive(Type):
    name: str


BOOL = Primitive("Bool")
INT = Primitive("Int")
FLOAT = Primitive("Float")
STRING = Primitive("String")
NULL = Primitive("Null")


@dataclass
class TypeVariable(Type):
    identifier: int
    instance: Type | None = None


@dataclass
class ListType(Type):
    element: Type


@dataclass
class MapType(Type):
    key: Type
    value: Type


@dataclass
class NullableType(Type):
    inner: Type


@dataclass
class RecordType(Type):
    name: str | None
    fields: dict[str, Type] = field(default_factory=dict)
    closed: bool = False


@dataclass
class FunctionType(Type):
    parameters: list[Type]
    result: Type


def prune(type_: Type) -> Type:
    if isinstance(type_, TypeVariable) and type_.instance is not None:
        type_.instance = prune(type_.instance)
        return type_.instance
    return type_


def occurs(variable: TypeVariable, type_: Type) -> bool:
    type_ = prune(type_)
    if type_ is variable:
        return True
    if isinstance(type_, ListType):
        return occurs(variable, type_.element)
    if isinstance(type_, MapType):
        return occurs(variable, type_.key) or occurs(variable, type_.value)
    if isinstance(type_, NullableType):
        return occurs(variable, type_.inner)
    if isinstance(type_, FunctionType):
        return any(occurs(variable, item) for item in [*type_.parameters, type_.result])
    if isinstance(type_, RecordType):
        return any(occurs(variable, item) for item in type_.fields.values())
    return False


def unify(left: Type, right: Type, context: str = "") -> Type:
    left, right = prune(left), prune(right)
    if left is right:
        return left
    if isinstance(left, TypeVariable):
        if occurs(left, right):
            raise LangTypeError(f"Rekursiver Typ{_at(context)}")
        left.instance = right
        return right
    if isinstance(right, TypeVariable):
        return unify(right, left, context)
    if left == NULL and isinstance(right, NullableType):
        return right
    if right == NULL and isinstance(left, NullableType):
        return left
    if isinstance(left, NullableType) and isinstance(right, NullableType):
        unify(left.inner, right.inner, context)
        return left
    if isinstance(left, Primitive) and isinstance(right, Primitive) and left == right:
        return left
    if isinstance(left, ListType) and isinstance(right, ListType):
        unify(left.element, right.element, context)
        return left
    if isinstance(left, MapType) and isinstance(right, MapType):
        unify(left.key, right.key, context)
        unify(left.value, right.value, context)
        return left
    if isinstance(left, FunctionType) and isinstance(right, FunctionType):
        if len(left.parameters) != len(right.parameters):
            raise LangTypeError(f"Unterschiedliche Parameteranzahl{_at(context)}")
        for a, b in zip(left.parameters, right.parameters):
            unify(a, b, context)
        unify(left.result, right.result, context)
        return left
    if isinstance(left, RecordType) and isinstance(right, RecordType):
        # Benannte Records sammeln Anforderungen; anonyme Literale dürfen mehr Felder haben.
        if left.name and right.name and left.name != right.name:
            raise LangTypeError(f"Record-Typen {left.name} und {right.name} sind verschieden{_at(context)}")
        shared = set(left.fields) & set(right.fields)
        for name in shared:
            unify(left.fields[name], right.fields[name], f"Feld {name}")
        if left.name:
            missing = set(left.fields) - set(right.fields) if right.closed else set()
            if missing:
                raise LangTypeError(f"Record fehlt Feld {sorted(missing)[0]!r}{_at(context)}")
            for name, value in right.fields.items():
                left.fields.setdefault(name, value)
            return left
        if right.name:
            return unify(right, left, context)
        if set(left.fields) != set(right.fields):
            raise LangTypeError(f"Unterschiedliche Record-Felder{_at(context)}")
        return left
    raise LangTypeError(f"Typkonflikt: {format_type(left)} und {format_type(right)}{_at(context)}")


def clone_type(type_: Type, variables: dict[int, TypeVariable] | None = None) -> Type:
    """Kopiert eine Signatur, damit jede externe Verwendung frisch typisiert wird."""
    variables = {} if variables is None else variables
    type_ = prune(type_)
    if isinstance(type_, Primitive):
        return type_
    if isinstance(type_, TypeVariable):
        return variables.setdefault(type_.identifier, TypeVariable(type_.identifier))
    if isinstance(type_, ListType):
        return ListType(clone_type(type_.element, variables))
    if isinstance(type_, MapType):
        return MapType(clone_type(type_.key, variables), clone_type(type_.value, variables))
    if isinstance(type_, NullableType):
        return NullableType(clone_type(type_.inner, variables))
    if isinstance(type_, RecordType):
        return RecordType(type_.name, {
            name: clone_type(field_type, variables)
            for name, field_type in type_.fields.items()
        }, type_.closed)
    if isinstance(type_, FunctionType):
        return FunctionType(
            [clone_type(parameter, variables) for parameter in type_.parameters],
            clone_type(type_.result, variables),
        )
    raise TypeError(type_)


def format_type(type_: Type) -> str:
    type_ = prune(type_)
    if isinstance(type_, Primitive): return type_.name
    if isinstance(type_, TypeVariable): return f"?{type_.identifier}"
    if isinstance(type_, ListType): return f"List<{format_type(type_.element)}>"
    if isinstance(type_, MapType): return f"Map<{format_type(type_.key)}, {format_type(type_.value)}>"
    if isinstance(type_, NullableType): return f"{format_type(type_.inner)}?"
    if isinstance(type_, RecordType):
        if type_.name: return type_.name
        fields = ", ".join(f"{k}: {format_type(v)}" for k, v in type_.fields.items())
        return "{" + fields + "}"
    if isinstance(type_, FunctionType):
        return "(" + ", ".join(map(format_type, type_.parameters)) + ") => " + format_type(type_.result)
    return repr(type_)


def _at(context: str) -> str:
    return f" bei {context}" if context else ""
