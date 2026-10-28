"""Kommandozeile für Prüfen, Ausführen und lokale Codegenerierung."""
from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any

from .lang import LangConstraint, LangError, compile_program, run as run_program
from .lang.stdlib import standard_registry


LANG_SYSTEM_PROMPT = """Erzeuge ausschließlich Quelltext der zielorientierten Sprache.
Ein Programm enthält genau ein `goal name: Typ = Ausdruck` und optional `let`-Definitionen.
Typen sind Bool, Int, Float, String, T?, List<T> und Map<K, V>. Antworte ohne Markdown oder Erklärung.
"""


def _print_value(value: Any) -> None:
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif isinstance(value, bool):
        print(str(value).lower())
    else:
        print(value)


def _source(path: str) -> tuple[Path, str]:
    file = Path(path)
    if file.suffix != ".sic":
        raise ValueError("SIC-Quelldateien benötigen die Endung .sic")
    return file, file.read_text(encoding="utf-8")


def command_check(args: argparse.Namespace) -> int:
    file, source = _source(args.file)
    try:
        checked = compile_program(source, standard_registry(file.parent))
    except LangError as exc:
        print(exc.diagnostic(source, str(file)), file=sys.stderr)
        return 1
    if checked.program.bindings:
        print(f"OK: goal {checked.program.goal.name}: {checked.type_of(checked.program.goal.name)}")
    else:
        names = ", ".join(effect.name for effect in checked.program.effects)
        print(f"OK: effects {names}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("uvicorn.error.sic").setLevel(args.log_level.upper())
    file, source = _source(args.file)
    try:
        result = run_program(source, standard_registry(file.parent))
    except LangError as exc:
        print(exc.diagnostic(source, str(file)), file=sys.stderr)
        return 1
    _print_value(result.value)
    return 0


def command_generate(args: argparse.Namespace) -> int:
    try:
        from src.llm import DEFAULT_MODEL, MLXModelBackend, generate
    except ImportError:
        # Bei parallelen Entwicklungs-Checkouts ist lokal_llm ein
        # Schwesterprojekt; installiert wird es regulär als `lokal-llm`.
        sibling = Path(__file__).resolve().parents[3] / "lokal_llm"
        if sibling.is_dir():
            sys.path.insert(0, str(sibling))
        try:
            from src.llm import DEFAULT_MODEL, MLXModelBackend, generate
        except ImportError as exc:
            raise ValueError(
                "`sic generate` benötigt das separat installierte lokal-llm-Projekt"
            ) from exc

    backend = MLXModelBackend(args.model or DEFAULT_MODEL)
    registry = standard_registry(Path.cwd())
    constraint = LangConstraint(backend.tokenizer, backend.vocab_size, registry=registry)
    trace = generate(
        backend=backend,
        constraint=constraint,
        schema=None,
        prompt=args.prompt,
        system_prompt=LANG_SYSTEM_PROMPT,
        output_validator=lambda source: bool(compile_program(source, registry)),
        temperature=args.temperature,
        top_p=args.top_p,
        seed=args.seed,
        max_new_tokens=args.max_tokens,
    )
    if trace.status != "abgeschlossen":
        print(trace.error or trace.text, file=sys.stderr)
        return 1
    if args.output:
        output = Path(args.output)
        if output.suffix != ".sic":
            raise ValueError("Ausgabedateien benötigen die Endung .sic")
        output.write_text(trace.text + "\n", encoding="utf-8")
    else:
        print(trace.text)
    return 0


def command_build(args: argparse.Namespace) -> int:
    from .web import build_web

    generated = build_web(args.config)
    for path in generated:
        print(path)
    return 0


def command_describe(args: argparse.Namespace) -> int:
    from .interfaces import describe_codebase

    generated = describe_codebase(args.path, args.output)
    for path in generated:
        print(path)
    return 0


def command_serve(args: argparse.Namespace) -> int:
    from .web import serve_web

    serve_web(args.config, reload=args.reload, log_level=args.log_level)
    return 0


def command_repl(args: argparse.Namespace) -> int:
    registry = standard_registry(Path.cwd())
    print("SIC REPL – Programm eingeben, mit leerer Zeile ausführen, :quit beendet.")
    lines: list[str] = []
    while True:
        try:
            line = input("... " if lines else ">>> ")
        except EOFError:
            print()
            return 0
        if not lines and line.strip() in {":q", ":quit"}:
            return 0
        if line.strip():
            lines.append(line)
            continue
        if not lines:
            continue
        source = "\n".join(lines)
        lines.clear()
        try:
            _print_value(run_program(source, registry).value)
        except LangError as exc:
            print(f"Fehler: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sic", description="Zielorientierte Programmiersprache")
    commands = parser.add_subparsers(dest="command", required=True)

    check_parser = commands.add_parser("check", help="Programm statisch prüfen")
    check_parser.add_argument("file")
    check_parser.set_defaults(handler=command_check)

    run_parser = commands.add_parser("run", help="Programm ausführen")
    run_parser.add_argument("file")
    run_parser.add_argument(
        "--log-level", choices=("debug", "info", "warning", "error"),
        default="warning",
    )
    run_parser.set_defaults(handler=command_run)

    generate_parser = commands.add_parser("generate", help="Programm mit lokalem LLM erzeugen")
    generate_parser.add_argument("prompt")
    generate_parser.add_argument("-o", "--output")
    generate_parser.add_argument("--model")
    generate_parser.add_argument("--temperature", type=float, default=0.0)
    generate_parser.add_argument("--top-p", type=float, default=1.0)
    generate_parser.add_argument("--seed", type=int, default=0)
    generate_parser.add_argument("--max-tokens", type=int, default=256)
    generate_parser.set_defaults(handler=command_generate)

    web_build_parser = commands.add_parser("build", help="SIC-Webseiten zu HTML/CSS/JS bauen")
    web_build_parser.add_argument("config", nargs="?", default="app.sic")
    web_build_parser.set_defaults(handler=command_build)

    describe_parser = commands.add_parser(
        "describe", aliases=["interface"],
        help="Schnittstellen einer SIC-Codebasis nach .out/i schreiben",
    )
    describe_parser.add_argument("path", nargs="?", default=".")
    describe_parser.add_argument("-o", "--output")
    describe_parser.set_defaults(handler=command_describe)

    serve_parser = commands.add_parser("serve", help="SIC-Webprojekt mit FastAPI starten")
    serve_parser.add_argument("config", nargs="?", default="app.sic")
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.add_argument(
        "--log-level", choices=("debug", "info", "warning", "error"),
        default="info",
    )
    serve_parser.set_defaults(handler=command_serve)

    repl_parser = commands.add_parser("repl", help="Interaktive Sitzung starten")
    repl_parser.set_defaults(handler=command_repl)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (LangError, OSError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
