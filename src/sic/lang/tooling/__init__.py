"""Schnittstellen- und Abhängigkeitswerkzeuge für SIC-Codebasen."""

from .analysis import describe_program
from .dependencies import render_dependency_tree
from .highlighting import analyze_source
from .project import describe_codebase
from .rendering import render_interface

__all__ = [
    "describe_codebase",
    "describe_program",
    "analyze_source",
    "render_dependency_tree",
    "render_interface",
]
