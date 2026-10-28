"""Kleine Standardbibliothek für Datei-, JSON- und Konsolenoperationen."""
from __future__ import annotations
import html
import json
from pathlib import Path
import re
from typing import Any

from .effects import ExternalAutoListener, ExternalEffectOutput
from .registry import ModuleRegistry
from .types import (
    BOOL, INT, STRING, FunctionType, ListType, MapType, Primitive, RecordType, TypeVariable,
)


def standard_registry(root: str | Path | None = None) -> ModuleRegistry:
    """Erzeugt ein Register; relative Dateipfade bleiben optional unter ``root``."""
    base = Path(root).resolve() if root is not None else None
    registry = ModuleRegistry()

    def resolve_path(raw: str) -> Path:
        path = Path(raw)
        if base is None:
            return path
        resolved = (base / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"Dateipfad verlässt das erlaubte Wurzelverzeichnis: {raw}") from exc
        return resolved

    def read_json(path: str) -> Any:
        with resolve_path(path).open(encoding="utf-8") as handle:
            return json.load(handle)

    def write_json(value: Any, path: str) -> bool:
        with resolve_path(path).open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return True

    def read_text(path: str) -> str:
        return resolve_path(path).read_text(encoding="utf-8")

    def write_text(value: str, path: str) -> bool:
        resolve_path(path).write_text(value, encoding="utf-8")
        return True

    def print_value(value: Any) -> Any:
        print(value)
        return value

    html_name = re.compile(r"^[A-Za-z][A-Za-z0-9:-]*$")
    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def html_text(value: str) -> str:
        return html.escape(value, quote=True)

    def html_element(tag: str, attributes: dict[str, str], children: list[str]) -> str:
        if not html_name.fullmatch(tag):
            raise ValueError(f"Ungültiger HTML-Tag: {tag}")
        rendered_attributes: list[str] = []
        for name, value in attributes.items():
            if not html_name.fullmatch(name):
                raise ValueError(f"Ungültiges HTML-Attribut: {name}")
            rendered_attributes.append(f' {name}="{html.escape(value, quote=True)}"')
        opening = f"<{tag}{''.join(rendered_attributes)}>"
        if tag.lower() in void_tags:
            if children:
                raise ValueError(f"Void-Element <{tag}> darf keine Kinder besitzen")
            return opening
        return opening + "".join(children) + f"</{tag}>"

    view_type = Primitive("View::web")
    component_type = Primitive("Component::web")
    app_type = RecordType("App::web", {
        "port": INT,
        "pages": ListType(STRING),
        "backend": STRING,
    }, closed=True)

    file_changed = registry.register_effect(
        "FileChanged", ("files", "std"), STRING
    )

    def canonical_path(raw: str) -> str:
        return str(resolve_path(raw).resolve())

    json_value = TypeVariable(-1)
    printed_value = TypeVariable(-2)
    registry.register(
        "read_json", ("files", "std"), FunctionType([STRING], json_value),
        read_json, ("path",),
        automatic_listeners=(
            ExternalAutoListener(file_changed, "path", canonical_path),
        ),
    )
    registry.register(
        "write_json", ("files", "std"), FunctionType([json_value, STRING], BOOL),
        write_json, ("value", "path"),
        effect_outputs=(
            ExternalEffectOutput("fileChanged", file_changed, "path", canonical_path),
        ),
    )
    registry.register(
        "read_text", ("files", "std"), FunctionType([STRING], STRING),
        read_text, ("path",),
        automatic_listeners=(
            ExternalAutoListener(file_changed, "path", canonical_path),
        ),
    )
    registry.register(
        "write_text", ("files", "std"), FunctionType([STRING, STRING], BOOL),
        write_text, ("value", "path"),
        effect_outputs=(
            ExternalEffectOutput("fileChanged", file_changed, "path", canonical_path),
        ),
    )
    registry.register(
        "print", ("console", "std"),
        FunctionType([printed_value], printed_value), print_value, ("value",),
    )
    html_type = Primitive("Html::web")
    registry.register_type("Html", ("web",), html_type)
    registry.register_type("View", ("web",), view_type)
    registry.register_type("Component", ("web",), component_type)
    registry.register_type("App", ("web",), app_type)
    registry.register_type(
        "Page", ("web",),
        RecordType("Page::web", {
            "output": STRING,
            "title": STRING,
            "html": html_type,
            "css": STRING,
            "js": STRING,
        }, closed=True),
    )
    # Web-Bausteine haben kurze, eindeutige Namen. Die längeren Pfade bleiben
    # vorerst als kompatible Aliase bestehen.
    for origin in (("web",), ("html", "web")):
        registry.register(
            "text", origin, FunctionType([STRING], html_type), html_text, ("value",),
        )
        registry.register(
            "element", origin,
            FunctionType(
                [STRING, MapType(STRING, STRING), ListType(html_type)], html_type
            ),
            html_element, ("tag", "attributes", "children"),
        )
    return registry
