"""Editorfreundliche lexikalische und semantische Quelltextinformationen."""
from __future__ import annotations

from typing import Any

from ..checker import check
from ..errors import LangError
from ..lexer import Token, lex
from ..parser import parse


_KEYWORDS = {
    "goal", "let", "var", "effect", "emit", "on", "void", "ignore",
    "if", "then", "else", "match", "in", "err",
}
_WORD_OPERATORS = {"and", "or", "not"}
_CONSTANTS = {"true", "false", "null"}
_BUILTIN_TYPES = {"Bool", "Int", "Float", "String", "List", "Map"}


def _previous(tokens: list[Token], index: int) -> Token | None:
    index -= 1
    while index >= 0 and tokens[index].kind in {"SPACE", "COMMENT"}:
        return tokens[index] if tokens[index].kind == "COMMENT" else None
    return tokens[index] if index >= 0 else None


def _next(tokens: list[Token], index: int) -> Token | None:
    index += 1
    while index < len(tokens) and tokens[index].kind == "SPACE":
        index += 1
    return tokens[index] if index < len(tokens) else None


def _token_type(tokens: list[Token], index: int) -> tuple[str, tuple[str, ...]]:
    token = tokens[index]
    if token.kind == "COMMENT":
        return "comment", ()
    if token.kind in {
        "STRING", "STRING_BUILDER", "PARTIAL_STRING", "PARTIAL_STRING_BUILDER",
        "INVALID_STRING",
    }:
        invalid = token.kind.startswith("PARTIAL") or token.kind == "INVALID_STRING"
        return "string", ("incomplete",) if invalid else ()
    if token.kind in {"INT", "FLOAT"}:
        return "number", ()
    if token.kind == "INVALID":
        return "invalid", ()
    if token.kind in {"OP", "ARROW", "ORIGIN", "SAFE_DOT", "="}:
        return "operator", ()
    if token.kind in {"(", ")", "{", "}", "[", "]", ",", ":", ".", "?"}:
        return "punctuation", ()
    if token.kind != "NAME":
        return "text", ()

    value = token.value
    previous = _previous(tokens, index)
    following = _next(tokens, index)
    if value in _KEYWORDS:
        return "keyword", ()
    if value in _WORD_OPERATORS:
        return "operator", ()
    if value in _CONSTANTS:
        return "constant", ()
    if value in _BUILTIN_TYPES:
        return "type", ("builtin",)
    if previous and previous.kind == "NAME" and previous.value in {"goal", "let", "var"}:
        return "variable", ("declaration", "mutable") if previous.value == "var" else ("declaration",)
    if previous and previous.kind == "NAME" and previous.value == "effect":
        return "effect", ("declaration",)
    if previous and previous.kind in {".", "SAFE_DOT"}:
        return ("method" if following and following.kind == "(" else "property"), ()
    if previous and previous.kind == "ORIGIN":
        return "namespace", ()
    if following and following.kind == "ARROW":
        return "parameter", ("declaration",)
    if following and following.kind == "(":
        return "function", ()
    if value[:1].isupper():
        return "type", ()
    return "variable", ()


def analyze_source(source: str, registry: Any | None = None) -> dict[str, Any]:
    """Liefert stabile Offsets für Highlighting, Diagnosen und Verwendungen."""
    tokens = lex(
        source, allow_incomplete=True, include_trivia=True, recover=True,
    )
    public_tokens: list[dict[str, Any]] = []
    occurrences: dict[str, list[dict[str, int]]] = {}
    for index, token in enumerate(tokens):
        if token.kind in {"SPACE", "EOF"}:
            continue
        type_, modifiers = _token_type(tokens, index)
        item: dict[str, Any] = {
            "start": token.offset,
            "end": token.end,
            "type": type_,
        }
        if modifiers:
            item["modifiers"] = list(modifiers)
        if token.kind == "NAME" and type_ in {
            "variable", "parameter", "function", "method", "effect",
        }:
            item["symbol"] = token.value
            occurrences.setdefault(token.value, []).append({
                "start": token.offset, "end": token.end,
            })
        public_tokens.append(item)

    diagnostics: list[dict[str, Any]] = []
    try:
        check(parse(source), registry) if registry is not None else None
    except LangError as error:
        start = error.offset if error.offset is not None else len(source)
        diagnostics.append({
            "start": start,
            "end": error.end if error.end is not None else min(len(source), start + 1),
            "severity": "error",
            "message": error.message,
        })

    symbols = [
        {"name": name, "occurrences": ranges}
        for name, ranges in occurrences.items()
    ]
    completions: list[dict[str, str]] = []
    if registry is not None:
        seen: set[str] = set()
        for path in registry.paths():
            symbol, origin = path[0], path[1:]
            label = "::".join(path)
            if label in seen:
                continue
            seen.add(label)
            if registry.has_calculation(symbol, origin):
                kind, insert_text = "function", label + "()"
            elif registry.has_function(symbol, origin):
                kind, insert_text = "function", label + "()"
            elif registry.has_type(symbol, origin):
                kind, insert_text = "type", label
            elif registry.has_effect(symbol, origin):
                kind, insert_text = "effect", label
            else:  # pragma: no cover - paths() besteht nur aus diesen Registern
                continue
            completions.append({
                "label": label, "insertText": insert_text, "kind": kind,
            })
    return {
        "tokens": public_tokens,
        "diagnostics": diagnostics,
        "symbols": symbols,
        "completions": completions,
    }


__all__ = ["analyze_source"]
