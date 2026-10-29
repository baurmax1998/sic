"""Bedarfsgesteuerte Auswertung geprüfter SIC-Programme."""
from __future__ import annotations
from functools import reduce
import html
import logging
from typing import Any, Callable, Callable
from .. import ast
from ..checker import CheckedProgram
from ..effects import EffectMessage, EffectSubscription
from ..errors import LangCalculationError, LangRuntimeError
from ..registry import ExternalFunction, ModuleRegistry
from ..types import Primitive, prune
from ..web_values import WebHandler, WebValue
from .models import ExecutionResult
from .validation import validate_runtime_value


logger = logging.getLogger("uvicorn.error.sic.runtime")


class WebEvaluationContext:
    """Metadaten eines Renderdurchlaufs; der Zustand lebt über Durchläufe fort."""

    def __init__(self, state: dict[str, Any] | None = None):
        self.state = state if state is not None else {}
        self.changed: set[str] = set()
        self.handlers: dict[str, WebHandler] = {}
        self.components: dict[str, str] = {}
        self.dependencies: dict[str, set[str]] = {}
        self.binding_dependencies: dict[str, set[str]] = {}
        self.root_dependencies: set[str] = set()
        self.effect_components: list[tuple[EffectSubscription, str]] = []
        self.effect_sources: list[tuple[EffectSubscription, str]] = []
        self._component_stack: list[str] = []
        self._collectors: list[set[str]] = []
        self._suppress_component_reads = 0
        self._occurrences: dict[tuple[str, int], int] = {}
        self._handler_occurrences: dict[str, int] = {}
        self.read_mode = "normal"

    @property
    def component_id(self) -> str | None:
        return self._component_stack[-1] if self._component_stack else None

    def push_component(self, component_id: str) -> None:
        self._component_stack.append(component_id)

    def pop_component(self) -> None:
        self._component_stack.pop()

    def record_read(self, names: set[str]) -> None:
        for collector in self._collectors:
            collector.update(names)
        if self._suppress_component_reads:
            return
        component = self.component_id
        if component is None:
            self.root_dependencies.update(names)
            return
        target = (
            self.binding_dependencies if self.read_mode == "binding"
            else self.dependencies
        )
        target.setdefault(component, set()).update(names)

    def collect_arguments(self):
        context = self
        class Collector:
            def __enter__(self):
                self.names: set[str] = set()
                context._collectors.append(self.names)
                context._suppress_component_reads += 1
                return self.names
            def __exit__(self, *_):
                context._suppress_component_reads -= 1
                context._collectors.pop()
        return Collector()

    def next_component(self, call_id: int, symbol: str) -> str:
        parent = self.component_id or "view"
        key = (parent, call_id)
        occurrence = self._occurrences.get(key, 0)
        self._occurrences[key] = occurrence + 1
        return f"{parent}/{symbol}-{call_id:x}-{occurrence}"

    def register_handler(self, callback: Any, evaluator: "Evaluator") -> str:
        component = self.component_id or "view"
        occurrence = self._handler_occurrences.get(component, 0)
        self._handler_occurrences[component] = occurrence + 1
        identifier = f"{component}:event-{occurrence}"
        owner = getattr(callback, "event_evaluator", evaluator)
        self.handlers[identifier] = WebHandler(callback, self.component_id, owner)
        return identifier


class Evaluator:
    def __init__(
        self, checked: CheckedProgram, registry: ModuleRegistry | None = None,
        overrides: dict[str, Any] | None = None,
        identity_origin: tuple[str, ...] = (),
        *,
        state: dict[str, Any] | None = None,
        web_context: WebEvaluationContext | None = None,
        component_id: str | None = None,
        source_aliases: dict[str, set[str]] | None = None,
        trace_callback: Callable[["Evaluator", str, Any], None] | None = None,
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
        self.web_context = web_context or WebEvaluationContext(state)
        self.state = self.web_context.state
        self.component_id = component_id
        self.source_aliases = source_aliases or {}
        self.trace_callback = trace_callback
        self.active_stack: list[str] = []

    def run(self) -> ExecutionResult:
        goal = self.checked.program.goal.name
        if self.component_id is not None:
            self.web_context.push_component(self.component_id)
        try:
            value = self.resolve(goal)
        finally:
            if self.component_id is not None:
                self.web_context.pop_component()
        return ExecutionResult(
            goal, value, tuple(self.outgoing_messages()), tuple(self.subscriptions)
        )

    def call(self, name: str, **arguments: Any) -> Any:
        """Ruft ein Goal oder Let von Python aus mit denselben Override-Regeln auf."""
        nested = Evaluator(
            self.checked, self.registry, arguments, self.identity_origin,
            state=self.state, web_context=self.web_context,
            trace_callback=self.trace_callback,
        )
        return nested.resolve(name)

    def resolve(self, name: str) -> Any:
        self.web_context.record_read(self.source_aliases.get(name, {name}))
        if name in self.checked.variable_names and name in self.state:
            return self.state[name]
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
        self.active_stack.append(name)
        logger.debug(
            "[SIC] calculate-start calculation=%s origin=%s",
            name, "::".join(self.identity_origin) or "local",
        )
        try:
            value = self.evaluate(self.definitions[name], {})
            validate_runtime_value(value, self.checked.bindings[name], name)
            if name in self.checked.variable_names:
                self.state[name] = value
            else:
                self.values[name] = value
            if self.trace_callback is not None:
                self.trace_callback(self, name, value)
            if name == self.checked.program.goal.name:
                self.finalize_goal()
            logger.debug("[SIC] calculate-finish calculation=%s", name)
            return value
        finally:
            self.active_stack.pop()
            self.active.remove(name)

    def evaluate(self, expression: ast.Expr, local: dict[str, Any]) -> Any:
        if isinstance(expression, ast.Literal): return expression.value
        if isinstance(expression, ast.StringBuilder):
            web_kind = self.checked.web_builders.get(id(expression))
            if web_kind is None:
                return "".join(
                    part if isinstance(part, str) else self.stringify(self.evaluate(part, local))
                    for part in expression.parts
                )
            rendered: list[str] = []
            previous = ""
            for part in expression.parts:
                if isinstance(part, str):
                    rendered.append(part)
                    previous = part
                    continue
                marker = previous.rstrip()
                old_mode = self.web_context.read_mode
                if (
                    marker.endswith('sic:bind-value="')
                    or marker.endswith("sic:bind-value='")
                    or marker.endswith('value="')
                    or marker.endswith("value='")
                ):
                    self.web_context.read_mode = "binding"
                try:
                    value = self.evaluate(part, local)
                finally:
                    self.web_context.read_mode = old_mode
                if isinstance(value, WebValue):
                    rendered.append(value.html)
                elif isinstance(value, list) and all(isinstance(item, WebValue) for item in value):
                    rendered.extend(item.html for item in value)
                elif callable(value):
                    rendered.append(html.escape(
                        self.web_context.register_handler(value, self), quote=True
                    ))
                else:
                    rendered.append(self.escape_web(value))
                previous = ""
            return WebValue("".join(rendered), web_kind)
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
        if isinstance(expression, ast.Assignment):
            value = self.evaluate(expression.value, local)
            validate_runtime_value(value, self.checked.bindings[expression.name], expression.name)
            self.state[expression.name] = value
            self.web_context.changed.add(expression.name)
            return value
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
            function.event_evaluator = self  # type: ignore[attr-defined]
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
                    self.add_subscription(EffectSubscription(
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
                arguments: dict[str, Any] = {}
                argument_sources: dict[str, set[str]] = {}
                for argument in expression.arguments:
                    if not isinstance(argument, ast.NamedArgument):
                        continue
                    with self.web_context.collect_arguments() as reads:
                        arguments[argument.name] = self.evaluate(argument.value, local)
                    argument_sources[argument.name] = set(reads)
                if self.capture_actions and spec.origin[-1:] == ("backend",):
                    return {
                        "__sic_action__": spec.symbol,
                        "arguments": arguments,
                    }
                nested = self.invoke_calculation(
                    spec, arguments, expression, argument_sources
                )
                if nested.component_id is not None:
                    self.web_context.push_component(nested.component_id)
                try:
                    result = nested.resolve(spec.symbol)
                finally:
                    self.absorb(nested)
                    if nested.component_id is not None:
                        self.web_context.pop_component()
                if nested.component_id is not None and isinstance(result, WebValue):
                    wrapped = (
                        f'<sic-component data-sic-component="{html.escape(nested.component_id, quote=True)}">'
                        f'{result.html}</sic-component>'
                    )
                    self.web_context.components[nested.component_id] = wrapped
                    return WebValue(wrapped, "Component::web")
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
    def escape_web(value: Any) -> str:
        """Universelle Maskierung für Text und auch unquoted Attributkontexte."""
        raw = Evaluator.stringify(value)
        escaped = html.escape(raw, quote=True)
        return (escaped.replace("`", "&#96;").replace("=", "&#61;")
                .replace(" ", "&#32;").replace("\t", "&#9;")
                .replace("\n", "&#10;").replace("\r", "&#13;"))

    @staticmethod
    def stringify(value: Any) -> str:
        """Verwendet die Schreibweise der Sprache für interpolierte Werte."""
        if value is None:
            return "null"
        if type(value) is bool:
            return "true" if value else "false"
        return str(value)

    def invoke_calculation(
        self, spec, arguments: dict[str, Any], call: ast.Call | None = None,
        argument_sources: dict[str, set[str]] | None = None,
    ) -> "Evaluator":
        checked = spec.checked or self.checked
        result_type = prune(spec.result_type)
        component_id = None
        if (
            call is not None and isinstance(result_type, Primitive)
            and result_type.name == "Component::web"
        ):
            component_id = self.web_context.next_component(id(call), spec.symbol)
        nested = Evaluator(
            checked, self.registry, arguments, spec.origin,
            state=self.state, web_context=self.web_context,
            component_id=component_id, source_aliases=argument_sources,
            trace_callback=self.trace_callback,
        )
        return nested

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
                self.add_subscription(EffectSubscription(checked_listener.effect))
                logger.debug(
                    "[SIC] listener explicit effect=%s",
                    "::".join(checked_listener.effect.identity),
                )
            else:
                payload = self.evaluate(declaration.filter, {})
                validate_runtime_value(payload, checked_listener.effect.payload, "on")
                self.add_subscription(EffectSubscription(
                    checked_listener.effect, payload, True
                ))
                logger.debug(
                    "[SIC] listener explicit effect=%s filter=%r",
                    "::".join(checked_listener.effect.identity), payload,
                )

    def add_subscription(self, subscription: EffectSubscription) -> None:
        self.subscriptions.append(subscription)
        component = self.web_context.component_id
        if component is not None:
            self.web_context.effect_components.append((subscription, component))
        elif self.active_stack:
            self.web_context.effect_sources.append(
                (subscription, self.active_stack[-1])
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
        if self.web_context.component_id is not None:
            self.web_context.effect_components.extend(
                (subscription, self.web_context.component_id)
                for subscription in nested.subscriptions
            )
        elif self.active_stack:
            self.web_context.effect_sources.extend(
                (subscription, self.active_stack[-1])
                for subscription in nested.subscriptions
            )

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
