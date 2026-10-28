"""Modulare statische Typprüfung der SIC-Sprache."""

from .base import TypeCheckerBase
from .expressions import ExpressionInferenceMixin
from .models import CaptureInfo, CheckedProgram
from .operations import OperationInferenceMixin


class TypeChecker(
    ExpressionInferenceMixin,
    OperationInferenceMixin,
    TypeCheckerBase,
):
    """Führt Programm-, Ausdrucks- und Operationsprüfung zusammen."""


__all__ = ["CaptureInfo", "CheckedProgram", "TypeChecker"]
