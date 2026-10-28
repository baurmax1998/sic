"""Kleiner, positionsbewusster Lexer."""
from __future__ import annotations
from dataclasses import dataclass
import json
import re
from .errors import LangSyntaxError


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    offset: int


_PATTERN = re.compile(
    r"(?P<SPACE>\s+)|(?P<COMMENT>\#[^\n]*)|"
    r"(?P<STRING>\"(?:\\.|[^\"\\])*\")|(?P<FLOAT>\d+\.\d+)|(?P<INT>\d+)|"
    r"(?P<ARROW>=>)|(?P<ORIGIN>::)|(?P<SAFE_DOT>\?\.)|(?P<OP>==|!=|<=|>=|\?\?|[+*/%\-<>])|"
    r"(?P<PUNCT>[(){}\[\],:.=?])|(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)"
)


def lex(source: str, allow_incomplete: bool = False) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    while position < len(source):
        # String-Builder werden bewusst vor dem regulären String-Muster
        # erkannt: Ihr Inhalt darf Zeilenumbrüche und einzelne Anführungszeichen
        # enthalten und wird erst im Parser in Text und `{...}`-Ausdrücke zerlegt.
        if source.startswith('\"\"\"', position):
            end = source.find('\"\"\"', position + 3)
            if end < 0:
                if allow_incomplete:
                    tokens.append(Token("PARTIAL_STRING_BUILDER", source[position:], position))
                    position = len(source)
                    break
                raise LangSyntaxError(
                    "Nicht geschlossener String-Builder", position, len(source)
                )
            tokens.append(Token("STRING_BUILDER", source[position + 3:end], position))
            position = end + 3
            continue
        # `\"\"` kann während inkrementeller Eingabe noch der Anfang eines
        # Triple-Quote-Literals sein und darf daher nicht als leerer String plus
        # unvollständiger Folgestring verworfen werden.
        if allow_incomplete and source[position:] == '\"\"':
            tokens.append(Token("PARTIAL_STRING_BUILDER", source[position:], position))
            position = len(source)
            break
        match = _PATTERN.match(source, position)
        if not match:
            remainder = source[position:]
            if allow_incomplete and source[position] == '"':
                # Ein noch nicht geschlossenes Stringliteral ist während der
                # inkrementellen Eingabe ein gültiges Präfix.
                tokens.append(Token("PARTIAL_STRING", remainder, position))
                position = len(source)
                break
            if allow_incomplete and remainder == "!":
                tokens.append(Token("PARTIAL_OP", remainder, position))
                position = len(source)
                break
            raise LangSyntaxError(
                f"Unerwartetes Zeichen {source[position]!r}", position, position + 1
            )
        kind = match.lastgroup or ""
        value = match.group()
        if kind not in {"SPACE", "COMMENT"}:
            if kind == "STRING":
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise LangSyntaxError("Ungültiger String", position, match.end()) from exc
            elif kind == "PUNCT":
                kind = value
            tokens.append(Token(kind, value, position))
        position = match.end()
    tokens.append(Token("EOF", "", len(source)))
    return tokens
