"""Typinferenz für einzelne AST-Ausdrücke."""
from __future__ import annotations
from dataclasses import fields, is_dataclass
from .. import ast
from ..calculation import CalculationSpec, ErrorSpec
from ..dependencies import check_definition_order, check_dependency_cycles
from ..errors import LangNameError, LangTypeError
from ..registry import ExternalFunction, ModuleRegistry
from ..types import (
    BOOL, FLOAT, INT, NULL, STRING, FunctionType, ListType, MapType,
    NullableType, Primitive, RecordType, Type, TypeVariable, format_type, prune,
    unify,
)


class ExpressionInferenceMixin:
    def infer(self, expression: ast.Expr, scope: dict[str, Type], expected: Type | None = None) -> Type:
        result: Type
        if isinstance(expression, ast.Literal):
            if expression.value is None:
                result = NULL
            elif isinstance(expression.value, bool):
                result = BOOL
            elif isinstance(expression.value, int):
                result = INT
            elif isinstance(expression.value, float):
                result = FLOAT
            else:
                result = STRING
        elif isinstance(expression, ast.StringBuilder):
            for part in expression.parts:
                if isinstance(part, ast.Expr):
                    self.infer(part, scope)
            result = STRING
        elif isinstance(expression, ast.Name):
            if expression.origin:
                if self.registry.has_calculation(expression.name, expression.origin):
                    raise LangTypeError("Eine Berechnung muss mit benannten Argumenten aufgerufen werden")
                result = self.registry.resolve(expression.name, expression.origin).type
            else:
                if expression.name in scope:
                    result = scope[expression.name]
                else:
                    # Freie Namen sind Eingaben der umgebenden Berechnung.
                    result = self.inputs.setdefault(expression.name, self.fresh())
        elif isinstance(expression, ast.Annotation):
            result = self.from_ref(expression.type_ref)
            self.infer(expression.value, scope, result)
        elif isinstance(expression, ast.ErrorExpr):
            payload = self.error_payloads[expression.name]
            if expression.payload is not None and payload is not None:
                self.infer(expression.payload, scope, payload)
            # `err` ist ein Bottom-Ausdruck: der erwartete Erfolgswert wird
            # nicht durch den Fehler eingeschränkt.
            result = expected or self.fresh()
        elif isinstance(expression, ast.OutputAccess):
            result = self.infer_capture(expression, scope)
        elif isinstance(expression, ast.ListExpr):
            element = prune(expected).element if isinstance(prune(expected), ListType) else self.fresh()
            for item in expression.items:
                self.infer(item, scope, element)
            result = ListType(element)
        elif isinstance(expression, ast.RecordExpr):
            expected_record = prune(expected) if expected is not None else None
            if not expression.fields and isinstance(expected_record, MapType):
                return expected_record
            names = [name for name, _ in expression.fields]
            if len(names) != len(set(names)):
                raise LangTypeError("Record enthält doppelte Felder")
            fields = {
                name: self.infer(
                    value,
                    scope,
                    expected_record.fields.get(name)
                    if isinstance(expected_record, RecordType) else None,
                )
                for name, value in expression.fields
            }
            result = RecordType(None, fields, closed=True)
        elif isinstance(expression, ast.MapExpr):
            expected_map = prune(expected) if expected is not None else None
            key_type = expected_map.key if isinstance(expected_map, MapType) else self.fresh()
            value_type = expected_map.value if isinstance(expected_map, MapType) else self.fresh()
            for key, value in expression.entries:
                self.infer(key, scope, key_type)
                self.infer(value, scope, value_type)
            result = MapType(key_type, value_type)
        elif isinstance(expression, ast.LocalLet):
            local_type = self.from_ref(expression.annotation) if expression.annotation else self.fresh()
            self.infer(expression.value, scope, local_type)
            local = dict(scope)
            local[expression.name] = local_type
            result = self.infer(expression.body, local, expected)
        elif isinstance(expression, ast.Unary):
            wanted = BOOL if expression.operator == "not" else INT
            self.infer(expression.operand, scope, wanted)
            result = wanted
        elif isinstance(expression, ast.Binary):
            result = self.infer_binary(expression, scope, expected)
        elif isinstance(expression, ast.IfExpr):
            self.infer(expression.condition, scope, BOOL)
            branch = expected or self.fresh()
            then_scope, else_scope = self.narrow_scopes(expression.condition, scope)
            self.infer(expression.then_branch, then_scope, branch)
            self.infer(expression.else_branch, else_scope, branch)
            result = branch
        elif isinstance(expression, ast.MatchExpr):
            subject = prune(self.infer(expression.value, scope))
            branch = expected or self.fresh()
            null_covered = False
            catch_all = False
            for case_index, case in enumerate(expression.cases):
                local = dict(scope)
                if isinstance(case.pattern, ast.NullPattern):
                    if not isinstance(subject, NullableType):
                        raise LangTypeError("null-Muster benötigt einen nullable Typ")
                    null_covered = True
                elif isinstance(case.pattern, ast.LiteralPattern):
                    self.infer(ast.Literal(case.pattern.value), scope, subject)
                elif isinstance(case.pattern, ast.BindingPattern):
                    local[case.pattern.name] = (
                        subject.inner if isinstance(subject, NullableType) and null_covered else subject
                    )
                    catch_all = True
                elif isinstance(case.pattern, ast.WildcardPattern):
                    catch_all = True
                if catch_all and case_index != len(expression.cases) - 1:
                    raise LangTypeError("Binding- oder _-Muster muss der letzte match-Fall sein")
                self.infer(case.body, local, branch)
            if not catch_all:
                raise LangTypeError("match benötigt ein abschließendes Binding- oder _-Muster")
            if isinstance(subject, NullableType) and not null_covered:
                raise LangTypeError("match über nullable Typ benötigt einen null-Fall")
            result = branch
        elif isinstance(expression, ast.SafeField):
            owner = prune(self.infer(expression.value, scope))
            if not isinstance(owner, NullableType):
                raise LangTypeError("'?.' benötigt einen nullable Wert")
            record = prune(owner.inner)
            if isinstance(record, TypeVariable):
                inferred_record = RecordType(None, {expression.name: self.fresh()})
                unify(record, inferred_record)
                record = inferred_record
            if not isinstance(record, RecordType):
                raise LangTypeError(f"Sicherer Feldzugriff auf {format_type(record)}")
            if record.closed and expression.name not in record.fields:
                raise LangTypeError(f"Record besitzt kein Feld {expression.name!r}")
            result = self.as_nullable(record.fields.setdefault(expression.name, self.fresh()))
        elif isinstance(expression, ast.SafeMethodCall):
            owner = prune(self.infer(expression.value, scope))
            if not isinstance(owner, NullableType):
                raise LangTypeError("'?.' benötigt einen nullable Wert")
            synthetic = "__safe_receiver__"
            local = dict(scope)
            local[synthetic] = owner.inner
            method = ast.MethodCall(ast.Name(synthetic), expression.name, expression.arguments)
            result = self.as_nullable(self.infer_method(method, local, None))
        elif isinstance(expression, ast.Index):
            owner = prune(self.infer(expression.value, scope))
            if isinstance(owner, ListType):
                self.infer(expression.index, scope, INT)
                result = owner.element
            elif isinstance(owner, MapType):
                self.infer(expression.index, scope, owner.key)
                result = owner.value
            elif owner == STRING:
                self.infer(expression.index, scope, INT)
                result = STRING
            else:
                raise LangTypeError(f"Indexzugriff auf {format_type(owner)}")
        elif isinstance(expression, ast.Field):
            owner = prune(self.infer(expression.value, scope))
            if isinstance(owner, TypeVariable):
                record = RecordType(None, {expression.name: self.fresh()})
                unify(owner, record)
                owner = record
            if not isinstance(owner, RecordType):
                raise LangTypeError(f"Feldzugriff .{expression.name} auf {format_type(owner)}")
            if owner.closed and expression.name not in owner.fields:
                raise LangTypeError(f"Record besitzt kein Feld {expression.name!r}")
            result = owner.fields.setdefault(expression.name, self.fresh())
        elif isinstance(expression, ast.Lambda):
            expected_function = prune(expected) if expected is not None else None
            if isinstance(expected_function, FunctionType):
                if len(expected_function.parameters) != len(expression.parameters):
                    raise LangTypeError("Falsche Parameteranzahl im Lambda")
                parameters = expected_function.parameters
                body_type = expected_function.result
            else:
                parameters = [self.fresh() for _ in expression.parameters]
                body_type = self.fresh()
            local = dict(scope)
            local.update(zip(expression.parameters, parameters))
            self.infer(expression.body, local, body_type)
            result = FunctionType(parameters, body_type)
        elif isinstance(expression, ast.Call):
            calculation = self.calculation_spec(expression)
            named = any(isinstance(arg, ast.NamedArgument) for arg in expression.arguments)
            external = None
            if (
                isinstance(expression.function, ast.Name)
                and expression.function.origin and calculation is None
            ):
                external = self.registry.resolve(
                    expression.function.name, expression.function.origin
                )
            if external is not None:
                if not external.parameter_names:
                    if named:
                        raise LangTypeError("Externe Funktion besitzt keine benannten Parameter")
                    if len(expression.arguments) != len(external.type.parameters):
                        raise LangTypeError("Falsche Argumentanzahl")
                    for argument, parameter_type in zip(
                        expression.arguments, external.type.parameters
                    ):
                        self.infer(argument, scope, parameter_type)
                else:
                    assigned: dict[str, ast.Expr] = {}
                    positional_index = 0
                    for argument in expression.arguments:
                        if isinstance(argument, ast.NamedArgument):
                            name, value = argument.name, argument.value
                        else:
                            if positional_index >= len(external.parameter_names):
                                raise LangTypeError("Zu viele positionale Argumente")
                            name, value = external.parameter_names[positional_index], argument
                            positional_index += 1
                        if name in assigned:
                            raise LangTypeError(f"Aufruf enthält Argument {name!r} mehrfach")
                        assigned[name] = value
                    expected_names = set(external.parameter_names)
                    if set(assigned) != expected_names:
                        missing = expected_names - set(assigned)
                        unknown = set(assigned) - expected_names
                        detail = sorted(missing or unknown)[0]
                        raise LangNameError(f"Ungültiges Argument {detail!r} für {external.symbol!r}")
                    for name, parameter_type in zip(
                        external.parameter_names, external.type.parameters
                    ):
                        self.infer(assigned[name], scope, parameter_type)
                result = external.type.result
                self.external_calls[id(expression)] = external
            elif calculation is not None or named:
                result, _ = self.infer_calculation_call(expression, scope, expected)
            else:
                arguments = [self.infer(argument, scope) for argument in expression.arguments]
                result = expected or self.fresh()
                self.infer(expression.function, scope, FunctionType(arguments, result))
        elif isinstance(expression, ast.MethodCall):
            result = self.infer_method(expression, scope, expected)
        else:  # pragma: no cover
            raise AssertionError(type(expression))
        if expected is not None:
            self.assign(expected, result)
            return expected
        return result
