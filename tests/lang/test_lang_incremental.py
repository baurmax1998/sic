import pytest

from sic.lang import LangPrefixState, LangSyntaxError, PrefixStatus, check_prefix


@pytest.mark.parametrize(
    "source",
    [
        "",
        "go",
        "goal",
        "goal result:",
        "goal result: List<",
        "goal result: List<Int> =",
        'goal result: String = "noch offen',
        'goal result: String = """Hallo {name}',
        "goal result: Int = 1 +",
        "goal result: Bool = 1 =",
        "goal result: Int = maybe ?",
        "goal result: Int = match maybe { null =>",
        "goal result: List<Int> = values.map(value =",
    ],
)
def test_valid_incomplete_prefixes(source):
    prefix = check_prefix(source)
    assert prefix.status is PrefixStatus.INCOMPLETE


def test_complete_multiline_string_builder_is_recognized():
    checked = check_prefix('goal result: String = """Hallo {"Welt"}"""')
    assert checked.status is PrefixStatus.COMPLETE


def test_complete_program_is_recognized():
    checked = check_prefix("goal result: Int = value + 1 let value: Int = 2")
    assert checked.status is PrefixStatus.COMPLETE
    assert checked.program is not None


def test_invalid_prefix_is_rejected():
    checked = check_prefix("goal result: Int = ]")
    assert checked.status is PrefixStatus.INVALID
    assert isinstance(checked.error, LangSyntaxError)


def test_state_accepts_chunks_and_filters_candidates():
    state = LangPrefixState()
    assert state.accept("go") is PrefixStatus.INCOMPLETE
    assert state.allowed_fragments(["al", "ose", "!"]) == ["al"]
    state.accept("al result: Int = 1")
    assert state.is_complete()
    assert state.can_accept(" + 2")
    assert not state.can_accept(" ]")


def test_failed_accept_does_not_modify_state():
    state = LangPrefixState("goal result: Int = ")
    before = state.source
    with pytest.raises(LangSyntaxError):
        state.accept("]")
    assert state.source == before
    assert state.status is PrefixStatus.INCOMPLETE


def test_type_annotations_without_parentheses_work_incrementally():
    source = """
    goal outstanding: List<Int> =
        customers: List<Customer>
            .map(customer => customer.orders: List<Order>
                .map(order => order.amount: Int).sum())
    let customers = []
    """
    assert check_prefix(source).status is PrefixStatus.COMPLETE
