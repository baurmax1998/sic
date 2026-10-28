"""Öffentliche Fassade der modularen statischen Typprüfung."""
from __future__ import annotations

from . import ast
from .checking import CaptureInfo, CheckedProgram, TypeChecker
from .registry import ModuleRegistry


def check(program: ast.Program, registry: ModuleRegistry | None = None) -> CheckedProgram:
    return TypeChecker(registry).check(program)


__all__ = ["CaptureInfo", "CheckedProgram", "TypeChecker", "check"]
