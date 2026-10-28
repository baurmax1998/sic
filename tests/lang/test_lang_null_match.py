import pytest

from sic.lang import LangTypeError, compile_program, run


def test_null_coalescing_uses_value_or_fallback():
    assert run("goal value: Int = null: Int? ?? 7").value == 7
    assert run("goal value: Int = 3: Int? ?? 7").value == 3


def test_if_condition_narrows_nullable_name():
    source = """
    goal result: Int =
        let value: Int? = 4
        in if value != null then value + 1 else 0
    """
    assert run(source).value == 5


def test_if_without_null_check_cannot_use_nullable_as_int():
    source = """
    goal result: Int =
        let value: Int? = null
        in value + 1
    """
    with pytest.raises(LangTypeError):
        compile_program(source)


def test_safe_field_and_method_access():
    missing = """
    goal name: String =
        let customer: Customer? = null
        in customer?.name ?? "unbekannt"
    """
    assert run(missing).value == "unbekannt"

    nested = """
    goal city: String =
        let customer: Customer? = {address: {city: "Berlin"}}
        in customer?.address?.city ?? "unbekannt"
    """
    assert run(nested).value == "Berlin"

    safe_method = """
    goal first: Int =
        let values: List<Int>? = null
        in values?.first() ?? 0
    """
    assert run(safe_method).value == 0


def test_match_unwraps_nullable_binding():
    source = """
    goal result: Int =
        let value: Int? = 4
        in match value {
            null => 0,
            number => number + 1
        }
    """
    assert run(source).value == 5


def test_match_literal_and_wildcard_patterns():
    source = """
    goal result: Int = match "Ada" {
        "Grace" => 1,
        "Ada" => 2,
        _ => 0
    }
    """
    assert run(source).value == 2


def test_match_must_be_exhaustive_and_cover_null():
    with pytest.raises(LangTypeError, match="abschließendes"):
        compile_program("goal result: Int = match 1 { 1 => 1 }")
    with pytest.raises(LangTypeError, match="null-Fall"):
        compile_program("goal result: Int = match null: Int? { value => 1 }")
