import pytest

from sic.lang import (
    INT, STRING, Evaluator, FunctionType, LangDependencyError, LangTypeError,
    ListType, ModuleRegistry, RecordType, compile_program, run, standard_registry,
)


def test_forward_definitions_are_evaluated_by_dependency():
    source = """
    goal total: Int = paintable_area * price
    let paintable_area = wall_area - window_area
    let wall_area = 6 * 3
    let window_area = 2 * 1
    let price = 1200
    """
    assert run(source).value == 19200


def test_record_requirements_and_list_pipeline():
    source = """
    goal outstanding: List<Int> =
        (customers: List<Customer>)
            .map(customer =>
                customer.orders: List<Order>
                    .filter(order => not order.paid)
                    .map(order => order.amount: Int)
                    .sum()
            )

    let customers = [
        {name: "Ada", orders: [
            {amount: 8000, paid: false},
            {amount: 4500, paid: true}
        ]},
        {name: "Grace", orders: [
            {amount: 2500, paid: false}
        ]}
    ]
    """
    checked = compile_program(source)
    assert checked.type_of("outstanding") == "List<Int>"
    assert set(checked.records["Order"].fields) == {"amount", "paid"}
    assert run(source).value == [8000, 2500]


def test_multiline_string_builder_interpolates_expressions():
    source = '''
    goal greeting: String = """Hallo {name}!
Du hast {messages.count()} Nachrichten.
{{name}} bleibt Text."""
    let name = "Ada"
    let messages = [1, 2, 3]
    '''
    assert run(source).value == (
        "Hallo Ada!\nDu hast 3 Nachrichten.\n{name} bleibt Text."
    )


def test_declarative_web_view_uses_safe_string_builder():
    source = '''
    goal view: View::web = """
    <main><h1>{title}</h1><button sic:onclick="{_ => true}">OK</button></main>
    """
    let title = "Test & SIC"
    '''
    result = run(source).value
    assert "<main>" in result.html
    assert "Test&#32;&amp;&#32;SIC" in result.html


def test_component_builder_escapes_values_and_var_event_updates_state():
    source = '''
    goal view: View::web = """<p>{draft}</p><input sic:oninput="{next => draft <- next}">"""
    var draft: String = "<unsafe>"
    '''
    registry = standard_registry()
    checked = compile_program(source, registry)
    evaluator = Evaluator(checked, registry)
    first = evaluator.run().value
    assert first.html.startswith("<p>&lt;unsafe&gt;</p>")

    handler = next(iter(evaluator.web_context.handlers.values()))
    handler.callback("A & B")
    updated = Evaluator(checked, registry, state=evaluator.state).run().value
    assert "A&#32;&amp;&#32;B" in updated.html


def test_if_fold_and_forward_function():
    source = """
    goal total: Int = calculate_total(orders)
    let calculate_total = (items) => items.fold(0, (total, item) =>
        if item.paid then total else total + item.amount
    )
    let orders: List<Order> = [
        {amount: 10, paid: false},
        {amount: 20, paid: true}
    ]
    """
    assert run(source).value == 10


def test_external_origin_path_uses_registry():
    registry = ModuleRegistry()
    customer = RecordType("Customer", {"name": STRING})
    registry.register(
        "read_customers", ("files", "std"),
        FunctionType([STRING], ListType(customer)),
        lambda path: [{"name": "Ada"}] if path == "customers.json" else [],
    )
    source = """
    goal names: List<String> = customers.map(customer => customer.name)
    let customers = read_customers::files::std("customers.json")
    """
    assert run(source, registry).value == ["Ada"]


def test_contradicting_field_requirement_is_rejected():
    source = """
    goal values: List<Int> = (items: List<Item>).map(item => (item.value: Int))
    let items = [{value: "falsch"}]
    """
    with pytest.raises(LangTypeError):
        compile_program(source)


def test_dependency_cycle_is_rejected_during_checking():
    source = """
    goal first: Int = second + 1
    let second: Int = first + 1
    """
    with pytest.raises(LangDependencyError, match="Abhängigkeitszyklus"):
        run(source)
