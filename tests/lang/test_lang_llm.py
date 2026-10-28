"""Lokaler End-to-End-Test für sprachbeschränkte Codegenerierung."""
import pytest

from sic.lang import LangConstraint, run


LANG_SYSTEM_PROMPT = """Du erzeugst ausschließlich Quelltext in dieser Sprache:
- Ein Programm beginnt mit: goal <name>: <Typ> = <Ausdruck>
- Typen sind Int, Bool, String und List<T>.
- Ganzzahlen unterstützen +, - und *.
- Zusätzliche unveränderliche Werte beginnen mit: let <name> = <Ausdruck>
Antworte ohne Markdown, Erklärung oder Codeblock und beginne unmittelbar mit goal.
"""


@pytest.mark.integration
def test_local_llm_writes_and_executes_constrained_code(backend):
    from src.llm import generate

    constraint = LangConstraint(backend.tokenizer, backend.vocab_size)
    result = generate(
        backend=backend,
        constraint=constraint,
        schema=None,
        prompt=(
            "Schreibe ein möglichst kurzes Programm. Das Ziel soll answer heißen, "
            "den Typ Int besitzen und das Produkt aus 6 und 7 berechnen."
        ),
        system_prompt=LANG_SYSTEM_PROMPT,
        output_validator=lambda source: run(source).value,
        temperature=0,
        top_p=1,
        seed=0,
        max_new_tokens=64,
    )

    assert result.status == "abgeschlossen", result.error or result.text
    assert result.steps
    assert constraint.is_complete()
    assert result.text == constraint.source
    assert result.validation == {"custom": True, "value": 42}
    assert run(result.text).value == 42
    print("\nGenerierter Code:\n" + result.text)
