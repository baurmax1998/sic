"""Vollständige transitive Abhängigkeitsbäume für SIC-Dateien."""
from __future__ import annotations

from dataclasses import dataclass

from ..checker import CheckedProgram
from ..registry import ModuleRegistry
from .analysis import _interface_type, _program_imports, _type_ref
from .imports import _type_import_paths


@dataclass
class _DependencyNode:
    label: str
    children: list["_DependencyNode"]


def render_dependency_tree(
    checked: CheckedProgram, source: str, registry: ModuleRegistry | None = None,
) -> str:
    """Rendert den vollständigen Baum inklusive transitiver Imports."""
    from ..dependencies import expression_names

    expanded_bindings: set[tuple[int, str]] = set()
    expanded_imports: set[tuple[str, ...]] = set()

    def import_node(imported: dict[str, object]) -> _DependencyNode:
        path = tuple(imported["path"])
        label = f"import {imported['name']}"
        if path in expanded_imports:
            return _DependencyNode(label + " (shared)", [])
        expanded_imports.add(path)
        if registry is None:
            return _DependencyNode(label, [])
        symbol, origin = path[0], path[1:]
        children: list[_DependencyNode] = []
        if registry.has_calculation(symbol, origin):
            spec = registry.resolve_calculation(symbol, origin)
            children.append(binding_node(spec.checked, spec.symbol))
        elif registry.has_function(symbol, origin):
            external = registry.resolve(symbol, origin)
            for dependency in _type_import_paths(external.type):
                if dependency != path:
                    children.append(import_node({
                        "name": ".".join(reversed(dependency)),
                        "path": dependency,
                    }))
        elif registry.has_type(symbol, origin):
            imported_type = registry.resolve_type(symbol, origin)
            for dependency in _type_import_paths(imported_type):
                if dependency != path:
                    children.append(import_node({
                        "name": ".".join(reversed(dependency)),
                        "path": dependency,
                    }))
        return _DependencyNode(label, children)

    def binding_node(active: CheckedProgram, name: str) -> _DependencyNode:
        bindings = {binding.name: binding for binding in active.program.bindings}
        source_order = {
            binding.name: index for index, binding in enumerate(active.program.bindings)
        }
        binding = bindings[name]
        kind = "goal" if binding.is_goal else "let"
        label = f"{kind} {name}: {_interface_type(active.bindings[name])}"
        key = (id(active), name)
        if key in expanded_bindings:
            return _DependencyNode(label + " (shared)", [])
        expanded_bindings.add(key)
        children: list[_DependencyNode] = []
        dependencies = expression_names(binding.value)
        ordered = sorted(
            dependencies,
            key=lambda item: (
                0 if item in source_order else 1,
                source_order.get(item, 0),
                item,
            ),
        )
        for dependency in ordered:
            if dependency in bindings:
                children.append(binding_node(active, dependency))
            else:
                type_ = active.inputs.get(dependency)
                rendered = _interface_type(type_) if type_ is not None else "unknown"
                children.append(_DependencyNode(f"input {dependency}: {rendered}", []))
        for imported in _program_imports(binding):
            children.append(import_node(imported))
        errors = sorted(
            active.direct_errors.get(name, ()),
            key=lambda item: (item.name, item.identity),
        )
        for error in errors:
            payload = f"({_interface_type(error.payload)})" if error.payload else ""
            label = f"throws {error.name}{payload}"
            if error.identity[:1] != ("__local__",) and len(error.identity) > 1:
                label += " from " + ".".join(reversed(error.identity[:-1]))
            children.append(_DependencyNode(label, []))
        return _DependencyNode(label, children)

    if checked.program.bindings:
        root_children = [binding_node(checked, checked.program.goal.name)]
    else:
        root_children = [
            _DependencyNode(f"effect {effect.name}: {_type_ref(effect.payload)}", [])
            for effect in checked.program.effects
        ]
    root = _DependencyNode(source, root_children)
    lines = [root.label]

    def append(node: _DependencyNode, prefix: str, last: bool) -> None:
        lines.append(prefix + ("└── " if last else "├── ") + node.label)
        child_prefix = prefix + ("    " if last else "│   ")
        for index, child in enumerate(node.children):
            append(child, child_prefix, index == len(node.children) - 1)

    for index, child in enumerate(root.children):
        append(child, "", index == len(root.children) - 1)
    return "\n".join(lines) + "\n"
