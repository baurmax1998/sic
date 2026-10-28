"""Inkrementeller Compilerzustand aus Syntax, Namen und Typprüfung."""
from __future__ import annotations
from dataclasses import dataclass
import re

from .ast import Program
from .checker import CheckedProgram, check
from .dependencies import (
    LangDefinitionOrderError, LangDependencyError, expression_names,
)
from .errors import LangError, LangTypeError
from .incremental import LangPrefixState, PrefixStatus, check_prefix
from .registry import ModuleRegistry


@dataclass(frozen=True)
class SemanticSnapshot:
    program: Program | None
    checked: CheckedProgram | None
    required_names: frozenset[str]
    error: LangError | None

    @property
    def complete(self) -> bool:
        return self.checked is not None


def analyze_semantics(program: Program | None, registry: ModuleRegistry) -> SemanticSnapshot:
    if program is None:
        return SemanticSnapshot(None, None, frozenset(), None)
    defined = {binding.name for binding in program.bindings}
    required: set[str] = set()
    for binding in program.bindings:
        required.update(expression_names(binding.value))
    required.difference_update(defined)
    try:
        checked = check(program, registry)
    except LangError as exc:
        return SemanticSnapshot(program, None, frozenset(required), exc)
    # Der normale Compiler akzeptiert freie Namen als Aufrufparameter. Bei der
    # tokenweisen Erzeugung bleiben sie dennoch offen, damit ein in sich
    # geschlossenes Programm weiterhin durch nachfolgende Lets erzeugbar ist.
    if required:
        return SemanticSnapshot(program, None, frozenset(required), None)
    return SemanticSnapshot(program, checked, frozenset(), None)


class IncrementalCompiler:
    """Hält den Compilerzustand synchron zur tokenweisen Eingabe.

    Definitive semantische Fehler (Definitionsreihenfolge, Zyklen und redundante
    Annotationen) werden bereits als ungültige Kandidaten behandelt. Unbekannte
    Namen bleiben als offene Anforderungen erhalten und dürfen später durch
    ``let`` aufgelöst werden.
    """

    def __init__(self, registry: ModuleRegistry, source: str = ""):
        self.registry = registry
        self.state = LangPrefixState(source)
        self.snapshot = analyze_semantics(self.state.program, registry)
        self._semantic_source = source if self.state.program is not None else ""

    @property
    def source(self) -> str:
        return self.state.source

    @property
    def required_names(self) -> frozenset[str]:
        return self.snapshot.required_names

    @property
    def checked_program(self) -> CheckedProgram | None:
        return self.snapshot.checked

    def is_complete(self) -> bool:
        return self.snapshot.complete

    def can_accept(self, fragment: str) -> bool:
        candidate_source = self.source + fragment
        if not self._definition_prefix_allowed(candidate_source):
            return False
        candidate = check_prefix(candidate_source)
        if candidate.status is PrefixStatus.INVALID:
            return False
        if candidate.program is None:
            return True
        semantic = analyze_semantics(candidate.program, self.registry)
        error = semantic.error
        if isinstance(error, (LangDefinitionOrderError, LangDependencyError)):
            return False
        if isinstance(error, LangTypeError) and "Redundante Typannotation" in str(error):
            return False
        # Name- und Typanforderungen können durch Fortsetzung noch aufgelöst
        # bzw. durch einen nachfolgenden Operator weiter spezialisiert werden.
        return True

    def accept(self, fragment: str) -> PrefixStatus:
        if not self.can_accept(fragment):
            raise LangTypeError("Fragment verletzt den aktuellen semantischen Compilerzustand")
        status = self.state.accept(fragment)
        if self.state.program is not None:
            self.snapshot = analyze_semantics(self.state.program, self.registry)
            self._semantic_source = self.source
        return status

    def _definition_prefix_allowed(self, candidate_source: str) -> bool:
        if not self._semantic_source or not candidate_source.startswith(self._semantic_source):
            return True
        tail = candidate_source[len(self._semantic_source):].lstrip()
        if not tail:
            return True
        if "let".startswith(tail):
            return bool(self.required_names)
        if not tail.startswith("let"):
            return True
        remainder = tail[3:]
        if remainder and not remainder[0].isspace():
            return True  # beispielsweise Fortsetzung eines Identifiers
        name_match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)?", remainder)
        name_prefix = (name_match.group(1) if name_match else None) or ""
        if not self.required_names:
            return False
        return any(name.startswith(name_prefix) for name in self.required_names)

    def reset(self, source: str = "") -> None:
        self.state = LangPrefixState(source)
        self.snapshot = analyze_semantics(self.state.program, self.registry)
        self._semantic_source = source if self.state.program is not None else ""
