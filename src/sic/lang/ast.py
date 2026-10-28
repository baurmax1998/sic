"""Abstrakter Syntaxbaum der Zielsprache."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int


@dataclass(frozen=True)
class TypeRef:
    name: str
    arguments: tuple[TypeRef, ...] = ()
    nullable: bool = False
    origin: tuple[str, ...] = ()


@dataclass(frozen=True)
class Expr:
    span: SourceSpan | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class Literal(Expr): value: Any


@dataclass(frozen=True)
class StringBuilder(Expr):
    """Mehrzeiliger String aus statischem Text und eingebetteten Ausdrücken."""
    parts: tuple[str | Expr, ...]


@dataclass(frozen=True)
class Name(Expr):
    name: str
    origin: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListExpr(Expr): items: tuple[Expr, ...]


@dataclass(frozen=True)
class RecordExpr(Expr): fields: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True)
class MapExpr(Expr): entries: tuple[tuple[Expr, Expr], ...]


@dataclass(frozen=True)
class Index(Expr):
    value: Expr
    index: Expr


@dataclass(frozen=True)
class LocalLet(Expr):
    name: str
    value: Expr
    body: Expr
    annotation: TypeRef | None = None


@dataclass(frozen=True)
class Annotation(Expr):
    value: Expr
    type_ref: TypeRef


@dataclass(frozen=True)
class Unary(Expr):
    operator: str
    operand: Expr


@dataclass(frozen=True)
class Binary(Expr):
    operator: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class IfExpr(Expr):
    condition: Expr
    then_branch: Expr
    else_branch: Expr


@dataclass(frozen=True)
class Lambda(Expr):
    parameters: tuple[str, ...]
    body: Expr


@dataclass(frozen=True)
class NamedArgument:
    name: str
    value: Expr


@dataclass(frozen=True)
class Call(Expr):
    function: Expr
    arguments: tuple[Expr | NamedArgument, ...]


@dataclass(frozen=True)
class ErrorExpr(Expr):
    name: str
    payload: Expr | None = None


@dataclass(frozen=True)
class CapturedCall:
    """Ein einmal auszuwertender Aufruf hinter einer Mehrfachbindung."""
    call: Call
    outputs: tuple[str, ...]


@dataclass(frozen=True)
class OutputAccess(Expr):
    captured: CapturedCall
    name: str


@dataclass(frozen=True)
class Field(Expr):
    value: Expr
    name: str


@dataclass(frozen=True)
class SafeField(Expr):
    value: Expr
    name: str


@dataclass(frozen=True)
class MethodCall(Expr):
    value: Expr
    name: str
    arguments: tuple[Expr, ...]


@dataclass(frozen=True)
class SafeMethodCall(Expr):
    value: Expr
    name: str
    arguments: tuple[Expr, ...]


@dataclass(frozen=True)
class Pattern: pass


@dataclass(frozen=True)
class NullPattern(Pattern): pass


@dataclass(frozen=True)
class LiteralPattern(Pattern): value: Any


@dataclass(frozen=True)
class BindingPattern(Pattern): name: str


@dataclass(frozen=True)
class WildcardPattern(Pattern): pass


@dataclass(frozen=True)
class MatchCase:
    pattern: Pattern
    body: Expr


@dataclass(frozen=True)
class MatchExpr(Expr):
    value: Expr
    cases: tuple[MatchCase, ...]


@dataclass(frozen=True)
class Binding:
    name: str
    value: Expr
    annotation: TypeRef | None = None
    is_goal: bool = False
    span: SourceSpan | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class EffectDeclaration:
    name: str
    payload: TypeRef
    span: SourceSpan | None = None


@dataclass(frozen=True)
class EmitDeclaration:
    name: str
    effect: Name
    payload: Expr
    span: SourceSpan | None = None


@dataclass(frozen=True)
class ListenerDeclaration:
    effect: Name
    filter: Expr | None = None
    span: SourceSpan | None = None


@dataclass(frozen=True)
class EffectSuppression:
    effect: Name
    span: SourceSpan | None = None


@dataclass(frozen=True)
class Program:
    bindings: tuple[Binding, ...]
    effects: tuple[EffectDeclaration, ...] = ()
    emits: tuple[EmitDeclaration, ...] = ()
    listeners: tuple[ListenerDeclaration, ...] = ()
    voids: tuple[EffectSuppression, ...] = ()
    ignores: tuple[EffectSuppression, ...] = ()

    @property
    def goal(self) -> Binding:
        goals = [binding for binding in self.bindings if binding.is_goal]
        if len(goals) != 1:
            raise ValueError("Ein Programm benötigt genau ein goal")
        return goals[0]
