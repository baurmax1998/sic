"""Präfixausdrücke, Literale und Kontrollausdrücke."""
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



class PrefixParserMixin:
    def parse_prefix(self) -> Expr:
        token = self.current
        if token.kind == "FLOAT":
            self.advance()
            return Literal(float(token.value))
        if token.kind == "INT":
            self.advance()
            return Literal(int(token.value))
        if token.kind == "STRING":
            self.advance()
            return Literal(token.value)
        if token.kind == "STRING_BUILDER":
            self.advance()
            return self.parse_string_builder(token)
        if token.kind == "NAME" and token.value in {"true", "false", "null"}:
            self.advance()
            if token.value == "null":
                return Literal(None)
            return Literal(token.value == "true")
        if token.kind == "NAME" and token.value == "err":
            self.advance()
            name = self.expect("NAME").value
            payload = self.parse_expression() if self.match("=") else None
            return ErrorExpr(name, payload)
        if token.kind == "NAME" and token.value == "let":
            self.advance()
            name = self.expect("NAME").value
            annotation = self.parse_type() if self.match(":") else None
            self.expect("=")
            value = self.parse_expression()
            self.expect("NAME", "in")
            return LocalLet(name, value, self.parse_expression(), annotation)
        if token.kind == "NAME" and token.value == "match":
            self.advance()
            value = self.parse_expression()
            self.expect("{")
            cases: list[MatchCase] = []
            while not self.match("}"):
                pattern = self.parse_pattern()
                self.expect("ARROW")
                cases.append(MatchCase(pattern, self.parse_expression()))
                if self.match("}"):
                    break
                self.match(",")
            if not cases:
                raise LangSyntaxError("match benötigt mindestens einen Fall", token.offset)
            return MatchExpr(value, tuple(cases))
        if token.kind == "NAME" and token.value == "if":
            self.advance()
            condition = self.parse_expression()
            self.expect("NAME", "then")
            then_branch = self.parse_expression()
            self.expect("NAME", "else")
            return IfExpr(condition, then_branch, self.parse_expression())
        if token.kind == "NAME" and token.value == "not":
            self.advance()
            return Unary("not", self.parse_expression(6))
        if token.kind == "OP" and token.value == "-":
            self.advance()
            return Unary("-", self.parse_expression(6))
        if token.kind == "NAME":
            self.advance()
            if self.match("ARROW"):
                return Lambda((token.value,), self.parse_expression())
            if (
                self.allow_incomplete
                and self.current.kind == "="
                and self.index + 1 < len(self.tokens)
                and self.tokens[self.index + 1].kind == "EOF"
            ):
                raise LangIncompleteError("'=>'")
            origin: list[str] = []
            while self.match("ORIGIN"):
                origin.append(self.expect("NAME").value)
            return Name(token.value, tuple(origin))
        if self.match("["):
            items: list[Expr] = []
            if not self.match("]"):
                while True:
                    items.append(self.parse_expression())
                    if self.match("]"):
                        break
                    self.expect(",")
            return ListExpr(tuple(items))
        if self.match("{"):
            if self.current.kind == "STRING":
                entries: list[tuple[Expr, Expr]] = []
                while True:
                    key = Literal(self.advance().value)
                    self.expect(":")
                    entries.append((key, self.parse_expression()))
                    if self.match("}"):
                        break
                    self.expect(",")
                return MapExpr(tuple(entries))
            fields: list[tuple[str, Expr]] = []
            if not self.match("}"):
                while True:
                    name = self.expect("NAME").value
                    self.expect(":")
                    fields.append((name, self.parse_expression()))
                    if self.match("}"):
                        break
                    self.expect(",")
            return RecordExpr(tuple(fields))
        if self.match("("):
            # Parameterlisten von Lambdas haben nur Namen und enden direkt vor =>.
            saved = self.index
            parameters: list[str] = []
            if self.current.kind == "NAME":
                parameters.append(self.advance().value)
                while self.match(","):
                    parameters.append(self.expect("NAME").value)
                if self.match(")") and self.match("ARROW"):
                    return Lambda(tuple(parameters), self.parse_expression())
            self.index = saved
            value = self.parse_expression()
            if self.match(":"):
                value = Annotation(value, self.parse_type())
            self.expect(")")
            return value
        if self.allow_incomplete and token.kind in {
            "EOF", "PARTIAL_STRING", "PARTIAL_STRING_BUILDER"
        }:
            raise LangIncompleteError("einen Ausdruck")
        raise LangSyntaxError(
            f"Ausdruck erwartet, gefunden {token.value or token.kind!r}",
            token.offset, token.offset + max(1, len(token.value)),
        )
