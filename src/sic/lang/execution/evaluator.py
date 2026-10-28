"""Bedarfsgesteuerte Auswertung geprüfter SIC-Programme."""
from __future__ import annotations
from functools import reduce
import logging
from typing import Any, Callable
from .. import ast
from ..checker import CheckedProgram
from ..effects import EffectMessage, EffectSubscription
from ..errors import LangCalculationError, LangRuntimeError
from ..registry import ExternalFunction, ModuleRegistry
from .models import ExecutionResult
from .validation import validate_runtime_value


logger = logging.getLogger("uvicorn.error.sic.runtime")


class Evaluator:
    def __init__(
        self, checked: CheckedProgram, registry: ModuleRegistry | None = None,
        overrides: dict[str, Any] | None = None,
        identity_origin: tuple[str, ...] = (),
    ):
        self.checked = checked
        self.registry = registry or ModuleRegistry()
        self.definitions = {binding.name: binding.value for binding in checked.program.bindings}
        self.values: dict[str, Any] = {}
        self.active: set[str] = set()
        self.overrides = dict(overrides or {})
        self.identity_origin = identity_origin
        self.captured_values: dict[int, dict[str, Any]] = {}
        self.messages: list[EffectMessage] = []
        self.subscriptions: list[EffectSubscription] = []
        self._goal_finalized = False
        self.capture_actions = False

    def run(self) -> ExecutionResult:
        goal = self.checked.program.goal.name
        value = self.resolve(goal)
        return ExecutionResult(
            goal, value, tuple(self.outgoing_messages()), tuple(self.subscriptions)
        )

    def call(self, name: str, **arguments: Any) -> Any:
        """Ruft ein Goal oder Let von Python aus mit denselben Override-Regeln auf."""
        nested = Evaluator(self.checked, self.registry, arguments, self.identity_origin)
        return nested.resolve(name)

    def resolve(self, name: str) -> Any:
        if name in self.overrides:
            logger.debug("[SIC] override calculation=%s", name)
            expected = self.checked.bindings.get(name, self.checked.inputs.get(name))
            if expected is not None:
                validate_runtime_value(self.overrides[name], expected, name)
            return self.overrides[name]
        if name in self.values:
            logger.debug("[SIC] cache-hit calculation=%s", name)
            return self.values[name]
        if name in self.active:
            raise LangRuntimeError(f"Unzulässiger Abhängigkeitszyklus bei {name!r}")
        if name not in self.definitions:
            if name in self.checked.inputs:
                raise LangRuntimeError(f"Erforderliche Eingabe {name!r} wurde nicht übergeben")
            raise LangRuntimeError(f"Name {name!r} besitzt keine Definition")
        self.active.add(name)
        logger.debug(
            "[SIC] calculate-start calculation=%s origin=%s",
            name, "::".join(self.identity_origin) or "local",
        )
        try:
            value = self.evaluate(self.definitions[name], {})
            validate_runtime_value(value, self.checked.bindings[name], name)
            self.values[name] = value
            if name == self.checked.program.goal.name:
                self.finalize_goal()
            logger.debug("[SIC] calculate-finish calculation=%s", name)
            return value
        finally:
            self.active.remove(name)

    def evaluate(self, expression: ast.Expr, local: dict[str, Any]) -> Any:
        if isinstance(expression, ast.Literal): return expression.value
        if isinstance(expression, ast.StringBuilder):
            return "".join(
                part if isinstance(part, str) else self.stringify(self.evaluate(part, local))
                for part in expression.parts
            )
        if isinstance(expression, ast.Name):
            if expression.origin:
                return self.registry.resolve(expression.name, expression.origin).implementation
            return local[expression.name] if expression.name in local else self.resolve(expression.name)
        if isinstance(expression, ast.Annotation): return self.evaluate(expression.value, local)
        if isinstance(expression, ast.ErrorExpr):
            payload = self.evaluate(expression.payload, local) if expression.payload is not None else None
            identity = (*self.identity_origin, expression.name) if self.identity_origin else (expression.name,)
            raise LangCalculationError(expression.name, payload, identity)
        if isinstance(expression, ast.OutputAccess):
            key = id(expression.captured)
            if key not in self.captured_values:
                self.captured_values[key] = self.evaluate_capture(expression.captured, local)
            return self.captured_values[key][expression.name]
        if isinstance(expression, ast.ListExpr):
            return [self.evaluate(item, local) for item in expression.items]
        if isinstance(expression, ast.MapExpr):
            return {
                self.evaluate(key, local): self.evaluate(value, local)
                for key, value in expression.entries
            }
        if isinstance(expression, ast.RecordExpr):
            return {name: self.evaluate(value, local) for name, value in expression.fields}
        if isinstance(expression, ast.Unary):
            value = self.evaluate(expression.operand, local)
            return not value if expression.operator == "not" else -value
        if isinstance(expression, ast.Binary):
            if expression.operator == "and":
                return self.evaluate(expression.left, local) and self.evaluate(expression.right, local)
            if expression.operator == "or":
                return self.evaluate(expression.left, local) or self.evaluate(expression.right, local)
            if expression.operator == "??":
                left = self.evaluate(expression.left, local)
                return left if left is not None else self.evaluate(expression.right, local)
            left, right = self.evaluate(expression.left, local), self.evaluate(expression.right, local)
            operations: dict[str, Callable[[Any, Any], Any]] = {
                "+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
                "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
                "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
                ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
            }
            operations.update({
                "/": lambda a, b: a / b,
                "%": lambda a, b: a % b,
            })
            return operations[expression.operator](left, right)
        if isinstance(expression, ast.IfExpr):
            branch = expression.then_branch if self.evaluate(expression.condition, local) else expression.else_branch
            return self.evaluate(branch, local)
        if isinstance(expression, ast.MatchExpr):
            value = self.evaluate(expression.value, local)
            for case in expression.cases:
                pattern = case.pattern
                matched = False
                case_local = local
                if isinstance(pattern, ast.NullPattern):
                    matched = value is None
                elif isinstance(pattern, ast.LiteralPattern):
                    matched = value == pattern.value
                elif isinstance(pattern, ast.BindingPattern):
                    matched = True
                    case_local = {**local, pattern.name: value}
                elif isinstance(pattern, ast.WildcardPattern):
                    matched = True
                if matched:
                    return self.evaluate(case.body, case_local)
            raise LangRuntimeError("Kein match-Fall passt zum Wert")
        if isinstance(expression, ast.LocalLet):
            value = self.evaluate(expression.value, local)
            return self.evaluate(expression.body, {**local, expression.name: value})
        if isinstance(expression, ast.Index):
            try:
                return self.evaluate(expression.value, local)[self.evaluate(expression.index, local)]
            except (KeyError, IndexError) as exc:
                raise LangRuntimeError("Index oder Map-Schlüssel ist nicht vorhanden") from exc
        if isinstance(expression, ast.SafeField):
            value = self.evaluate(expression.value, local)
            if value is None:
                return None
            try:
                return value[expression.name] if isinstance(value, dict) else getattr(value, expression.name)
            except (KeyError, AttributeError) as exc:
                raise LangRuntimeError(f"Feld {expression.name!r} fehlt zur Laufzeit") from exc
        if isinstance(expression, ast.Field):
            value = self.evaluate(expression.value, local)
            try:
                return value[expression.name] if isinstance(value, dict) else getattr(value, expression.name)
            except (KeyError, AttributeError) as exc:
                raise LangRuntimeError(f"Feld {expression.name!r} fehlt zur Laufzeit") from exc
        if isinstance(expression, ast.Lambda):
            captured = dict(local)
            def function(*arguments: Any) -> Any:
                if len(arguments) != len(expression.parameters):
                    raise LangRuntimeError("Falsche Parameteranzahl")
                return self.evaluate(expression.body, {**captured, **dict(zip(expression.parameters, arguments))})
            def action_descriptor(*arguments: Any) -> Any:
                # Statische Abhängigkeiten (etwa `nextId`) werden vor dem
                # Capture berechnet; nur der eigentliche Backend-Aufruf der
                # Lambda wird anschließend als Browseraktion beschrieben.
                from ..dependencies import expression_names
                for dependency in expression_names(
                    expression.body, frozenset(expression.parameters)
                ):
                    if dependency in self.definitions:
                        self.resolve(dependency)
                previous = self.capture_actions
                self.capture_actions = True
                try:
                    return function(*arguments)
                finally:
                    self.capture_actions = previous
            function.action_descriptor = action_descriptor  # type: ignore[attr-defined]
            return function
        if isinstance(expression, ast.Call):
            external = self.checked.external_calls.get(id(expression))
            if external is not None:
                if not external.parameter_names:
                    positional = [
                        self.evaluate(argument, local)
                        for argument in expression.arguments
                        if not isinstance(argument, ast.NamedArgument)
                    ]
                    return external.implementation(*positional)
                arguments: dict[str, Any] = {}
                positional_index = 0
                for argument in expression.arguments:
                    if isinstance(argument, ast.NamedArgument):
                        name, value = argument.name, argument.value
                    else:
                        name, value = external.parameter_names[positional_index], argument
                        positional_index += 1
                    arguments[name] = self.evaluate(value, local)
                result = external.implementation(**arguments)
                for listener in external.automatic_listeners:
                    if listener.effect.identity in self.checked.ignore_effects:
                        continue
                    payload = arguments[listener.payload_parameter]
                    if listener.normalize is not None:
                        payload = listener.normalize(payload)
                    self.subscriptions.append(EffectSubscription(
                        listener.effect, payload, True, True
                    ))
                    logger.debug(
                        "[SIC] listener automatic effect=%s filter=%r",
                        "::".join(listener.effect.identity), payload,
                    )
                for output in external.effect_outputs:
                    payload = arguments[output.payload_parameter]
                    if output.normalize is not None:
                        payload = output.normalize(payload)
                    validate_runtime_value(payload, output.effect.payload, output.name)
                    self.messages.append(EffectMessage(output.effect, payload, output.name))
                    logger.info(
                        "[SIC] effect-emitted effect=%s output=%s",
                        "::".join(output.effect.identity), output.name,
                    )
                    logger.debug(
                        "[SIC] effect-payload output=%s payload=%r",
                        output.name, payload,
                    )
                return result
            spec = self.checked.call_specs.get(id(expression))
            if spec is not None:
                arguments = {
                    argument.name: self.evaluate(argument.value, local)
                    for argument in expression.arguments
                    if isinstance(argument, ast.NamedArgument)
                }
                if self.capture_actions and spec.origin[-1:] == ("backend",):
                    return {
                        "__sic_action__": spec.symbol,
                        "arguments": arguments,
                    }
                nested = self.invoke_calculation(spec, arguments)
                try:
                    result = nested.resolve(spec.symbol)
                finally:
                    self.absorb(nested)
                return result
            function = self.evaluate(expression.function, local)
            return function(*(self.evaluate(argument, local) for argument in expression.arguments))
        if isinstance(expression, ast.SafeMethodCall):
            values = self.evaluate(expression.value, local)
            if values is None:
                return None
            # Argumente müssen weiterhin im ursprünglichen Scope ausgewertet werden.
            arguments = [self.evaluate(argument, local) for argument in expression.arguments]
            return self.evaluate_method(values, expression.name, arguments)
        if isinstance(expression, ast.MethodCall):
            values = self.evaluate(expression.value, local)
            arguments = [self.evaluate(argument, local) for argument in expression.arguments]
            return self.evaluate_method(values, expression.name, arguments)
        raise AssertionError(type(expression))  # pragma: no cover

    @staticmethod
    def stringify(value: Any) -> str:
        """Verwendet die Schreibweise der Sprache für interpolierte Werte."""
        if value is None:
            return "null"
        if type(value) is bool:
            return "true" if value else "false"
        return str(value)

    def invoke_calculation(self, spec, arguments: dict[str, Any]) -> "Evaluator":
        checked = spec.checked or self.checked
        return Evaluator(checked, self.registry, arguments, spec.origin)

    def finalize_goal(self) -> None:
        if self._goal_finalized:
            return
        self._goal_finalized = True
        declarations = {item.name: item for item in self.checked.program.emits}
        for output in self.checked.effect_outputs:
            declaration = declarations[output.name]
            payload = self.evaluate(declaration.payload, {})
            validate_runtime_value(payload, output.effect.payload, output.name)
            self.messages.append(EffectMessage(output.effect, payload, output.name))
            logger.info(
                "[SIC] effect-emitted effect=%s output=%s",
                "::".join(output.effect.identity), output.name,
            )
            logger.debug(
                "[SIC] effect-payload output=%s payload=%r", output.name, payload,
            )
        for checked_listener in self.checked.listeners:
            declaration = checked_listener.declaration
            if declaration.filter is None:
                self.subscriptions.append(EffectSubscription(checked_listener.effect))
                logger.debug(
                    "[SIC] listener explicit effect=%s",
                    "::".join(checked_listener.effect.identity),
                )
            else:
                payload = self.evaluate(declaration.filter, {})
                validate_runtime_value(payload, checked_listener.effect.payload, "on")
                self.subscriptions.append(EffectSubscription(
                    checked_listener.effect, payload, True
                ))
                logger.debug(
                    "[SIC] listener explicit effect=%s filter=%r",
                    "::".join(checked_listener.effect.identity), payload,
                )

    def outgoing_messages(self) -> list[EffectMessage]:
        return [
            message for message in self.messages
            if message.effect.identity not in self.checked.void_effects
        ]

    def absorb(
        self, nested: "Evaluator", caught: frozenset[tuple[str, ...]] = frozenset()
    ) -> None:
        self.messages.extend(
            message for message in nested.outgoing_messages()
            if message.effect.identity not in caught
        )
        self.subscriptions.extend(nested.subscriptions)

    def evaluate_capture(self, captured: ast.CapturedCall, local: dict[str, Any]) -> dict[str, Any]:
        info = self.checked.captures[id(captured)]
        values = {name: None for name in captured.outputs}
        if isinstance(info.spec, ExternalFunction):
            before = len(self.messages)
            result = self.evaluate(captured.call, local)
            produced = self.messages[before:]
            del self.messages[before:]
            for name in info.normal_outputs:
                values[name] = result
            caught_names = frozenset(info.caught_effects)
            for name, output in info.caught_effects.items():
                values[name] = [
                    message.payload for message in produced
                    if message.output == name
                    and message.effect.identity == output.effect.identity
                ]
            self.messages.extend(
                message for message in produced if message.output not in caught_names
            )
            return values

        arguments = {
            argument.name: self.evaluate(argument.value, local)
            for argument in captured.call.arguments
            if isinstance(argument, ast.NamedArgument)
        }
        evaluator = self.invoke_calculation(info.spec, arguments)
        normal = list(info.normal_outputs)
        try:
            # Das Hauptergebnis bestimmt Erfolg oder Fehler. Erst danach werden
            # angeforderte Zwischenwerte aus derselben Auswertung entnommen.
            evaluator.resolve(info.spec.symbol)
            for name in normal:
                values[name] = evaluator.resolve(info.normal_outputs[name])
        except LangCalculationError as error:
            match = next(
                (name for name, declared in info.caught.items()
                 if declared.name == error.name and
                 (declared.identity == error.identity or declared.identity[:1] == ("__local__",))),
                None,
            )
            if match is None:
                self.absorb(evaluator)
                raise
            values[match] = error.payload if info.caught[match].payload is not None else True
        caught_names = frozenset(info.caught_effects)
        outgoing = evaluator.outgoing_messages()
        for name, output in info.caught_effects.items():
            values[name] = [
                message.payload for message in outgoing
                if message.output == name
                and message.effect.identity == output.effect.identity
            ]
        self.messages.extend(
            message for message in outgoing if message.output not in caught_names
        )
        self.subscriptions.extend(evaluator.subscriptions)
        return values

    def evaluate_method(self, values: Any, name: str, arguments: list[Any]) -> Any:
        if name == "keys": return list(values.keys())
        if name == "values": return list(values.values())
        if name == "get": return values.get(arguments[0])
        if name == "contains_key": return arguments[0] in values
        if name == "filter": return [item for item in values if arguments[0](item)]
        if name == "map": return [arguments[0](item) for item in values]
        if name == "flat_map": return [mapped for item in values for mapped in arguments[0](item)]
        if name == "sum": return sum(values)
        if name == "fold": return reduce(arguments[1], values, arguments[0])
        if name == "any": return any(arguments[0](item) for item in values)
        if name == "all": return all(arguments[0](item) for item in values)
        if name == "count": return len(values)
        if name == "take": return values[:arguments[0]]
        if name == "drop": return values[arguments[0]:]
        if name == "first": return values[0] if values else None
        if name == "last": return values[-1] if values else None
        if name == "find": return next((item for item in values if arguments[0](item)), None)
        if name == "sort": return sorted(values)
        if name == "group_by":
            grouped = {}
            for item in values:
                grouped.setdefault(arguments[0](item), []).append(item)
            return grouped
        raise LangRuntimeError(f"Unbekannte Methode {name!r}")
