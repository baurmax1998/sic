from pathlib import Path

from sic.interfaces import describe_codebase, describe_program, render_interface
from sic.lang import compile_program


def test_description_contains_input_cuts_outputs_types_and_errors():
    checked = compile_program(
        '''
        goal total: Int = subtotal + fee
        let subtotal =
            if valid then amount else err invalidAmount = "ungültig"
        '''
    )

    description = describe_program(checked, "price.sic")
    assert description["types"] == {}
    total = description["calculations"][0]
    assert total["name"] == "total"
    assert total["type"] == "Int"

    normal = next(item for item in total["signatures"] if not item["overrides"])
    assert normal["inputs"] == {"amount": "Int", "fee": "Int", "valid": "Bool"}
    assert normal["outputs"] == {"subtotal": "Int", "total": "Int"}
    assert normal["errors"][0]["name"] == "invalidAmount"
    assert normal["errors"][0]["type"] == "String"

    overridden = next(
        item for item in total["signatures"] if item["overrides"] == ["subtotal"]
    )
    assert overridden["inputs"] == {"fee": "Int", "subtotal": "Int"}
    assert overridden["errors"] == []

    rendered = render_interface(description)
    assert "package price;" in rendered
    assert "interface price" not in rendered
    assert "Int total(\n" in rendered
    assert "    Int amount,\n" in rendered
    assert "    Int fee,\n" in rendered
    assert "    Bool valid,\n" in rendered
    assert "    override Int subtotal = derive(amount, valid)\n)" in rendered
    assert "throws invalidAmount(String);" in rendered


def test_qualified_symbols_are_rendered_as_ordered_imports():
    checked = compile_program(
        'goal content: Html::web = text::web("Hallo")\n'
    )

    rendered = render_interface(describe_program(checked, "page.sic"))
    assert "package page;\n\nimport web.Html;\nimport web.text;" in rendered
    assert "interface page" not in rendered


def test_outputs_follow_source_declaration_order():
    checked = compile_program(
        '''
        goal value: String = first + second + third
        let first = "1"
        let second = "2"
        let third = "3"
        '''
    )

    rendered = render_interface(describe_program(checked, "ordered.sic"))
    assert rendered.index("String first;") < rendered.index("String second;")
    assert rendered.index("String second;") < rendered.index("String third;")


def test_describe_codebase_mirrors_paths_under_out_i(tmp_path: Path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "create.sic").write_text(
        "goal created = {id: id: Int, title: title: String}\n",
        encoding="utf-8",
    )

    generated = describe_codebase(tmp_path)

    assert generated == [tmp_path / ".out" / "i" / "backend" / "create.i"]
    result = generated[0].read_text(encoding="utf-8")
    assert "// Source: backend/create.sic" in result
    assert "package backend.create;" in result
    assert "interface create" not in result
    assert "record { Int id; String title; } created(\n" in result
    assert "    Int id,\n    String title\n);" in result
    tree = tmp_path / ".out" / "t" / "backend" / "create"
    assert tree.is_file()
    assert "goal created:" in tree.read_text(encoding="utf-8")


def test_imported_standard_function_gets_its_own_interface(tmp_path: Path):
    (tmp_path / "save.sic").write_text(
        'goal saved: Bool = write_json::files::std([1], "data.json")\n',
        encoding="utf-8",
    )

    generated = describe_codebase(tmp_path)

    imported = tmp_path / ".out" / "i" / "std" / "files" / "write_json.i"
    assert imported in generated
    content = imported.read_text(encoding="utf-8")
    assert "package std.files.write_json;" in content
    assert "Bool write_json<T>(" in content
    assert "    T value," in content
    assert "    String path" in content


def test_web_project_uses_declared_sources_and_backend_registry(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    config = tmp_path / "app.sic"
    config.write_text(
        '''
        goal app: App::web = {
            port: 8000,
            pages: ["frontend/app.sic"],
            backend: "backend"
        }
        ''',
        encoding="utf-8",
    )
    (tmp_path / "backend" / "greet.sic").write_text(
        'goal greeting: String = "Hallo " + (name: String)\n', encoding="utf-8"
    )
    (tmp_path / "frontend" / "app.sic").write_text(
        'goal view: View::web = """{greeting::backend(name: "SIC")}"""\n',
        encoding="utf-8",
    )
    # Auch noch nicht in app.sic deklarierte SIC-Dateien gehören zur Codebasis.
    (tmp_path / "unused.sic").write_text("goal unused: Bool = true\n", encoding="utf-8")

    generated = describe_codebase(config)

    relative = {
        path.relative_to(tmp_path / ".out" / "i").as_posix()
        for path in generated
    }
    assert {
        "app.i",
        "backend/greet.i",
        "frontend/app.i",
        "unused.i",
        "web/App.i",
        "web/View.i",
    } <= relative
    assert "backend/greeting.i" not in relative
    assert "package web.View;" in (
        tmp_path / ".out" / "i" / "web" / "View.i"
    ).read_text(encoding="utf-8")
    app_interface = (
        tmp_path / ".out" / "i" / "web" / "App.i"
    ).read_text(encoding="utf-8")
    assert "String backend;" in app_interface
    assert "endpoints" not in app_interface

    frontend_tree = (
        tmp_path / ".out" / "t" / "frontend" / "app"
    ).read_text(encoding="utf-8")
    assert "import backend.greeting" in frontend_tree
    assert "goal greeting: String" in frontend_tree
    assert "input name: String" in frontend_tree

    app_tree = (tmp_path / ".out" / "t" / "app").read_text(encoding="utf-8")
    assert "import web.App" in app_tree
    assert "web.Endpoint" not in app_tree
