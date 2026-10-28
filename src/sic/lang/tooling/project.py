"""Projektweite Erzeugung von Schnittstellen und Abhängigkeitsbäumen."""
from __future__ import annotations

from pathlib import Path

from .. import compile_program, standard_registry
from ..registry import ModuleRegistry
from .analysis import describe_program
from .dependencies import render_dependency_tree
from .imports import (
    _render_calculation_import, _render_effect_import, _render_external_import,
    _render_type_import,
    _type_import_paths,
)
from .rendering import render_interface


def _is_web_project(path: Path) -> Path | None:
    candidate = path if path.is_file() else path / "app.sic"
    return candidate if candidate.is_file() and candidate.name == "app.sic" else None


def _project_sources(config_path: Path) -> tuple[Path, list[Path], ModuleRegistry, Path]:
    # Der Import bleibt lokal, damit die Sprachwerkzeuge nicht von FastAPI abhängen.
    from ...web import _project_registry, load_web_config

    config = load_web_config(config_path)
    registry = _project_registry(
        config.root, config.backend, config.backend_programs
    )
    declared = [
        config_path.resolve(),
        *config.pages,
        *(program.source for program in config.backend_programs),
    ]
    discovered = sorted(
        item.resolve() for item in config.root.rglob("*.sic")
        if ".out" not in item.relative_to(config.root).parts
    )
    # Deklarierte Dateien kommen zuerst und erhalten den vollständigen
    # Projektkontext; zusätzliche SIC-Dateien der Codebasis werden ebenfalls
    # beschrieben, auch wenn sie noch nicht in app.sic eingebunden sind.
    unique = list(dict.fromkeys([*(path.resolve() for path in declared), *discovered]))
    return config.root, unique, registry, config.output / "i"


def _plain_sources(path: Path) -> tuple[Path, list[Path], ModuleRegistry, Path]:
    if path.is_file():
        if path.suffix != ".sic":
            raise ValueError("SIC-Quelldateien benötigen die Endung .sic")
        root, paths = path.parent, [path]
    elif path.is_dir():
        root = path
        paths = sorted(
            item for item in path.rglob("*.sic")
            if ".out" not in item.relative_to(path).parts
        )
    else:
        raise ValueError(f"Codebasis existiert nicht: {path}")
    if not paths:
        raise ValueError(f"Keine SIC-Dateien unter {path}")
    return root.resolve(), [item.resolve() for item in paths], standard_registry(root), root / ".out" / "i"


def describe_codebase(
    path: str | Path = ".", output: str | Path | None = None,
) -> list[Path]:
    """Beschreibt eine Datei oder Codebasis und schreibt gespiegelte ``.i``-Dateien.

    Bei einem Webprojekt werden die in ``app.sic`` deklarierten Module, Seiten
    und Endpunkte mit demselben Register wie beim Build analysiert.
    """
    requested = Path(path).resolve()
    config_path = _is_web_project(requested)
    if config_path is not None:
        root, paths, registry, default_output = _project_sources(config_path)
    else:
        root, paths, registry, default_output = _plain_sources(requested)
    output_root = Path(output).resolve() if output is not None else default_output
    tree_root = output_root.parent / "t"

    generated: list[Path] = []
    destinations: set[Path] = set()
    imported_paths: dict[tuple[str, ...], str] = {}
    for source_path in paths:
        relative = source_path.relative_to(root)
        checked = compile_program(source_path.read_text(encoding="utf-8"), registry)
        description = describe_program(checked, relative.as_posix())
        for imported in description["imports"]:
            path_tuple = tuple(imported["path"])
            imported_paths[path_tuple] = str(imported["name"])
        destination = output_root / relative.with_suffix(".i")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_interface(description), encoding="utf-8")
        generated.append(destination)
        destinations.add(destination.resolve())

        tree_destination = tree_root / relative.with_suffix("")
        tree_destination.parent.mkdir(parents=True, exist_ok=True)
        tree_destination.write_text(
            render_dependency_tree(checked, relative.as_posix(), registry),
            encoding="utf-8",
        )

    # Jeder Import erhält eine gleichnamige Schnittstellendatei. Abhängige
    # Typen solcher Schnittstellen werden rekursiv ergänzt; `web.App` zieht
    # beispielsweise auch `web.Endpoint` nach.
    pending = list(imported_paths)
    processed: set[tuple[str, ...]] = set()
    while pending:
        path_tuple = pending.pop(0)
        if path_tuple in processed:
            continue
        processed.add(path_tuple)
        package = ".".join(reversed(path_tuple))
        symbol, origin = path_tuple[0], path_tuple[1:]
        destination = output_root.joinpath(*reversed(path_tuple)).with_suffix(".i")
        if destination.resolve() in destinations:
            continue

        dependencies: list[tuple[str, ...]] = []
        if registry.has_calculation(symbol, origin):
            calculation = registry.resolve_calculation(symbol, origin)
            # Goals werden bereits in der Schnittstelle ihrer Quelldatei
            # beschrieben. Eine weitere, nach dem Goal benannte .i-Datei wäre
            # insbesondere bei abweichendem Datei- und Goalnamen ein Duplikat.
            if calculation.checked.program.goal.name == calculation.symbol:
                continue
            content = _render_calculation_import(calculation, path_tuple)
        elif registry.has_function(symbol, origin):
            external = registry.resolve(symbol, origin)
            dependencies = [
                path for path in _type_import_paths(external.type)
                if path != path_tuple
            ]
            content = _render_external_import(external, package, dependencies)
        elif registry.has_effect(symbol, origin):
            effect = registry.resolve_effect(symbol, origin)
            content = _render_effect_import(symbol, effect.payload, package)
        elif registry.has_type(symbol, origin):
            imported_type = registry.resolve_type(symbol, origin)
            dependencies = [
                path for path in _type_import_paths(imported_type)
                if path != path_tuple
            ]
            content = _render_type_import(
                symbol, imported_type, package, dependencies
            )
        else:  # Der Checker hätte unbekannte qualifizierte Namen bereits abgelehnt.
            continue

        for dependency in dependencies:
            if dependency not in processed:
                pending.append(dependency)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        generated.append(destination)
        destinations.add(destination.resolve())
    return generated
