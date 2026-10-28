import numpy as np
import pytest

from sic.lang import LangConstraint


class FakeTokenizer:
    eos_token_id = 0
    all_special_ids = [0, 11]

    def __init__(self):
        self._vocab = {
            "<eos>": 0,
            "goal": 1,
            " result": 2,
            ": Int": 3,
            " =": 4,
            " 1": 5,
            "]": 6,
            " value": 7,
            " let": 8,
            "▁value": 9,
            " = 2": 10,
            "<special>": 11,
            "goal total: Int = orders: List<Order>": 12,
            " orders": 13,
            ": List<Order>": 14,
            " = []": 15,
        }

    def get_vocab(self):
        return self._vocab

    def convert_tokens_to_string(self, tokens):
        return "".join(" value" if token == "▁value" else token for token in tokens)


def accept(constraint, *token_ids):
    for token_id in token_ids:
        assert constraint.allowed_token_mask()[token_id]
        constraint.accept_token(token_id)


def test_mask_only_allows_valid_next_token_fragments():
    constraint = LangConstraint(FakeTokenizer(), vocab_size=18)
    mask = constraint.allowed_token_mask()

    assert mask.dtype == np.bool_
    assert mask.shape == (18,)
    assert mask[1]  # goal
    assert not mask[8]  # let darf nicht vor seiner ersten Anforderung stehen
    assert not mask[2]  # result kann kein erstes Schlüsselwort sein
    assert not mask[0]  # EOS und andere Spezialtokens sind ausgeschlossen
    assert not mask[11]
    assert not mask[17]  # gepolsterte Modell-IDs sind ausgeschlossen


def test_complete_typed_program_finishes_constraint():
    constraint = LangConstraint(FakeTokenizer())
    accept(constraint, 1, 2, 3, 4, 5)

    assert constraint.source == "goal result: Int = 1"
    assert not constraint.is_complete()  # Der Ausdruck könnte noch weitergehen.
    assert constraint.allowed_token_mask()[0]  # EOS bestätigt den Abschluss.
    constraint.accept_token(0)
    assert constraint.is_complete()
    assert constraint.checked_program is not None
    assert constraint.checked_program.type_of("result") == "Int"


def test_syntactically_complete_program_waits_for_missing_definition():
    constraint = LangConstraint(FakeTokenizer())
    accept(constraint, 1, 2, 3, 4, 7)

    assert constraint.state.is_complete()
    assert not constraint.is_complete()

    # Beide IDs dekodieren zum selben Text und müssen gemeinsam erlaubt sein.
    mask = constraint.allowed_token_mask()
    assert mask[8]
    constraint.accept_token(8)
    mask = constraint.allowed_token_mask()
    assert mask[7] and mask[9]
    constraint.accept_token(7)
    accept(constraint, 10)
    assert not constraint.is_complete()
    assert constraint.allowed_token_mask()[0]
    constraint.accept_token(0)
    assert constraint.is_complete()


def test_mask_rejects_redundant_annotation_after_typed_first_use():
    constraint = LangConstraint(FakeTokenizer())
    accept(constraint, 12, 8, 13)
    assert not constraint.allowed_token_mask()[14]
    with pytest.raises(ValueError):
        constraint.accept_token(14)
    assert constraint.allowed_token_mask()[15]


def test_invalid_or_special_token_is_rejected_without_state_change():
    constraint = LangConstraint(FakeTokenizer())
    before = constraint.source
    with pytest.raises(ValueError):
        constraint.accept_token(6)
    assert constraint.source == before
    with pytest.raises(ValueError):
        constraint.accept_token(0)


def test_mask_is_cached_defensively_and_resettable():
    constraint = LangConstraint(FakeTokenizer())
    first = constraint.allowed_token_mask()
    first[:] = False
    assert constraint.allowed_token_mask()[1]

    accept(constraint, 1)
    constraint.reset()
    assert constraint.source == ""
    assert constraint.allowed_token_mask()[1]
