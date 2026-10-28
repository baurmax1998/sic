from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sic.lang import LangTypeError, compile_program
from sic.web import (
    _project_registry, _view_source_dependencies, build_web, create_app,
    load_web_config,
)


def web_project(tmp_path: Path) -> Path:
    backend = tmp_path / "backend"
    backend.mkdir()
    config = tmp_path / "app.sic"
    config.write_text(
        '''
        goal app: App::web = {
            title: "Test App",
            host: "127.0.0.1",
            port: 8123,
            output: ".out",
            pages: ["page.sic"],
            backend: "backend"
        }
        ''',
        encoding="utf-8",
    )
    (tmp_path / "page.sic").write_text(
        '''
        goal page: Page::web = {
            output: "index.html",
            title: "Start",
            html: text::web(greet::backend(name: "SIC")),
            css: "",
            js: "sic.call(\\\"greet\\\", {name: \\\"Ada\\\"});"
        }
        ''',
        encoding="utf-8",
    )
    (backend / "greet.sic").write_text(
        'goal greet: String = "Hallo " + (name: String)\n', encoding="utf-8"
    )
    return config


def test_minimal_typed_app_uses_web_defaults(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "effects.sic").write_text(
        "effect Changed: String\n", encoding="utf-8"
    )
    config_path = tmp_path / "app.sic"
    config_path.write_text(
        '''
        goal app: App::web = {
            port: 8000,
            pages: [],
            backend: "backend"
        }
        ''',
        encoding="utf-8",
    )
    config = load_web_config(config_path)
    assert config.title == "SIC App"
    assert config.host == "127.0.0.1"
    assert config.output == tmp_path / ".out"
    assert config.backend == "backend"
    assert config.backend_programs[0].module == "effects"


def test_sic_web_config_and_static_build(tmp_path):
    config_path = web_project(tmp_path)
    config = load_web_config(config_path)
    assert config.port == 8123
    assert [item.symbol for item in config.backend_programs] == ["greet"]

    generated = build_web(config_path)
    assert generated == [tmp_path / ".out" / "index.html"]
    document = generated[0].read_text(encoding="utf-8")
    assert "Hallo SIC" in document
    assert "window.sic = {call, actions: definitions}" in document
    assert '"greet":{"transport":"websocket"}' in document
    assert 'console.info("[SIC] Aktion gesendet"' in document


def test_web_goal_requires_standard_library_type(tmp_path):
    config_path = web_project(tmp_path)
    page_path = tmp_path / "page.sic"
    page_path.write_text(
        '''
        goal page = {
            output: "index.html",
            title: "Start",
            html: text::web(""),
            css: "",
            js: ""
        }
        ''',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="View::web oder Page::web annotiert"):
        build_web(config_path)


def test_page_type_requires_all_fields(tmp_path):
    config_path = web_project(tmp_path)
    page_path = tmp_path / "page.sic"
    page_path.write_text(
        '''
        goal page: Page::web = {
            output: "index.html",
            title: "Start",
            html: text::web(""),
            css: ""
        }
        ''',
        encoding="utf-8",
    )
    with pytest.raises(LangTypeError, match="Record fehlt Feld 'js'"):
        build_web(config_path)


def test_websocket_recomputes_live_view_after_file_effect(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    config_path = tmp_path / "app.sic"
    config_path.write_text(
        '''
        goal app: App::web = {
            port: 8000,
            pages: ["page.sic"],
            backend: "backend"
        }
        ''',
        encoding="utf-8",
    )
    (tmp_path / "page.sic").write_text(
        'goal view: View::web = Text::web(read_text::files::std("value.txt"))',
        encoding="utf-8",
    )
    (backend / "set_value.sic").write_text(
        'goal setValue: Bool = write_text::files::std(value: String, "value.txt")',
        encoding="utf-8",
    )
    (tmp_path / "value.txt").write_text("vorher", encoding="utf-8")

    app = create_app(config_path)
    with TestClient(app) as client:
        with client.websocket_connect("/__sic_ws?page=/") as websocket:
            assert websocket.receive_json() == {"type": "replace", "html": "vorher"}
            websocket.send_json({
                "type": "call", "id": "1", "name": "setValue",
                "values": {"value": "nachher"},
            })
            assert websocket.receive_json() == {
                "type": "result", "id": "1", "result": True,
            }
            assert websocket.receive_json() == {"type": "replace", "html": "nachher"}


def test_all_backend_goals_are_discovered_as_websocket_actions(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    config_path = tmp_path / "app.sic"
    config_path.write_text(
        '''
        goal app: App::web = {
            port: 8000,
            pages: ["page.sic"],
            backend: "backend"
        }
        ''',
        encoding="utf-8",
    )
    (tmp_path / "page.sic").write_text(
        'goal view: View::web = Text::web("bereit")', encoding="utf-8"
    )
    for name in ("createValue", "updateValue", "deleteValue"):
        (backend / f"{name}.sic").write_text(
            f'goal {name}: String = request.method: String', encoding="utf-8"
        )

    app = create_app(config_path)
    with TestClient(app) as client:
        with client.websocket_connect("/__sic_ws?page=/") as websocket:
            assert websocket.receive_json()["type"] == "replace"
            for index, name in enumerate(("createValue", "updateValue", "deleteValue"), 1):
                websocket.send_json({
                    "type": "call", "id": str(index),
                    "name": name, "values": {"id": index},
                })
                assert websocket.receive_json() == {
                    "type": "result", "id": str(index), "result": "WS",
                }


def test_view_source_dependencies_exclude_unrelated_backend(tmp_path):
    config_path = web_project(tmp_path)
    unrelated = tmp_path / "backend" / "unrelated.sic"
    unrelated.write_text('goal unrelated: String = "x"', encoding="utf-8")
    config = load_web_config(config_path)
    registry = _project_registry(
        config.root, config.backend, config.backend_programs
    )
    page = tmp_path / "page.sic"
    checked = compile_program(page.read_text(encoding="utf-8"), registry)
    dependencies = _view_source_dependencies(checked, page, config)
    assert (tmp_path / "backend" / "greet.sic").resolve() in dependencies
    assert unrelated.resolve() not in dependencies


def test_frontend_source_change_refreshes_open_view(tmp_path):
    config_path = web_project(tmp_path)
    app = create_app(config_path)
    page = tmp_path / "page.sic"
    with TestClient(app) as client:
        with client.websocket_connect("/__sic_ws?page=/") as websocket:
            assert "Hallo SIC" in websocket.receive_json()["html"]
            source = page.read_text(encoding="utf-8").replace(
                'name: "SIC"', 'name: "Frontend"'
            )
            page.write_text(source, encoding="utf-8")
            update = websocket.receive_json()
            assert update["type"] == "replace"
            assert "Hallo Frontend" in update["html"]


def test_backend_dependency_change_refreshes_open_view(tmp_path):
    config_path = web_project(tmp_path)
    app = create_app(config_path)
    backend = tmp_path / "backend" / "greet.sic"
    with TestClient(app) as client:
        with client.websocket_connect("/__sic_ws?page=/") as websocket:
            assert "Hallo SIC" in websocket.receive_json()["html"]
            backend.write_text(
                'goal greet: String = "Neu " + (name: String)\n',
                encoding="utf-8",
            )
            update = websocket.receive_json()
            assert update["type"] == "replace"
            assert "Neu SIC" in update["html"]


def test_websocket_backend_hot_reload(tmp_path):
    config_path = web_project(tmp_path)
    app = create_app(config_path)
    source = tmp_path / "backend" / "greet.sic"
    with TestClient(app) as client:
        with client.websocket_connect("/__sic_ws?page=/") as websocket:
            websocket.receive_json()
            websocket.send_json({
                "type": "call", "id": "1", "name": "greet",
                "values": {"name": "Ada"},
            })
            assert websocket.receive_json()["result"] == "Hallo Ada"
            source.write_text(
                'goal greet: String = "Hi " + (name: String) + "!"\n',
                encoding="utf-8",
            )
            websocket.send_json({
                "type": "call", "id": "2", "name": "greet",
                "values": {"name": "Ada"},
            })
            assert websocket.receive_json()["result"] == "Hi Ada!"
