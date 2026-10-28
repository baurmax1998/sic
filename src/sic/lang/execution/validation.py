"""Laufzeitvalidierung externer SIC-Werte."""
from __future__ import annotations
from typing import Any
from ..errors import LangRuntimeError
from ..types import (
    FunctionType, ListType, MapType, NullableType, Primitive, RecordType, Type,
    TypeVariable, format_type, prune,
)


def validate_runtime_value(value: Any, expected: Type, context: str = "value") -> None:
    """Prüft insbesondere untypisierte Werte aus externen Funktionen."""
    expected = prune(expected)
    valid = True
    if isinstance(expected, Primitive):
        if expected.name == "Bool":
            valid = type(value) is bool
        elif expected.name == "Int":
            valid = type(value) is int
        elif expected.name == "Float":
            valid = type(value) is float
        elif expected.name == "Null":
            valid = value is None
        elif expected.name in {"String", "Html::web", "View::web"}:
            valid = isinstance(value, str)
    elif isinstance(expected, NullableType):
        if value is None:
            return
        validate_runtime_value(value, expected.inner, context)
        return
    elif isinstance(expected, ListType):
        valid = isinstance(value, list)
        if valid:
            for index, item in enumerate(value):
                validate_runtime_value(item, expected.element, f"{context}[{index}]")
    elif isinstance(expected, MapType):
        valid = isinstance(value, dict)
        if valid:
            for key, item in value.items():
                validate_runtime_value(key, expected.key, f"{context}.key")
                validate_runtime_value(item, expected.value, f"{context}[{key!r}]")
    elif isinstance(expected, RecordType):
        valid = isinstance(value, dict)
        if valid:
            for name, field_type in expected.fields.items():
                if name not in value:
                    raise LangRuntimeError(f"{context}: erforderliches Feld {name!r} fehlt")
                validate_runtime_value(value[name], field_type, f"{context}.{name}")
    elif isinstance(expected, FunctionType):
        valid = callable(value)
    elif isinstance(expected, TypeVariable):  # defensiv; der Checker lehnt dies vorher ab
        valid = True
    if not valid:
        raise LangRuntimeError(
            f"{context}: Laufzeitwert passt nicht zu {format_type(expected)}"
        )
