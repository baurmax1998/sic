"""Öffentliche Fassade der modularen SIC-Laufzeit."""

from .execution import Evaluator, ExecutionResult, execute, validate_runtime_value

__all__ = ["Evaluator", "ExecutionResult", "execute", "validate_runtime_value"]
