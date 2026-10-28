import pytest

from sic.lang import LangRuntimeError, LangTypeError, compile_program, run


def test_nullable_suffix_and_null_for_all_value_types():
    source = """
    goal values: List<String?> = [null, "Ada"]
    """
    checked = compile_program(source)
    assert checked.type_of("values") == "List<String?>"
    assert run(source).value == [None, "Ada"]


@pytest.mark.parametrize(
    ("type_name", "literal", "value"),
    [("Bool?", "null", None), ("Int?", "1", 1), ("Float?", "1.5", 1.5)],
)
def test_nullable_primitive_types(type_name, literal, value):
    assert run(f"goal value: {type_name} = {literal}").value == value


def test_float_arithmetic_division_and_modulo():
    assert run("goal value: Float = 7.5 / 2.5 + 1.0").value == 4.0
    assert run("goal value: Int = 11 % 4").value == 3
    with pytest.raises(LangTypeError, match="Float-Operanden"):
        compile_program("goal value: Int = 7 / 2")


def test_map_literal_type_and_index_access():
    source = """
    goal score: Int =
        let scores: Map<String, Int> = {"Ada": 10, "Grace": 12}
        in scores["Grace"]
    """
    assert run(source).value == 12


def test_map_operations():
    source = """
    goal names: List<String> =
        let scores: Map<String, Int> = {"Ada": 10, "Grace": 12}
        in scores.keys().sort()
    """
    assert run(source).value == ["Ada", "Grace"]
    assert run('goal found: Int? = {"Ada": 10}: Map<String, Int>.get("Ada")').value == 10
    assert run('goal found: Int? = {"Ada": 10}: Map<String, Int>.get("Grace")').value is None
    assert run('goal found: Bool = {"Ada": 10}: Map<String, Int>.contains_key("Ada")').value is True


def test_missing_map_key_is_runtime_error():
    source = """
    goal score: Int =
        let scores: Map<String, Int> = {"Ada": 10}
        in scores["Grace"]
    """
    with pytest.raises(LangRuntimeError, match="Map-Schlüssel"):
        run(source)


def test_local_binding_is_scoped_to_its_body():
    source = """
    goal total: Int =
        let subtotal = [1, 2, 3].sum()
        in subtotal * 2
    """
    assert run(source).value == 12


def test_list_concatenation_and_index():
    assert run("goal value: List<Int> = [1, 2] + [3]").value == [1, 2, 3]
    assert run("goal value: Int = [4, 5][1]").value == 5


def test_extended_list_operations():
    assert run("goal value: List<Int> = [1, 2].flat_map(x => [x, x])").value == [1, 1, 2, 2]
    assert run("goal value: Bool = [1, 2, 3].any(x => x == 2)").value is True
    assert run("goal value: Bool = [1, 2, 3].all(x => x > 0)").value is True
    assert run("goal value: Int = [1, 2, 3].count()").value == 3
    assert run("goal value: List<Int> = [1, 2, 3].take(2)").value == [1, 2]
    assert run("goal value: List<Int> = [1, 2, 3].drop(1)").value == [2, 3]
    assert run("goal value: Int? = [3, 1, 2].sort().first()").value == 1
    assert run("goal value: Int? = [1, 2, 3].find(x => x > 1)").value == 2


def test_group_by_returns_a_map_of_lists():
    source = 'goal groups: Map<String, List<String>> = ["Ada", "Amy"].group_by(x => x)'
    assert run(source).value == {"Ada": ["Ada"], "Amy": ["Amy"]}
