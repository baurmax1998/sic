from sic.lang import IncrementalCompiler, ModuleRegistry


def test_incremental_compiler_tracks_open_names_until_definition():
    compiler = IncrementalCompiler(ModuleRegistry())
    compiler.accept("goal answer: Int = value")
    assert compiler.required_names == {"value"}
    assert not compiler.is_complete()
    assert not compiler.can_accept(" let unrelated")
    assert compiler.can_accept(" let value")

    compiler.accept(" let value = 42")
    assert compiler.required_names == set()
    assert compiler.is_complete()
    assert compiler.checked_program is not None


def test_incremental_compiler_rejects_unrequested_definition():
    compiler = IncrementalCompiler(ModuleRegistry(), "goal answer: Int = 42")
    assert compiler.is_complete()
    assert not compiler.can_accept(" l")
    assert not compiler.can_accept(" let unused = 1")


def test_incremental_compiler_rejects_dependency_cycle_candidate():
    compiler = IncrementalCompiler(ModuleRegistry(), "goal answer: Int = value")
    assert not compiler.can_accept(" let value = answer")


def test_incremental_compiler_rejects_redundant_annotation_candidate():
    compiler = IncrementalCompiler(
        ModuleRegistry(), "goal answer: Int = value: Int let value"
    )
    assert not compiler.can_accept(": Int = 1")
    assert compiler.can_accept(" = 1")
