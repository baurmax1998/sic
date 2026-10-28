"""Öffentlicher Einstieg in die SIC-Ausführung."""
from __future__ import annotations
from typing import Any
from ..checker import CheckedProgram
from ..registry import ModuleRegistry
from .evaluator import Evaluator
from .models import ExecutionResult


def execute(
    checked: CheckedProgram, registry: ModuleRegistry | None = None,
    arguments: dict[str, Any] | None = None,
) -> ExecutionResult:
    return Evaluator(checked, registry, arguments).run()
