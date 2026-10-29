import json

import pytest

from sic.cli import main
from sic.lang import (
    LangDefinitionOrderError, LangRuntimeError, LangTypeError, compile_program,
    run, standard_registry,
)
from sic.lang.tooling import analyze_source


def test_source_analysis_returns_semantic_tokens_usages_and_diagnostics():
    source = 'goal greeting: String = prefix + name\nlet prefix = "Hallo "\nlet name = "SIC"'
    analysis = analyze_source(source, standard_registry())

    assert not analysis["diagnostics"]
    assert any(token["type"] == "keyword" for token in analysis["tokens"])
    assert any(token["type"] == "type" for token in analysis["tokens"])
    assert any(token["type"] == "string" for token in analysis["tokens"])
    assert next(symbol for symbol in analysis["symbols"] if symbol["name"] == "prefix")[
        "occurrences"
    ] == [{"start": 24, "end": 30}, {"start": 42, "end": 48}]

    invalid = analyze_source('goal value: Int = "falsch"', standard_registry())
    assert invalid["diagnostics"][0]["severity"] == "error"
    assert "Int" in invalid["diagnostics"][0]["message"]

    broken_string = analyze_source(
        'goal greeting: String = prefix + name\n'
        'let prefix = "Hallo \nlet name = "SIC"',
        standard_registry(),
    )
    assert broken_string["diagnostics"]
    assert any(
        "incomplete" in token.get("modifiers", [])
        for token in broken_string["tokens"]
    )


def test_redundant_definition_annotation_is_rejected():
    source = """
    goal total: Int =
        orders: List<Order>.map(order => order.amount: Int).sum()
    let orders: List<Order> = [{amount: 2}]
    """
    with pytest.raises(LangTypeError, match="Redundante Typannotation.*orders"):
        compile_program(source)


def test_first_function_use_propagates_annotated_signature():
    source = """
    goal total: Int = calculate_total(orders: List<Order>): Int
    let calculate_total = (items) =>
        items.map(item => item.amount: Int).sum()
    let orders = [{amount: 2}, {amount: 3}]
    """
    checked = compile_program(source)
    assert checked.type_of("calculate_total") == "(List<Order>) => Int"
    assert run(source).value == 5


def test_standard_library_reads_and_runtime_validates_json(tmp_path):
    (tmp_path / "customers.json").write_text(
        json.dumps([{"name": "Ada"}, {"name": "Grace"}]), encoding="utf-8"
    )
    source = """
    goal names: List<String> =
        read_json::files::std("customers.json"): List<Customer>
            .map(customer => customer.name: String)
    """
    assert run(source, standard_registry(tmp_path)).value == ["Ada", "Grace"]

    (tmp_path / "customers.json").write_text('[{"name": 12}]', encoding="utf-8")
    with pytest.raises(LangRuntimeError, match="String"):
        run(source, standard_registry(tmp_path))


def test_definition_before_first_requirement_is_rejected():
    source = """
    let customers = [{name: "Ada"}]
    goal amounts: List<Int> =
        customers.map(customer => customer.amount: Int)
    """
    with pytest.raises(LangDefinitionOrderError, match="goal muss die erste"):
        compile_program(source)


def test_unrequested_definition_after_goal_is_rejected():
    source = """
    goal answer: Int = 42
    let unused = 1
    """
    with pytest.raises(LangDefinitionOrderError, match="unused.*bevor.*benötigt"):
        compile_program(source)


def test_literal_record_missing_required_field_is_static_error():
    source = """
    goal amounts: List<Int> =
        customers: List<Customer>.map(customer => customer.amount: Int)
    let customers = [{name: "Ada"}]
    """
    with pytest.raises(LangTypeError, match="Feld.*amount"):
        compile_program(source)


def test_type_error_contains_source_diagnostic():
    source = 'goal result: Int = "falsch"'
    with pytest.raises(LangTypeError) as caught:
        compile_program(source)
    diagnostic = caught.value.diagnostic(source, "example.sic")
    assert "example.sic:1:" in diagnostic
    assert "^" in diagnostic
    assert 'goal result: Int = "falsch"' in diagnostic


def test_cli_check_and_run(tmp_path, capsys):
    program = tmp_path / "answer.sic"
    program.write_text("goal answer: Int = 6 * 7\n", encoding="utf-8")

    assert main(["check", str(program)]) == 0
    assert "OK: goal answer: Int" in capsys.readouterr().out
    assert main(["run", str(program)]) == 0
    assert capsys.readouterr().out.strip() == "42"


def test_cli_prints_located_error(tmp_path, capsys):
    program = tmp_path / "broken.sic"
    program.write_text('goal answer: Int = "nein"\n', encoding="utf-8")
    assert main(["check", str(program)]) == 1
    error = capsys.readouterr().err
    assert f"{program}:1:" in error
    assert "^" in error
