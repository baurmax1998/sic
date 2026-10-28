"""Tokenizer-Maske für inkrementell gültige Programme der Zielsprache."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import fields, is_dataclass
import re
from typing import Any

import numpy as np


class SchemaConstraint(ABC):
    """Minimale Schnittstelle für Token-Constraints."""

    @abstractmethod
    def allowed_token_mask(self) -> np.ndarray: ...

    @abstractmethod
    def accept_token(self, token_id: int) -> None: ...

    @abstractmethod
    def is_complete(self) -> bool: ...
from . import ast
from .checker import CheckedProgram
from .incremental import LangPrefixState
from .iterative import IncrementalCompiler
from .registry import ModuleRegistry


class LangConstraint(SchemaConstraint):
    """Beschränkt Modell-Tokens auf syntaktisch gültige Sprachpräfixe.

    Die Token-Texte werden mit derselben Tokenizer-Schnittstelle wie bei der
    JSON-Schema-Maske erzeugt. Ein Programm gilt erst dann als abgeschlossen,
    wenn es nicht nur syntaktisch vollständig ist, sondern auch die statische
    Typ- und Namensprüfung besteht.
    """

    def __init__(
        self,
        tokenizer: Any,
        vocab_size: int | None = None,
        *,
        registry: ModuleRegistry | None = None,
        source: str = "",
    ) -> None:
        vocab = tokenizer.get_vocab()
        if not vocab:
            raise ValueError("Tokenizer besitzt kein Vokabular")
        tokenizer_size = max(int(token_id) for token_id in vocab.values()) + 1
        self._vocab_size = int(vocab_size or tokenizer_size)
        if self._vocab_size < tokenizer_size:
            raise ValueError("Modellvokabular ist kleiner als das Tokenizervokabular")

        special_ids = {int(token_id) for token_id in getattr(tokenizer, "all_special_ids", [])}
        eos_id = getattr(tokenizer, "eos_token_id", None)
        self._eos_id = int(eos_id) if eos_id is not None else None
        if self._eos_id is not None:
            special_ids.add(self._eos_id)

        fragments: dict[str, list[int]] = {}
        for token, token_id_value in vocab.items():
            token_id = int(token_id_value)
            if token_id in special_ids or token_id >= self._vocab_size:
                continue
            fragment = tokenizer.convert_tokens_to_string([token])
            if fragment:
                fragments.setdefault(fragment, []).append(token_id)

        self._fragments = fragments
        self._fragment_trie: dict[str, Any] = {}
        for fragment, token_ids in fragments.items():
            node = self._fragment_trie
            for character in fragment:
                node = node.setdefault(character, {})
            node.setdefault("", []).extend(token_ids)
        self._token_fragments = {
            token_id: fragment
            for fragment, token_ids in fragments.items()
            for token_id in token_ids
        }
        self._registry = registry or ModuleRegistry()
        self._compiler = IncrementalCompiler(self._registry, source)
        self._cached_mask: np.ndarray | None = None
        self._completion_source: str | None = None
        self._checked_program: CheckedProgram | None = None
        self._terminated = False

    @property
    def source(self) -> str:
        return self._compiler.source

    @property
    def state(self) -> LangPrefixState:
        return self._compiler.state

    @property
    def checked_program(self) -> CheckedProgram | None:
        """Das geprüfte Programm, sobald ``is_complete`` erfolgreich war."""
        self.is_complete()
        return self._checked_program

    def allowed_token_mask(self) -> np.ndarray:
        if self._cached_mask is not None:
            return self._cached_mask.copy()

        mask = np.zeros(self._vocab_size, dtype=bool)
        if not self._terminated:
            # Gemeinsame Tokenpräfixe werden nur einmal geprüft. Sobald ein
            # Präfix ungültig ist, kann der gesamte Trie-Zweig entfallen.
            def visit(node: dict[str, Any], prefix: str) -> None:
                token_ids = node.get("")
                if token_ids and not self._is_redundant_annotation(prefix):
                    mask[np.asarray(token_ids, dtype=np.int64)] = True
                for character, child in node.items():
                    if character == "":
                        continue
                    candidate = prefix + character
                    if (
                        self._respects_definition_order_prefix(candidate)
                        and self._compiler.can_accept(candidate)
                    ):
                        visit(child, candidate)

            visit(self._fragment_trie, "")
            # Ein vollständiger Ausdruck wie `6` könnte noch zu `6 * 7`
            # erweitert werden. Nur EOS bestätigt deshalb den Abschluss.
            if self._eos_id is not None and self._program_is_complete():
                mask[self._eos_id] = True
        self._cached_mask = mask
        return mask.copy()

    def accept_token(self, token_id: int) -> None:
        token_id = int(token_id)
        if token_id == self._eos_id:
            if not self._program_is_complete():
                raise ValueError("EOS ist erst nach einem vollständigen Programm zulässig")
            self._terminated = True
            self._cached_mask = None
            return
        fragment = self._token_fragments.get(token_id)
        if fragment is None:
            raise ValueError(f"Token {token_id} besitzt kein zulässiges Textfragment")
        if (
            not self._respects_definition_order_prefix(fragment)
            or not self._compiler.can_accept(fragment)
            or self._is_redundant_annotation(fragment)
        ):
            raise ValueError(f"Token {token_id} ist im aktuellen Sprachzustand unzulässig")
        self._compiler.accept(fragment)
        self._cached_mask = None
        self._completion_source = None
        self._checked_program = None

    def _respects_definition_order_prefix(self, fragment: str) -> bool:
        if self.source.strip():
            return True
        candidate = (self.source + fragment).lstrip()
        return not candidate or "goal".startswith(candidate) or candidate.startswith("goal")

    def _is_redundant_annotation(self, fragment: str) -> bool:
        if not fragment.lstrip().startswith(":"):
            return False
        match = re.search(r"(?:^|\s)let\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", self.source)
        if match is None:
            return False
        name = match.group(1)
        prefix = self.source[:match.start()].rstrip()
        if not prefix:
            return False
        checked = LangPrefixState(prefix)
        if checked.program is None:
            return False

        def contains_requirement(value: object) -> bool:
            if isinstance(value, ast.Annotation):
                if isinstance(value.value, ast.Name) and value.value.name == name:
                    return True
            if is_dataclass(value):
                return any(
                    contains_requirement(getattr(value, descriptor.name))
                    for descriptor in fields(value)
                    if descriptor.name != "span"
                )
            if isinstance(value, tuple):
                return any(contains_requirement(item) for item in value)
            return False

        return contains_requirement(checked.program)

    def is_complete(self) -> bool:
        return self._terminated and self._program_is_complete()

    def _program_is_complete(self) -> bool:
        if not self._compiler.is_complete():
            return False
        self._completion_source = self.source
        self._checked_program = self._compiler.checked_program
        return self._checked_program is not None

    def reset(self, source: str = "") -> None:
        """Setzt dieselbe Constraint-Instanz für eine neue Generierung zurück."""
        self._compiler.reset(source)
        self._cached_mask = None
        self._completion_source = None
        self._checked_program = None
        self._terminated = False
