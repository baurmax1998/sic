"""Inkrementelle syntaktische Prüfung von Sprachpräfixen.

Die Klasse arbeitet absichtlich mit Textfragmenten. Damit kann später jedes
Tokenizer-Token über ``can_accept`` geprüft werden, ohne den Parser an einen
bestimmten LLM-Tokenizer zu koppeln.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .ast import Program
from .errors import LangIncompleteError, LangSyntaxError
from .parser import Parser


class PrefixStatus(str, Enum):
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"
    INVALID = "invalid"


@dataclass(frozen=True)
class PrefixCheck:
    status: PrefixStatus
    program: Program | None = None
    expected: str | None = None
    error: LangSyntaxError | None = None


def check_prefix(source: str) -> PrefixCheck:
    """Klassifiziert Quelltext als gültiges Präfix, Programm oder Fehler."""
    try:
        program = Parser(source, allow_incomplete=True).parse_program()
    except LangIncompleteError as exc:
        return PrefixCheck(PrefixStatus.INCOMPLETE, expected=exc.expected)
    except LangSyntaxError as exc:
        return PrefixCheck(PrefixStatus.INVALID, error=exc)
    return PrefixCheck(PrefixStatus.COMPLETE, program=program)


class LangPrefixState:
    """Unveränderliche Parserlogik hinter einem veränderlichen Textpuffer."""

    def __init__(self, source: str = ""):
        self._source = ""
        self._check = check_prefix("")
        if source:
            self.accept(source)

    @property
    def source(self) -> str:
        return self._source

    @property
    def status(self) -> PrefixStatus:
        return self._check.status

    @property
    def expected(self) -> str | None:
        return self._check.expected

    @property
    def program(self) -> Program | None:
        return self._check.program

    def is_complete(self) -> bool:
        return self.status is PrefixStatus.COMPLETE

    def can_accept(self, fragment: str) -> bool:
        """Prüft ein Fragment, ohne den Zustand zu verändern."""
        return check_prefix(self._source + fragment).status is not PrefixStatus.INVALID

    def accept(self, fragment: str) -> PrefixStatus:
        """Hängt ein Fragment an oder wirft bei einem ungültigen Präfix."""
        candidate = self._source + fragment
        checked = check_prefix(candidate)
        if checked.status is PrefixStatus.INVALID:
            assert checked.error is not None
            raise checked.error
        self._source = candidate
        self._check = checked
        return checked.status

    def allowed_fragments(self, fragments: Iterable[str]) -> list[str]:
        """Filtert Kandidaten, wie es später die LLM-Tokenmaske benötigt."""
        return [fragment for fragment in fragments if self.can_accept(fragment)]

    def copy(self) -> LangPrefixState:
        clone = LangPrefixState()
        clone._source = self._source
        clone._check = self._check
        return clone
