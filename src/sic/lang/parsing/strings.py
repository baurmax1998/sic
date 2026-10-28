"""Interpolierte String-Builder."""
from __future__ import annotations
from dataclasses import replace

from ..ast import (
    Annotation, Binary, Binding, BindingPattern, Call, CapturedCall, ErrorExpr,
    Expr, Field, IfExpr, Index, Lambda, ListExpr, Literal, LiteralPattern,
    LocalLet, MapExpr, MatchCase, MatchExpr, MethodCall, Name, NamedArgument,
    NullPattern, OutputAccess, Program, RecordExpr, SafeField, SafeMethodCall,
    SourceSpan, StringBuilder, TypeRef, Unary, WildcardPattern,
)
from ..errors import LangIncompleteError, LangSyntaxError
from ..lexer import Token, lex



class StringParserMixin:
    def parse_string_builder(self, token: Token) -> StringBuilder:
        """Parst Text sowie Ausdrücke in `{...}`; `{{` und `}}` sind Literale."""
        content = token.value
        parts: list[str | Expr] = []
        text: list[str] = []
        index = 0

        def flush_text() -> None:
            if text:
                value = "".join(text)
                if parts and isinstance(parts[-1], str):
                    parts[-1] += value
                else:
                    parts.append(value)
                text.clear()

        while index < len(content):
            if content.startswith("{{", index):
                text.append("{")
                index += 2
                continue
            if content.startswith("}}", index):
                text.append("}")
                index += 2
                continue
            if content[index] == "}":
                offset = token.offset + 3 + index
                raise LangSyntaxError("Einzelne '}' im String-Builder", offset, offset + 1)
            if content[index] != "{":
                text.append(content[index])
                index += 1
                continue

            flush_text()
            expression_start = index + 1
            expression_end = self.find_builder_expression_end(
                content, expression_start, token.offset + 3
            )
            source = content[expression_start:expression_end]
            if not source.strip():
                offset = token.offset + 3 + index
                raise LangSyntaxError("Leerer Ausdruck im String-Builder", offset, offset + 2)
            try:
                nested = type(self)(source)
                expression = nested.parse_expression()
                nested.expect("EOF")
            except LangSyntaxError as exc:
                if exc.offset is not None:
                    exc.offset += token.offset + 3 + expression_start
                    if exc.end is not None:
                        exc.end += token.offset + 3 + expression_start
                raise
            parts.append(expression)
            index = expression_end + 1

        flush_text()
        return StringBuilder(tuple(parts))

    @staticmethod
    def find_builder_expression_end(content: str, start: int, base_offset: int) -> int:
        depth = 0
        index = start
        while index < len(content):
            character = content[index]
            if character == '"':
                index += 1
                while index < len(content):
                    if content[index] == "\\":
                        index += 2
                    elif content[index] == '"':
                        index += 1
                        break
                    else:
                        index += 1
                continue
            if character == "{":
                depth += 1
            elif character == "}":
                if depth == 0:
                    return index
                depth -= 1
            index += 1
        raise LangSyntaxError(
            "Nicht geschlossener Ausdruck im String-Builder",
            base_offset + start - 1,
            base_offset + len(content),
        )
