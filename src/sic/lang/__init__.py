"""Parser, Typprüfung und Laufzeit der zielorientierten Sprache."""
from .ast import Program
from .checker import CheckedProgram, TypeChecker, check
from .constraint import LangConstraint
from .dependencies import (
    LangDefinitionOrderError, LangDependencyError, check_definition_order,
    check_dependency_cycles, dependency_graph,
)
from .effects import EffectMessage, EffectSpec, EffectSubscription
from .errors import (
    LangCalculationError, LangError, LangIncompleteError, LangNameError, LangRuntimeError,
    LangSyntaxError, LangTypeError,
)
from .incremental import LangPrefixState, PrefixCheck, PrefixStatus, check_prefix
from .iterative import IncrementalCompiler, SemanticSnapshot
from .parser import Parser, parse
from .registry import ExternalFunction, ModuleRegistry
from .runtime import ExecutionResult, Evaluator, execute
from .stdlib import standard_registry
from .types import (
    BOOL, FLOAT, INT, NULL, STRING, FunctionType, ListType, MapType,
    NullableType, RecordType, format_type,
)


def compile_program(source: str, registry: ModuleRegistry | None = None) -> CheckedProgram:
    """Quelltext parsen und vollständig typprüfen."""
    active_registry = registry if registry is not None else standard_registry()
    return check(parse(source), active_registry)


def run(
    source: str, registry: ModuleRegistry | None = None,
    arguments: dict[str, object] | None = None,
) -> ExecutionResult:
    """Quelltext prüfen und anschließend sein Ziel mit optionalen Eingaben auswerten."""
    active_registry = registry if registry is not None else standard_registry()
    checked = compile_program(source, active_registry)
    return execute(checked, active_registry, arguments)


__all__ = [
    "BOOL", "FLOAT", "INT", "NULL", "STRING", "CheckedProgram", "Evaluator", "ExecutionResult",
    "EffectMessage", "EffectSpec", "EffectSubscription",
    "ExternalFunction", "FunctionType", "LangDefinitionOrderError",
    "LangDependencyError", "LangCalculationError", "LangError",
    "LangIncompleteError", "LangConstraint", "LangNameError", "LangPrefixState",
    "IncrementalCompiler", "SemanticSnapshot",
    "LangRuntimeError", "LangSyntaxError",
    "LangTypeError", "ListType", "MapType", "ModuleRegistry", "NullableType",
    "Parser", "PrefixCheck",
    "PrefixStatus", "Program", "RecordType", "TypeChecker", "check",
    "check_definition_order", "check_dependency_cycles", "check_prefix",
    "compile_program", "dependency_graph",
    "execute", "format_type", "parse", "run", "standard_registry",
]
