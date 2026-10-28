import pytest

from sic.lang import (
    LangCalculationError, LangNameError, LangTypeError, ModuleRegistry,
    compile_program, run,
)


def price_registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.register_source(
        "preise",
        "shop",
        """
        goal rechnungsbetrag: Float = grundpreis - rabatt
        let rabatt =
            if divisor == 0.0
            then err divideByZeroError = "Der Divisor darf nicht null sein"
            else punkte / divisor
        """,
    )
    return registry


def test_goal_and_let_are_importable_calculations():
    registry = price_registry()
    assert run(
        "goal wert: Float = rechnungsbetrag::preise::shop("
        "grundpreis: 100.0, punkte: 20.0, divisor: 2.0)", registry,
    ).value == 90.0
    assert run(
        "goal wert: Float = rabatt::preise::shop(punkte: 20.0, divisor: 2.0)",
        registry,
    ).value == 10.0


def test_intermediate_override_cuts_off_inputs_and_error_path():
    registry = price_registry()
    source = (
        "goal wert: Float = rechnungsbetrag::preise::shop("
        "grundpreis: 100.0, rabatt: 20.0)"
    )
    assert run(source, registry).value == 80.0


def test_all_branch_inputs_are_required_but_only_selected_branch_runs():
    registry = price_registry()
    with pytest.raises(LangNameError, match="divisor"):
        compile_program(
            "goal wert: Float = rechnungsbetrag::preise::shop("
            "grundpreis: 100.0, punkte: 20.0)", registry,
        )
    assert run(
        "goal wert: Float = rechnungsbetrag::preise::shop("
        "grundpreis: 100.0, punkte: 20.0, divisor: 2.0)", registry,
    ).value == 90.0


def test_err_with_and_without_payload_and_automatic_propagation():
    with pytest.raises(LangCalculationError) as plain:
        run("goal wert: Int = err kaputt")
    assert plain.value.name == "kaputt"
    assert plain.value.payload is None

    with pytest.raises(LangCalculationError) as payload:
        run('goal wert: Int = err kaputt = "Details"')
    assert payload.value.payload == "Details"


def test_destructuring_catches_only_selected_error_and_tracks_missing_values():
    registry = price_registry()
    source = """
    goal meldung: String =
        if divideByZeroError != null then divideByZeroError else "ok"
    rechnungsbetrag, divideByZeroError =
        rechnungsbetrag::preise::shop(
            grundpreis: 100.0, punkte: 20.0, divisor: 0.0)
    """
    checked = compile_program(source, registry)
    assert checked.type_of("rechnungsbetrag") == "Float?"
    assert checked.type_of("divideByZeroError") == "String?"
    assert run(source, registry).value == "Der Divisor darf nicht null sein"

    with pytest.raises(LangTypeError):
        compile_program(
            """
            goal wert: Float = rechnungsbetrag + 1.0
            rechnungsbetrag, divideByZeroError =
                rechnungsbetrag::preise::shop(
                    grundpreis: 100.0, punkte: 20.0, divisor: 0.0)
            """,
            registry,
        )


def test_uncaught_error_still_propagates_from_multi_error_calculation():
    registry = ModuleRegistry()
    registry.register_source(
        "modul", "paket",
        """
        goal wert: Int = if first then err erster else if second then err zweiter else 1
        """,
    )
    source = """
    goal behandelt: Bool = erster != null
    wert, erster = wert::modul::paket(first: false, second: true)
    """
    with pytest.raises(LangCalculationError, match="zweiter"):
        run(source, registry)


def test_local_calculation_call_and_python_inputs():
    source = """
    goal ergebnis: Int = produkt(a: 6, b: 7)
    let produkt = a * b
    """
    assert run(source).value == 42
    assert run("goal ergebnis: Int = a + b", arguments={"a": 10, "b": 5}).value == 15
