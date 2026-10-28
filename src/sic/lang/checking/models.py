"""Ergebnisse und Metadaten der statischen Typprüfung."""
from __future__ import annotations

from dataclasses import dataclass

from .. import ast
from ..calculation import CalculationSpec, ErrorSpec
from ..effects import EffectOutputSpec, EffectSpec
from ..registry import ExternalFunction
from ..types import RecordType, Type, format_type


@dataclass(frozen=True)
class CaptureInfo:
    spec: CalculationSpec | ExternalFunction
    caught: dict[str, ErrorSpec]
    caught_effects: dict[str, EffectOutputSpec]
    normal_outputs: dict[str, str]


@dataclass(frozen=True)
class CheckedListener:
    declaration: ast.ListenerDeclaration
    effect: EffectSpec


@dataclass(frozen=True)
class CheckedProgram:
    program: ast.Program
    bindings: dict[str, Type]
    records: dict[str, RecordType]
    inputs: dict[str, Type]
    direct_errors: dict[str, tuple[ErrorSpec, ...]]
    call_specs: dict[int, CalculationSpec]
    external_calls: dict[int, ExternalFunction]
    captures: dict[int, CaptureInfo]
    effect_outputs: tuple[EffectOutputSpec, ...]
    emit_effects: dict[str, EffectSpec]
    listeners: tuple[CheckedListener, ...]
    void_effects: frozenset[tuple[str, ...]]
    ignore_effects: frozenset[tuple[str, ...]]
    completion_dependencies: frozenset[str]

    def type_of(self, name: str) -> str:
        return format_type(self.bindings[name])
