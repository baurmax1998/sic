"""Muster, Postfixausdrücke und Aufrufargumente."""
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



class PostfixParserMixin:
    def parse_pattern(self):
        token = self.current
        if token.kind == "NAME" and token.value == "null":
            self.advance()
            return NullPattern()
        if token.kind == "NAME" and token.value in {"true", "false"}:
            self.advance()
            return LiteralPattern(token.value == "true")
        if token.kind == "INT":
            self.advance()
            return LiteralPattern(int(token.value))
        if token.kind == "FLOAT":
            self.advance()
            return LiteralPattern(float(token.value))
        if token.kind == "STRING":
            self.advance()
            return LiteralPattern(token.value)
        if token.kind == "NAME":
            self.advance()
            return WildcardPattern() if token.value == "_" else BindingPattern(token.value)
        if self.allow_incomplete and token.kind == "EOF":
            raise LangIncompleteError("ein match-Muster")
        raise LangSyntaxError("Ungültiges match-Muster", token.offset)

    def parse_postfix(self, value: Expr) -> Expr:
        while True:
            if self.match("("):
                arguments = self.parse_arguments_after_open()
                value = Call(value, arguments)
            elif self.match("["):
                index = self.parse_expression()
                self.expect("]")
                value = Index(value, index)
            elif self.match("."):
                name = self.expect("NAME").value
                if self.match("("):
                    value = MethodCall(value, name, self.parse_arguments_after_open())
                else:
                    value = Field(value, name)
            elif self.match("SAFE_DOT"):
                name = self.expect("NAME").value
                if self.match("("):
                    value = SafeMethodCall(value, name, self.parse_arguments_after_open())
                else:
                    value = SafeField(value, name)
            elif self.allow_incomplete and self.current.kind == "?":
                raise LangIncompleteError("'??' oder '?.'")
            elif self.match(":"):
                # Typannotationen sind Postfix-Ausdrücke. Dadurch funktionieren
                # Ketten wie `customers: List<Customer>.map(...)` ohne Klammern.
                value = Annotation(value, self.parse_type())
            else:
                return value

    def parse_arguments_after_open(self) -> tuple[Expr | NamedArgument, ...]:
        arguments: list[Expr | NamedArgument] = []
        if not self.match(")"):
            while True:
                # `name: wert` ist ein benanntes Aufrufargument. Eine mit einem
                # Großbuchstaben beginnende rechte Seite bleibt zur Kompatibilität
                # eine Typannotation (`orders: List<Order>`).
                if (
                    self.current.kind == "NAME"
                    and self.index + 2 < len(self.tokens)
                    and self.tokens[self.index + 1].kind == ":"
                    and not (
                        self.tokens[self.index + 2].kind == "NAME"
                        and self.tokens[self.index + 2].value[:1].isupper()
                    )
                ):
                    name = self.advance().value
                    self.advance()
                    arguments.append(NamedArgument(name, self.parse_expression()))
                else:
                    arguments.append(self.parse_expression())
                if self.match(")"):
                    break
                self.expect(",")
        return tuple(arguments)
