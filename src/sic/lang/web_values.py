"""Interne, bereits maskierte Werte der SIC-Web-String-Builder."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebValue:
    """Sicheres Webfragment; normale Strings sind absichtlich nicht kompatibel."""

    html: str
    kind: str

    def __str__(self) -> str:
        return self.html


@dataclass
class WebHandler:
    callback: object
    component_id: str | None
    evaluator: object
