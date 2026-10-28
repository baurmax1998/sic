"""Öffentliche Fassade des modularen SIC-Parsers."""

from .ast import Program
from .parsing import Parser


def parse(source: str) -> Program:
    return Parser(source).parse_program()


__all__ = ["Parser", "parse"]
