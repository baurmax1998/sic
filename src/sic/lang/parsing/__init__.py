"""Modularer Parser der SIC-Sprache."""

from .core import ParserCore
from .postfix import PostfixParserMixin
from .prefix import PrefixParserMixin
from .strings import StringParserMixin


class Parser(
    PrefixParserMixin,
    StringParserMixin,
    PostfixParserMixin,
    ParserCore,
):
    """Kombiniert die spezialisierten Parserbestandteile."""


__all__ = ["Parser"]
