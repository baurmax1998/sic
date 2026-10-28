"""Tokensteuerung sowie Programm-, Typ- und Präzedenzparser."""
from __future__ import annotations
from dataclasses import replace

from ..ast import (
    Annotation, Binary, Binding, BindingPattern, Call, CapturedCall, ErrorExpr,
    Expr, Field, IfExpr, Index, Lambda, ListExpr, Literal, LiteralPattern,
    EffectDeclaration, EffectSuppression, EmitDeclaration, ListenerDeclaration,
    LocalLet, MapExpr, MatchCase, MatchExpr, MethodCall, Name, NamedArgument,
    NullPattern, OutputAccess, Program, RecordExpr, SafeField, SafeMethodCall,
    SourceSpan, StringBuilder, TypeRef, Unary, WildcardPattern,
)
from ..errors import LangIncompleteError, LangSyntaxError
from ..lexer import Token, lex

_PRECEDENCE = {"??": 0, "or": 1, "and": 2, "==": 3, "!=": 3, "<": 3, "<=": 3,
               ">": 3, ">=": 3, "+": 4, "-": 4, "*": 5, "/": 5, "%": 5}

class ParserCore:
    def __init__(self, source: str, allow_incomplete: bool = False):
        self.allow_incomplete = allow_incomplete
        self.tokens = lex(source, allow_incomplete=allow_incomplete)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def match(self, kind: str, value: str | None = None) -> bool:
        if self.current.kind == kind and (value is None or self.current.value == value):
            self.advance()
            return True
        return False

    def expect(self, kind: str, value: str | None = None) -> Token:
        if not self.match(kind, value):
            wanted = value if value is not None else kind
            if self.allow_incomplete and self.current.kind == "EOF":
                raise LangIncompleteError(repr(wanted))
            if (
                self.allow_incomplete
                and value is not None
                and self.current.kind == kind
                and value.startswith(self.current.value)
                and self.index + 1 < len(self.tokens)
                and self.tokens[self.index + 1].kind == "EOF"
            ):
                raise LangIncompleteError(repr(value))
            raise LangSyntaxError(
                f"Erwartet {wanted!r}, gefunden {self.current.value or self.current.kind!r}",
                self.current.offset,
                self.current.offset + max(1, len(self.current.value)),
            )
        return self.tokens[self.index - 1]

    def parse_program(self) -> Program:
        bindings: list[Binding] = []
        effects: list[EffectDeclaration] = []
        emits: list[EmitDeclaration] = []
        listeners: list[ListenerDeclaration] = []
        voids: list[EffectSuppression] = []
        ignores: list[EffectSuppression] = []
        while self.current.kind != "EOF":
            binding_start = self.current.offset
            keyword = self.expect("NAME").value
            if keyword == "effect":
                name = self.expect("NAME").value
                self.expect(":")
                effects.append(EffectDeclaration(
                    name, self.parse_type(), SourceSpan(binding_start, self.current.offset)
                ))
                continue
            if keyword in {"emit", "on", "void", "ignore"}:
                if keyword == "emit":
                    name = self.expect("NAME").value
                    self.expect(":")
                    effect = self.parse_qualified_name()
                    self.expect("=")
                    payload = self.parse_expression()
                    emits.append(EmitDeclaration(
                        name, effect, payload, SourceSpan(binding_start, self.current.offset)
                    ))
                else:
                    effect = self.parse_qualified_name()
                    span = SourceSpan(binding_start, self.current.offset)
                    if keyword == "on":
                        filter_ = self.parse_expression() if self.match("=") else None
                        listeners.append(ListenerDeclaration(effect, filter_, span))
                    else:
                        (voids if keyword == "void" else ignores).append(
                            EffectSuppression(effect, span)
                        )
                continue
            if keyword not in {"goal", "let"}:
                if (
                    self.allow_incomplete
                    and any(candidate.startswith(keyword) for candidate in ("goal", "let"))
                    and self.current.kind == "EOF"
                ):
                    raise LangIncompleteError("'goal' oder 'let'")
                # Mehrfachbindungen sind absichtlich die einzige Definition ohne
                # Schlüsselwort: `wert, fehler = berechnung(...)`.
                outputs = [keyword]
                if not self.match(","):
                    token = self.tokens[self.index - 1]
                    raise LangSyntaxError(
                        f"Erwartet eine SIC-Deklaration oder Mehrfachbindung, gefunden {keyword!r}",
                        token.offset, token.offset + len(token.value),
                    )
                outputs.append(self.expect("NAME").value)
                while self.match(","):
                    outputs.append(self.expect("NAME").value)
                self.expect("=")
                call = self.parse_expression()
                if not isinstance(call, Call):
                    raise LangSyntaxError("Mehrfachbindung benötigt einen Aufruf", binding_start)
                captured = CapturedCall(call, tuple(outputs))
                span = SourceSpan(binding_start, self.current.offset)
                bindings.extend(Binding(name, OutputAccess(captured, name), span=span) for name in outputs)
                continue
            name = self.expect("NAME").value
            annotation = None
            if self.match(":"):
                annotation = self.parse_type()
            self.expect("=")
            value = self.parse_expression()
            bindings.append(Binding(
                name, value, annotation, keyword == "goal",
                span=SourceSpan(binding_start, self.current.offset),
            ))
        goals = sum(binding.is_goal for binding in bindings)
        if goals != 1 and not (goals == 0 and not bindings and effects):
            if self.allow_incomplete and goals == 0:
                raise LangIncompleteError("eine goal-Definition")
            raise LangSyntaxError("Ein Programm muss genau ein goal enthalten")
        names = [binding.name for binding in bindings]
        duplicate = next((name for name in names if names.count(name) > 1), None)
        if duplicate:
            raise LangSyntaxError(f"Name {duplicate!r} wird mehrfach definiert")
        effect_names = [effect.name for effect in effects]
        duplicate_effect = next(
            (name for name in effect_names if effect_names.count(name) > 1), None
        )
        if duplicate_effect:
            raise LangSyntaxError(f"Effekt {duplicate_effect!r} wird mehrfach definiert")
        output_names = [emit.name for emit in emits]
        duplicate_output = next(
            (name for name in output_names if output_names.count(name) > 1), None
        )
        if duplicate_output:
            raise LangSyntaxError(f"Effekt-Ausgang {duplicate_output!r} wird mehrfach definiert")
        return Program(
            tuple(bindings), tuple(effects), tuple(emits), tuple(listeners),
            tuple(voids), tuple(ignores),
        )

    def parse_qualified_name(self) -> Name:
        name = self.expect("NAME").value
        origin: list[str] = []
        while self.match("ORIGIN"):
            origin.append(self.expect("NAME").value)
        return Name(name, tuple(origin))

    def parse_type(self) -> TypeRef:
        name = self.expect("NAME").value
        origin: list[str] = []
        while self.match("ORIGIN"):
            origin.append(self.expect("NAME").value)
        arguments: list[TypeRef] = []
        if self.match("OP", "<"):
            arguments.append(self.parse_type())
            while self.match(","):
                arguments.append(self.parse_type())
            self.expect("OP", ">")
        expected_arguments = {"List": 1, "Map": 2}.get(name, 0) if not origin else 0
        if len(arguments) != expected_arguments:
            if self.allow_incomplete and not arguments and expected_arguments and self.current.kind == "EOF":
                raise LangIncompleteError("Typparameter")
            raise LangSyntaxError(
                f"{name} benötigt {expected_arguments} Typparameter, erhalten: {len(arguments)}"
            )
        nullable = self.match("?")
        return TypeRef(name, tuple(arguments), nullable, tuple(origin))

    def parse_expression(self, minimum: int = 0) -> Expr:
        start = self.current.offset
        left = self.parse_prefix()
        left = self.parse_postfix(left)
        while True:
            if self.allow_incomplete and self.current.kind == "PARTIAL_OP":
                raise LangIncompleteError("'!='")
            if self.allow_incomplete and self.current.kind == "=":
                raise LangIncompleteError("'=='")
            operator = self.current.value
            precedence = _PRECEDENCE.get(operator, -1)
            if precedence < minimum:
                break
            self.advance()
            right = self.parse_expression(precedence + 1)
            left = Binary(operator, left, right)
        return replace(left, span=SourceSpan(start, self.current.offset))
