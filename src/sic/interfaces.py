"""Kompatibilitätsfassade für die SIC-Beschreibungswerkzeuge.

Die Implementierung liegt aufgeteilt unter :mod:`sic.lang.tooling`, damit
Analyse, Rendering, Importauflösung und Projektorchestrierung unabhängig
weiterentwickelt werden können.
"""

from .lang.tooling import (
    describe_codebase,
    describe_program,
    render_dependency_tree,
    render_interface,
)

__all__ = [
    "describe_codebase",
    "describe_program",
    "render_dependency_tree",
    "render_interface",
]
