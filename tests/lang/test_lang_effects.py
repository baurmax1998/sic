from pathlib import Path

import pytest

from sic.lang import (
    Evaluator, LangCalculationError, LangTypeError, ModuleRegistry,
    compile_program, standard_registry,
)


def effect_registry() -> ModuleRegistry:
    registry = ModuleRegistry()
    registry.register_source("effects", "backend", "effect Todos: Int")
    return registry


def test_typed_effect_is_emitted_and_propagated_from_calculation(caplog):
    registry = effect_registry()
    registry.register_source(
        "create", "backend",
        """
        emit todosChanged: Todos::effects::backend = create.id
        goal create: Todo = {id: id: Int}
        """,
    )
    checked = compile_program(
        "goal todo: Todo = create::create::backend(id: 42)", registry
    )
    with caplog.at_level("INFO", logger="uvicorn.error.sic.runtime"):
        result = Evaluator(checked, registry).run()
    assert result.value == {"id": 42}
    assert "effect-emitted effect=Todos::effects::backend" in caplog.text
    assert [(item.output, item.payload) for item in result.effects] == [
        ("todosChanged", 42)
    ]

    captured = compile_program(
        """
        goal id: Int = created.id
        created, todosChanged = create::create::backend(id: 7)
        """,
        registry,
    )
    evaluator = Evaluator(captured, registry)
    assert evaluator.run().effects == ()
    assert evaluator.resolve("todosChanged") == [7]


def test_effect_payload_and_listener_filter_are_statically_typed():
    registry = effect_registry()
    with pytest.raises(LangTypeError):
        compile_program(
            'emit changed: Todos::effects::backend = "wrong"\n'
            "goal value: Int = 1",
            registry,
        )
    with pytest.raises(LangTypeError):
        compile_program(
            'on Todos::effects::backend = "wrong"\n'
            "goal value: Int = 1",
            registry,
        )


def test_explicit_listener_has_runtime_filter():
    registry = effect_registry()
    checked = compile_program(
        """
        on Todos::effects::backend = id
        goal value: Int = id: Int
        """,
        registry,
    )
    result = Evaluator(checked, registry, {"id": 7}).run()
    assert len(result.subscriptions) == 1
    assert result.subscriptions[0].filtered
    assert result.subscriptions[0].filter == 7


def test_file_effects_support_ignore_void_and_named_capture(tmp_path: Path):
    path = tmp_path / "value.txt"
    path.write_text("old", encoding="utf-8")
    registry = standard_registry(tmp_path)

    read = compile_program(
        'ignore FileChanged::files::std\n'
        'goal value: String = read_text::files::std("value.txt")',
        registry,
    )
    assert Evaluator(read, registry).run().subscriptions == ()

    write = compile_program(
        """
        goal result: Bool = saved
        saved, fileChanged =
            write_text::files::std("new", "value.txt")
        """,
        registry,
    )
    result = Evaluator(write, registry).run()
    assert result.value is True
    assert result.effects == ()
    assert len(result.value if isinstance(result.value, list) else [result.value]) == 1
    evaluator = Evaluator(write, registry)
    evaluator.run()
    assert evaluator.resolve("fileChanged") == [str(path.resolve())]

    suppressed = compile_program(
        'void FileChanged::files::std\n'
        'goal result: Bool = write_text::files::std("again", "value.txt")',
        registry,
    )
    assert Evaluator(suppressed, registry).run().effects == ()


def test_declared_success_effect_is_not_created_after_error():
    registry = effect_registry()
    checked = compile_program(
        """
        emit changed: Todos::effects::backend = 1
        goal value: Int = err failed
        """,
        registry,
    )
    evaluator = Evaluator(checked, registry)
    with pytest.raises(LangCalculationError):
        evaluator.run()
    assert evaluator.messages == []
