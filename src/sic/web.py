"""FastAPI-Host und statischer Compiler für SIC-Webprojekte.

Die Webschicht bleibt bewusst klein: Konfiguration, Seiten und Backendlogik
sind SIC-Programme. Python übernimmt nur HTTP, Hot-Reload und das Schreiben
der erzeugten Browserdateien.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, fields, is_dataclass
import html
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any

from .lang import (
    Evaluator, LangCalculationError, LangError, compile_program, parse,
    standard_registry,
)
from .lang import ast
from .lang.effects import EffectMessage, EffectSubscription
from .lang.types import ListType, MapType, NullableType, Primitive, RecordType, Type, prune
from .lang.web_values import WebValue
from .lang.tooling import analyze_source


logger = logging.getLogger("uvicorn.error.sic")


@dataclass(frozen=True)
class BackendProgram:
    module: str
    symbol: str | None
    source: Path


@dataclass(frozen=True)
class WebConfig:
    title: str
    host: str
    port: int
    output: Path
    pages: tuple[Path, ...]
    backend: str
    backend_programs: tuple[BackendProgram, ...]
    root: Path


def _inside(root: Path, raw: str, label: str) -> Path:
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} verlässt das Projektverzeichnis: {raw}") from exc
    return path


def _string(record: dict[str, Any], name: str, context: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}.{name} muss ein nicht leerer String sein")
    return value


def _discover_backend(root: Path, package: str) -> tuple[BackendProgram, ...]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", package):
        raise ValueError("app.backend muss ein gültiger SIC-Paketname sein")
    directory = _inside(root, package, "app.backend")
    if not directory.is_dir():
        raise ValueError(f"Backend-Verzeichnis existiert nicht: {directory}")
    programs: list[BackendProgram] = []
    symbols: set[str] = set()
    for source in sorted(directory.rglob("*.sic")):
        program = parse(source.read_text(encoding="utf-8"))
        symbol = program.goal.name if program.bindings else None
        module = symbol or source.stem
        if symbol is not None and symbol in symbols:
            raise ValueError(f"Backend-Berechnung {symbol!r} ist mehrfach definiert")
        if symbol is not None:
            symbols.add(symbol)
        programs.append(BackendProgram(module, symbol, source))
    if not programs:
        raise ValueError(f"Keine SIC-Dateien im Backend-Verzeichnis {directory}")
    # Deklarationsmodule müssen vor Berechnungen registriert werden, die ihre
    # Effekte referenzieren.
    programs.sort(key=lambda item: (item.symbol is not None, str(item.source)))
    return tuple(programs)


def load_web_config(path: str | Path = "app.sic") -> WebConfig:
    """Wertet die SIC-Konfiguration aus und validiert ihre Web-Metadaten."""
    config_path = Path(path).resolve()
    root = config_path.parent
    source = config_path.read_text(encoding="utf-8")
    registry = standard_registry(root)
    checked = compile_program(source, registry)
    app_type = prune(checked.bindings[checked.program.goal.name])
    if not isinstance(app_type, RecordType) or app_type.name != "App::web":
        raise ValueError("Das Goal in app.sic muss als App::web annotiert sein")
    value = Evaluator(checked, registry).run().value
    if not isinstance(value, dict):
        raise ValueError("Das App-Goal muss einen Record liefern")
    removed = {"modules", "actions", "endpoints"} & set(value)
    if removed:
        name = sorted(removed)[0]
        raise ValueError(
            f"app.{name} wird nicht mehr unterstützt; verwende nur backend"
        )

    title = value.get("title", "SIC App")
    host = value.get("host", "127.0.0.1")
    if not isinstance(title, str) or not title:
        raise ValueError("app.title muss ein nicht leerer String sein")
    if not isinstance(host, str) or not host:
        raise ValueError("app.host muss ein nicht leerer String sein")
    port = value.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("app.port muss ein Int zwischen 1 und 65535 sein")
    output_raw = value.get("output", ".out")
    if not isinstance(output_raw, str) or not output_raw:
        raise ValueError("app.output muss ein nicht leerer String sein")
    output = _inside(root, output_raw, "app.output")

    raw_pages = value.get("pages", [])
    if not isinstance(raw_pages, list) or not all(isinstance(item, str) for item in raw_pages):
        raise ValueError("app.pages muss List<String> sein")
    backend = value.get("backend")
    if not isinstance(backend, str) or not backend:
        raise ValueError("app.backend muss ein nicht leerer Paketname sein")
    pages = tuple(_inside(root, item, "page") for item in raw_pages)
    return WebConfig(
        title, host, port, output, pages, backend,
        _discover_backend(root, backend), root,
    )


def _project_registry(
    root: Path, package: str,
    programs: tuple[BackendProgram, ...] | None = None,
    *, include_frontend: bool = False,
):
    registry = standard_registry(root)
    active = programs if programs is not None else _discover_backend(root, package)
    for program in active:
        registry.register_source(
            program.module, package,
            program.source.read_text(encoding="utf-8"),
        )
    if include_frontend:
        frontend = (root / "frontend").resolve()
        if frontend.is_dir():
            frontend_programs = [
                (source, source.read_text(encoding="utf-8"))
                for source in frontend.rglob("*.sic")
            ]
            frontend_programs.sort(
                key=lambda item: (
                    bool(parse(item[1]).bindings), str(item[0])
                )
            )
            for source, source_text in frontend_programs:
                program = parse(source_text)
                annotation = program.goal.annotation if program.bindings else None
                if (
                    annotation is not None and annotation.name in {"View", "Page"}
                    and annotation.origin == ("web",)
                ):
                    continue
                registry.register_source(
                    program.goal.name if program.bindings else source.stem,
                    "frontend", source_text,
                )
    return registry


def _view_source_dependencies(
    checked, page_source: Path, config: WebConfig,
) -> frozenset[Path]:
    """Ordnet den statisch erreichbaren Berechnungsgraphen Quelldateien zu."""
    from .lang.dependencies import expression_names

    by_module = {
        program.module: program.source.resolve()
        for program in config.backend_programs
    }
    frontend_by_module: dict[str, Path] = {}
    frontend = (config.root / "frontend").resolve()
    if frontend.is_dir():
        for source in frontend.rglob("*.sic"):
            program = parse(source.read_text(encoding="utf-8"))
            if program.bindings:
                frontend_by_module[program.goal.name] = source.resolve()
    dependencies: set[Path] = {page_source.resolve()}
    visited: set[tuple[int, str]] = set()

    def visit_value(value: object, active_checked) -> None:
        if isinstance(value, ast.Call):
            spec = active_checked.call_specs.get(id(value))
            if spec is not None:
                if spec.origin and spec.origin[-1] == config.backend:
                    source = by_module.get(spec.origin[0])
                    if source is not None:
                        dependencies.add(source)
                elif spec.origin and spec.origin[-1] == "frontend":
                    source = frontend_by_module.get(spec.symbol)
                    if source is not None:
                        dependencies.add(source)
                if spec.checked is not None:
                    visit_calculation(spec.checked, spec.symbol)
        if isinstance(value, ast.Expr) and is_dataclass(value):
            for descriptor in fields(value):
                if descriptor.name != "span":
                    visit_value(getattr(value, descriptor.name), active_checked)
        elif isinstance(value, ast.NamedArgument):
            visit_value(value.value, active_checked)
        elif isinstance(value, (tuple, list)):
            for item in value:
                if isinstance(item, tuple):
                    for nested in item:
                        visit_value(nested, active_checked)
                else:
                    visit_value(item, active_checked)

    def add_effect_modules(active_checked) -> None:
        effects = [
            *(output.effect for output in active_checked.effect_outputs),
            *(listener.effect for listener in active_checked.listeners),
        ]
        for effect in effects:
            identity = effect.identity
            if len(identity) >= 3 and identity[-1] == config.backend:
                source = by_module.get(identity[-2])
                if source is not None:
                    dependencies.add(source)

    def visit_calculation(active_checked, symbol: str) -> None:
        key = (id(active_checked), symbol)
        if key in visited:
            return
        visited.add(key)
        bindings = {item.name: item for item in active_checked.program.bindings}
        pending = [symbol]
        reached: set[str] = set()
        while pending:
            name = pending.pop()
            if name in reached or name not in bindings:
                continue
            reached.add(name)
            binding = bindings[name]
            visit_value(binding.value, active_checked)
            pending.extend(expression_names(binding.value))
        if symbol == active_checked.program.goal.name:
            for declaration in active_checked.program.emits:
                visit_value(declaration.payload, active_checked)
            for declaration in active_checked.program.listeners:
                if declaration.filter is not None:
                    visit_value(declaration.filter, active_checked)
        add_effect_modules(active_checked)

    visit_calculation(checked, checked.program.goal.name)
    return frozenset(dependencies)


def _coerce_http_value(value: Any, expected: Type | None) -> Any:
    """Konvertiert nur eindeutige HTTP-Strings anhand des geprüften SIC-Typs."""
    if expected is None:
        return value
    expected = prune(expected)
    if isinstance(expected, NullableType):
        return None if value is None else _coerce_http_value(value, expected.inner)
    if isinstance(expected, Primitive) and isinstance(value, str):
        if expected.name == "Int":
            try:
                return int(value)
            except ValueError:
                return value
        if expected.name == "Float":
            try:
                return float(value)
            except ValueError:
                return value
        if expected.name == "Bool" and value.lower() in {"true", "false"}:
            return value.lower() == "true"
    if isinstance(expected, RecordType) and isinstance(value, dict):
        return {
            name: _coerce_http_value(item, expected.fields.get(name))
            for name, item in value.items()
        }
    if isinstance(expected, MapType) and isinstance(value, dict):
        return {
            _coerce_http_value(key, expected.key): _coerce_http_value(item, expected.value)
            for key, item in value.items()
        }
    if isinstance(expected, ListType) and isinstance(value, list):
        return [_coerce_http_value(item, expected.element) for item in value]
    return value


class HotSicProgram:
    """Hält die letzte kompilierte Fassung und lädt Änderungen automatisch."""

    def __init__(
        self, source: Path, root: Path, package: str,
        programs: tuple[BackendProgram, ...], execution_lock: threading.RLock,
    ):
        self.source = source
        self.root = root
        self.package = package
        self.programs = programs
        self.execution_lock = execution_lock
        self._load_lock = threading.RLock()
        self._stamp: tuple[int, ...] | None = None
        self._checked = None
        self._registry = None
        self._load()

    def _load(self) -> None:
        sources = tuple(program.source for program in self.programs)
        stamp = tuple(source.stat().st_mtime_ns for source in sources)
        if stamp == self._stamp and self._checked is not None:
            return
        with self._load_lock:
            stamp = tuple(source.stat().st_mtime_ns for source in sources)
            if stamp == self._stamp and self._checked is not None:
                return
            source = self.source.read_text(encoding="utf-8")
            registry = _project_registry(
                self.root, self.package, self.programs
            )
            checked = compile_program(source, registry)
            self._registry = registry
            self._checked = checked
            self._stamp = stamp
            logger.info("[SIC] compiled source=%s", self.source)

    def invalidate(self) -> None:
        with self._load_lock:
            self._stamp = None

    def execute_result(self, arguments: dict[str, Any]):
        self._load()
        converted = {
            name: _coerce_http_value(value, self._checked.inputs.get(name))
            for name, value in arguments.items()
        }
        with self.execution_lock:
            # Evaluator-Zustand ist absichtlich pro Request frisch.
            evaluator = Evaluator(self._checked, self._registry, converted)
            try:
                return evaluator.run()
            except LangError as exc:
                # Erfolgreiche Unteroperationen können die Außenwelt bereits
                # verändert haben, auch wenn das umgebende Goal fehlschlägt.
                exc.effects = tuple(evaluator.outgoing_messages())  # type: ignore[attr-defined]
                raise

    def execute(self, arguments: dict[str, Any]) -> Any:
        return self.execute_result(arguments).value


class EffectHub:
    """Prozesslokale Verteilung an aktive View-Instanzen."""

    def __init__(self) -> None:
        self._views: dict[
            object, tuple[
                tuple[EffectSubscription, ...], frozenset[Path], asyncio.Queue[Any]
            ]
        ] = {}

    def replace(
        self, token: object, subscriptions: tuple[EffectSubscription, ...],
        sources: frozenset[Path], queue: asyncio.Queue[Any],
    ) -> None:
        self._views[token] = (subscriptions, sources, queue)
        logger.debug(
            "[SIC] subscriptions-updated view=%s count=%d",
            hex(id(token)), len(subscriptions),
        )

    def remove(self, token: object) -> None:
        self._views.pop(token, None)

    def publish(self, messages: tuple[EffectMessage, ...]) -> None:
        if not messages:
            return
        logger.info(
            "[SIC] effects-publish count=%d effects=%s active_views=%d",
            len(messages),
            ",".join("::".join(item.effect.identity) for item in messages),
            len(self._views),
        )
        matched = 0
        for subscriptions, _, queue in tuple(self._views.values()):
            if any(
                subscription.matches(message)
                for subscription in subscriptions for message in messages
            ) and queue.empty():
                queue.put_nowait(messages)
                matched += 1
        logger.info("[SIC] effects-matched views=%d", matched)

    def publish_sources(self, changed: frozenset[Path]) -> None:
        matched = 0
        for _, sources, queue in tuple(self._views.values()):
            if sources & changed and queue.empty():
                queue.put_nowait("source")
                matched += 1
        logger.info(
            "[SIC] sources-changed files=%s matched_views=%d",
            ",".join(str(path) for path in sorted(changed)), matched,
        )



class SourceWatcher:
    """Kleiner asynchroner Wächter für bereits laufende Entwicklungsserver."""

    def __init__(self, config_path: Path, config: WebConfig, interval: float = 0.2):
        self.config_path = config_path.resolve()
        self.config = config
        self.interval = interval
        self.snapshot = self._snapshot()

    def _paths(self) -> set[Path]:
        return {
            self.config_path,
            *(path.resolve() for path in self.config.root.rglob("*.sic")
              if self.config.output not in path.resolve().parents),
        }

    def _snapshot(self) -> dict[Path, tuple[int, int]]:
        result: dict[Path, tuple[int, int]] = {}
        for path in self._paths():
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            result[path] = (stat.st_mtime_ns, stat.st_size)
        return result

    async def run(self, callback) -> None:
        while True:
            await asyncio.sleep(self.interval)
            current = self._snapshot()
            changed = frozenset(
                path for path in set(self.snapshot) | set(current)
                if self.snapshot.get(path) != current.get(path)
            )
            self.snapshot = current
            if changed:
                callback(changed)


def _browser_runtime(programs: tuple[BackendProgram, ...]) -> str:
    public = {
        program.symbol: {"transport": "websocket"}
        for program in programs if program.symbol is not None
    }
    encoded = json.dumps(public, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""
const definitions = {encoded};
function definition(name) {{
  const value = definitions[name];
  if (!value) throw new Error(`Unbekanntes SIC-Goal: ${{name}}`);
  return value;
}}
const websocketProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const socket = new WebSocket(`${{websocketProtocol}}//${{location.host}}/__sic_ws?page=${{encodeURIComponent(location.pathname)}}`);
const pendingCalls = new Map();
let callSequence = 0;
const socketReady = new Promise((resolve, reject) => {{
  socket.addEventListener("open", () => {{
    console.info("[SIC] WebSocket verbunden");
    resolve();
  }}, {{once: true}});
  socket.addEventListener("error", () => reject(new Error("WebSocket-Verbindung fehlgeschlagen")), {{once: true}});
}});
async function analyze(source) {{
  await socketReady;
  const id = String(++callSequence);
  return new Promise((resolve, reject) => {{
    pendingCalls.set(id, {{resolve, reject}});
    socket.send(JSON.stringify({{type: "analyze", id, source}}));
  }});
}}
async function call(name, values = {{}}) {{
  definition(name);
  await socketReady;
  const id = String(++callSequence);
  return new Promise((resolve, reject) => {{
    pendingCalls.set(id, {{resolve, reject}});
    console.info("[SIC] Aktion gesendet", {{
      id, name, transport: definition(name).transport,
      method: definition(name).method || "WS"
    }});
    socket.send(JSON.stringify({{type: "call", id, name, values: {{...values}}}}));
  }});
}}
function hydrateSicBindings(container = document) {{
  const nodes = [];
  if (container instanceof HTMLTextAreaElement) nodes.push(container);
  if (container.querySelectorAll) nodes.push(...container.querySelectorAll("textarea"));
  for (const node of nodes) {{
    if (node.hasAttribute("sic:bind-value")) {{
      node.value = node.getAttribute("sic:bind-value") || "";
    }}
  }}
  document.dispatchEvent(new CustomEvent("sic:bindings-hydrated", {{
    detail: {{container}}
  }}));
}}
hydrateSicBindings();
socket.addEventListener("message", event => {{
  const message = JSON.parse(event.data);
  if (message.type === "replace") {{
    console.info("[SIC] View-Aktualisierung empfangen");
    const root = document.getElementById("sic-root");
    if (root) {{
      root.innerHTML = message.html;
      hydrateSicBindings(root);
    }}
    document.getElementById("sic-diagnostic")?.remove();
    return;
  }}
  if (message.type === "replace-component") {{
    const current = [...document.querySelectorAll("[data-sic-component]")]
      .find(node => node.getAttribute("data-sic-component") === message.component);
    if (current) {{
      current.outerHTML = message.html;
      const replacement = [...document.querySelectorAll("[data-sic-component]")]
        .find(node => node.getAttribute("data-sic-component") === message.component);
      if (replacement) hydrateSicBindings(replacement);
    }}
    return;
  }}
  if (message.type === "remove-component") {{
    const current = [...document.querySelectorAll("[data-sic-component]")]
      .find(node => node.getAttribute("data-sic-component") === message.component);
    current?.remove();
    return;
  }}
  if (message.type === "diagnostic") {{
    console.error("[SIC] Compilerfehler", message.detail);
    let diagnostic = document.getElementById("sic-diagnostic");
    if (!diagnostic) {{
      diagnostic = document.createElement("pre");
      diagnostic.id = "sic-diagnostic";
      diagnostic.style.cssText = "position:fixed;inset:auto 0 0 0;z-index:9999;margin:0;padding:12px;background:#5b1111;color:white;white-space:pre-wrap";
      document.body.appendChild(diagnostic);
    }}
    diagnostic.textContent = message.detail;
    return;
  }}
  const pending = pendingCalls.get(String(message.id));
  if (!pending) return;
  pendingCalls.delete(String(message.id));
  if (message.type === "result" || message.type === "analysis") {{
    if (message.type === "result") console.info("[SIC] Aktion abgeschlossen", {{id: message.id}});
    pending.resolve(message.result);
  }} else {{
    console.error("[SIC] Aktion fehlgeschlagen", message);
    const error = new Error(message.detail || message.error || "SIC-Aktion fehlgeschlagen");
    error.response = message;
    pending.reject(error);
  }}
}});
socket.addEventListener("close", () => {{
  console.warn("[SIC] WebSocket getrennt");
  for (const pending of pendingCalls.values()) {{
    pending.reject(new Error("WebSocket-Verbindung wurde geschlossen"));
  }}
  pendingCalls.clear();
}});
function show(name, value) {{
  document.querySelectorAll(`[data-sic-output="${{name}}"]`).forEach(node => {{
    node.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }});
}}
async function sendSicEvent(handler, value) {{
  await socketReady;
  socket.send(JSON.stringify({{type: "event", handler, value}}));
}}
function closestSicHandler(target, ...attributes) {{
  let node = target instanceof Element ? target : null;
  while (node) {{
    if (attributes.some(attribute => node.hasAttribute(attribute))) return node;
    node = node.parentElement;
  }}
  return null;
}}
document.addEventListener("input", event => {{
  const reactive = closestSicHandler(event.target, "sic:oninput");
  if (reactive) sendSicEvent(reactive.getAttribute("sic:oninput"), reactive.value);
}});
document.addEventListener("change", event => {{
  const target = closestSicHandler(event.target, "sic:onchange", "sic:oncheck");
  if (!target) return;
  const handler = target.getAttribute("sic:onchange") || target.getAttribute("sic:oncheck");
  sendSicEvent(handler, target.type === "checkbox" ? target.checked : target.value);
}});
document.addEventListener("submit", async event => {{
  const reactive = closestSicHandler(event.target, "sic:onsubmit");
  if (reactive) {{
    event.preventDefault();
    const values = [...new FormData(reactive).values()];
    sendSicEvent(reactive.getAttribute("sic:onsubmit"), values[0] || "");
    return;
  }}
  const form = event.target.closest("form[data-sic-submit]");
  if (!form) return;
  event.preventDefault();
  const name = form.dataset.sicSubmit;
  const values = Object.fromEntries(new FormData(form).entries());
  try {{
    const result = await call(name, values);
    show(name, result);
    document.dispatchEvent(new CustomEvent("sic:result", {{detail: {{name, result}}}}));
  }} catch (error) {{
    show(name, error.response || error.message);
    document.dispatchEvent(new CustomEvent("sic:error", {{detail: {{name, error}}}}));
  }}
}});
document.addEventListener("click", async event => {{
  const reactive = closestSicHandler(event.target, "sic:onclick");
  if (reactive) {{
    sendSicEvent(reactive.getAttribute("sic:onclick"), true);
    return;
  }}
  const button = event.target.closest("[data-sic-call]");
  if (!button) return;
  const name = button.dataset.sicCall;
  const values = button.dataset.sicArgs ? JSON.parse(button.dataset.sicArgs) : {{}};
  const result = await call(name, values);
  show(name, result);
  document.dispatchEvent(new CustomEvent("sic:result", {{detail: {{name, result}}}}));
}});
window.sic = {{call, analyze, actions: definitions}};
""".strip()


def build_web(config_path: str | Path = "app.sic") -> list[Path]:
    """Kompiliert SIC-Seitengoals zu eigenständigen HTML-Dateien."""
    config = load_web_config(config_path)
    config.output.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    runtime = _browser_runtime(config.backend_programs)
    for source_path in config.pages:
        registry = _project_registry(
            config.root, config.backend, config.backend_programs,
            include_frontend=True,
        )
        checked = compile_program(source_path.read_text(encoding="utf-8"), registry)
        page_type = prune(checked.bindings[checked.program.goal.name])
        is_view = isinstance(page_type, Primitive) and page_type.name == "View::web"
        is_page = isinstance(page_type, RecordType) and page_type.name == "Page::web"
        if not is_view and not is_page:
            raise ValueError(
                f"{source_path}: Das Goal muss als View::web oder Page::web annotiert sein"
            )
        value = Evaluator(checked, registry).run().value
        if is_view:
            page = {"html": value.html if isinstance(value, WebValue) else value}
        elif isinstance(value, dict):
            page = value
        else:
            raise ValueError(f"{source_path}: Das Page-Goal muss einen Record liefern")
        output_name = "index.html" if is_view else _string(page, "output", str(source_path))
        title = config.title if is_view else page.get("title", config.title)
        body = page.get("html", "")
        css = "" if is_view else page.get("css", "")
        script = "" if is_view else page.get("js", "")
        if not all(isinstance(value, str) for value in (title, body, css, script)):
            raise ValueError(f"{source_path}: title, html, css und js müssen Strings sein")
        destination = _inside(config.output, output_name, "page.output")
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = "\n".join([
            "<!doctype html>", '<html lang="de">', "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{html.escape(title)}</title>", f"<style>{css}</style>",
            "</head>", '<body><main id="sic-root">', body, "</main>",
            f"<script type=\"module\">{runtime}\n\n{script}</script>",
            "</body>", "</html>", "",
        ])
        destination.write_text(document, encoding="utf-8")
        generated.append(destination)
    return generated


def create_app(config_path: str | Path = "app.sic"):
    """Erzeugt eine FastAPI-App mit WebSocket-Aufrufen und Hot-Reload."""
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.concurrency import run_in_threadpool
        from fastapi.responses import FileResponse
    except ImportError as exc:  # pragma: no cover - verständlich bei Minimalinstallation
        raise RuntimeError("FastAPI fehlt; Projektabhängigkeiten erneut installieren") from exc

    config_path = Path(config_path).resolve()
    config = load_web_config(config_path)
    build_web(config_path)
    app = FastAPI(title=config.title)
    execution_lock = threading.RLock()  # schützt die vorläufige JSON-Dateipersistenz
    effect_hub = EffectHub()

    programs: dict[str, HotSicProgram] = {
        program.symbol: HotSicProgram(
            program.source, config.root, config.backend,
            config.backend_programs, execution_lock,
        )
        for program in config.backend_programs
        if program.symbol is not None
    }
    source_watcher = SourceWatcher(config_path, config)
    watcher_task: asyncio.Task | None = None

    def sources_changed(changed: frozenset[Path]) -> None:
        for name, program in programs.items():
            if program.source.resolve() in changed:
                logger.info("[SIC] backend-invalidated calculation=%s", name)
            # Jede Backend-Schnittstelle kann von einer anderen abhängen; der
            # nächste Aufruf baut deshalb den gemeinsamen Registry-Stand neu.
            if any(
                item.source.resolve() in changed
                for item in config.backend_programs
            ):
                program.invalidate()
        effect_hub.publish_sources(changed)

    async def start_source_watcher() -> None:
        nonlocal watcher_task
        watcher_task = asyncio.create_task(source_watcher.run(sources_changed))
        logger.info("[SIC] source-watcher started")

    async def stop_source_watcher() -> None:
        if watcher_task is not None:
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                pass
        logger.info("[SIC] source-watcher stopped")

    app.router.add_event_handler("startup", start_source_watcher)
    app.router.add_event_handler("shutdown", stop_source_watcher)

    def evaluate_live_page(
        pathname: str, state: dict[str, Any] | None = None,
        compiled: tuple[Path, Any, Any] | None = None,
    ):
        wanted = pathname.lstrip("/") or "index.html"
        candidates = [compiled] if compiled is not None else [
            (source_path, None, None) for source_path in config.pages
        ]
        for source_path, checked, registry in candidates:
            if checked is None or registry is None:
                registry = _project_registry(
                    config.root, config.backend, config.backend_programs,
                    include_frontend=True,
                )
                checked = compile_program(
                    source_path.read_text(encoding="utf-8"), registry
                )
            evaluator = Evaluator(checked, registry, state=state)
            with execution_lock:
                result = evaluator.run()
            page_type = prune(checked.bindings[checked.program.goal.name])
            is_view = isinstance(page_type, Primitive) and page_type.name == "View::web"
            if is_view:
                output, body = "index.html", result.value
            elif isinstance(result.value, dict):
                output = result.value.get("output", "index.html")
                body = result.value.get("html", "")
            else:
                continue
            if isinstance(body, WebValue):
                body = body.html
            if output == wanted:
                sources = _view_source_dependencies(checked, source_path, config)
                return (
                    body, result.subscriptions, sources, evaluator,
                    (source_path, checked, registry),
                )
        raise ValueError(f"Unbekannte SIC-Seite: {pathname}")

    async def execute_socket_call(websocket, message: dict[str, Any]) -> None:
        call_id = str(message.get("id", ""))
        name = message.get("name")
        values = message.get("values", {})
        if not isinstance(name, str) or name not in programs:
            await websocket.send_json({
                "type": "error", "id": call_id,
                "detail": f"Unbekanntes SIC-Goal: {name}",
            })
            return
        if not isinstance(values, dict):
            await websocket.send_json({
                "type": "error", "id": call_id,
                "detail": "Aktionswerte müssen ein Record sein",
            })
            return

        logger.info(
            "[SIC] websocket-action start id=%s name=%s",
            call_id, name,
        )
        request_value = {
            "method": "WS",
            "path": f"/__sic_action/{name}",
            "query": {},
            "pathParams": {},
            "headers": dict(websocket.headers),
            "body": values,
        }
        arguments: dict[str, Any] = {
            "request": request_value, **values,
        }
        try:
            result = await run_in_threadpool(
                programs[name].execute_result, arguments
            )
            effect_hub.publish(result.effects)
            value = result.value
            if (
                isinstance(value, dict) and type(value.get("status")) is int
                and "body" in value
            ):
                if value["status"] >= 400:
                    await websocket.send_json({
                        "type": "error", "id": call_id,
                        "status": value["status"], "detail": value["body"],
                    })
                    return
                value = value["body"]
            await websocket.send_json({
                "type": "result", "id": call_id, "result": value,
            })
            logger.info(
                "[SIC] websocket-action finish id=%s name=%s effects=%d",
                call_id, name, len(result.effects),
            )
        except LangCalculationError as exc:
            effect_hub.publish(getattr(exc, "effects", ()))
            logger.warning(
                "[SIC] websocket-action calculation-error id=%s name=%s error=%s",
                call_id, name, exc.name,
            )
            detail = exc.payload if exc.payload is not None else exc.name
            await websocket.send_json({
                "type": "error", "id": call_id,
                "error": exc.name, "detail": detail,
            })
        except LangError as exc:
            effect_hub.publish(getattr(exc, "effects", ()))
            logger.warning(
                "[SIC] websocket-action language-error id=%s name=%s detail=%s",
                call_id, name, exc,
            )
            await websocket.send_json({
                "type": "error", "id": call_id, "detail": str(exc),
            })
        except (OSError, ValueError) as exc:
            logger.exception(
                "[SIC] websocket-action runtime-error id=%s name=%s",
                call_id, name,
            )
            await websocket.send_json({
                "type": "error", "id": call_id, "detail": str(exc),
            })

    async def live_updates(websocket):
        await websocket.accept()
        token = object()
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1)
        pathname = websocket.query_params.get("page", "/")
        state: dict[str, Any] = {}
        compiled = None
        current_evaluator = None
        logger.info(
            "[SIC] websocket-connected view=%s page=%s client=%s",
            hex(id(token)), pathname, websocket.client,
        )

        async def refresh(
            *, full: bool, affected: set[str] | None = None,
            recompile: bool = False,
        ) -> None:
            nonlocal compiled, current_evaluator
            previous = current_evaluator
            try:
                rendered = await run_in_threadpool(
                    evaluate_live_page, pathname, state,
                    None if recompile else compiled,
                )
                body, subscriptions, sources, evaluator, compiled = rendered
            except (LangError, OSError, ValueError) as exc:
                logger.warning(
                    "[SIC] view-compile-error view=%s page=%s detail=%s",
                    hex(id(token)), pathname, exc,
                )
                await websocket.send_json({
                    "type": "diagnostic", "detail": str(exc),
                })
                return
            current_evaluator = evaluator
            effect_hub.replace(token, subscriptions, sources, queue)
            if full or previous is None or not previous.web_context.components:
                await websocket.send_json({"type": "replace", "html": body})
            else:
                targets = affected or set(previous.web_context.components)
                for component in sorted(targets):
                    html_value = evaluator.web_context.components.get(component)
                    if html_value is None:
                        await websocket.send_json({
                            "type": "remove-component", "component": component,
                        })
                    else:
                        await websocket.send_json({
                            "type": "replace-component", "component": component,
                            "html": html_value,
                        })
            logger.info(
                "[SIC] view-rendered view=%s page=%s listeners=%d html_bytes=%d",
                hex(id(token)), pathname, len(subscriptions), len(body.encode("utf-8")),
            )

        async def execute_analysis(message: dict[str, Any]) -> None:
            source = message.get("source")
            identifier = str(message.get("id", ""))
            if not isinstance(source, str):
                await websocket.send_json({
                    "type": "error", "id": identifier,
                    "detail": "Analyse benötigt Quelltext als String",
                })
                return
            registry = compiled[2] if compiled is not None else _project_registry(
                config.root, config.backend, config.backend_programs,
                include_frontend=True,
            )
            result = await run_in_threadpool(analyze_source, source, registry)
            await websocket.send_json({
                "type": "analysis", "id": identifier, "result": result,
            })

        async def execute_local_event(message: dict[str, Any]) -> None:
            nonlocal current_evaluator
            if current_evaluator is None:
                return
            identifier = message.get("handler")
            handler = current_evaluator.web_context.handlers.get(identifier)
            if handler is None:
                await websocket.send_json({
                    "type": "error", "id": str(identifier or ""),
                    "detail": "Unbekannte oder veraltete SIC-Eventbindung",
                })
                return
            event_evaluator = handler.evaluator
            before = len(event_evaluator.messages)
            current_evaluator.web_context.changed.clear()
            try:
                with execution_lock:
                    handler.callback(message.get("value"))
            except (LangError, OSError, ValueError) as exc:
                await websocket.send_json({
                    "type": "error", "id": str(identifier), "detail": str(exc),
                })
                return
            changed = set(current_evaluator.web_context.changed)
            context = current_evaluator.web_context
            affected: set[str] = set()
            for component, dependencies in context.dependencies.items():
                if dependencies & changed:
                    affected.add(component)
            for component, dependencies in context.binding_dependencies.items():
                relevant = dependencies & changed
                origin_is_current = bool(relevant) and all(
                    state.get(name) == message.get("value") for name in relevant
                )
                if relevant and (
                    component != handler.component_id or not origin_is_current
                ):
                    affected.add(component)
                elif relevant and context.dependencies.get(component, set()) & changed:
                    affected.add(component)
            produced = tuple(event_evaluator.messages[before:])
            if changed and context.root_dependencies & changed:
                await refresh(full=True)
            elif changed and affected:
                await refresh(full=False, affected=affected)
            local_effects = tuple(
                message for message in produced
                if message.effect.identity[-1:] == ("frontend",)
            )
            external_effects = tuple(
                message for message in produced if message not in local_effects
            )
            if local_effects:
                local_targets: set[str] = set()
                for subscription, component in context.effect_components:
                    if any(subscription.matches(message) for message in local_effects):
                        local_targets.add(component)
                sources = {
                    source for subscription, source in context.effect_sources
                    if any(subscription.matches(message) for message in local_effects)
                }
                for component, dependencies in context.dependencies.items():
                    if dependencies & sources:
                        local_targets.add(component)
                await refresh(full=False, affected=local_targets or None)
            if external_effects:
                effect_hub.publish(external_effects)

        initial_sources = frozenset({
            *(path.resolve() for path in config.pages),
            *(program.source.resolve() for program in config.backend_programs),
        })
        effect_hub.replace(token, (), initial_sources, queue)
        try:
            await refresh(full=True)
            while True:
                update = asyncio.create_task(queue.get())
                incoming = asyncio.create_task(websocket.receive())
                done, pending = await asyncio.wait(
                    {update, incoming}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if update in done:
                    reason = update.result()
                    if reason == "source":
                        await refresh(full=True, recompile=True)
                    else:
                        context = current_evaluator.web_context if current_evaluator else None
                        targets: set[str] = set()
                        sources: set[str] = set()
                        if context is not None:
                            for subscription, component in context.effect_components:
                                if any(subscription.matches(message) for message in reason):
                                    targets.add(component)
                            for subscription, source in context.effect_sources:
                                if any(subscription.matches(message) for message in reason):
                                    sources.add(source)
                            for component, dependencies in context.dependencies.items():
                                if dependencies & sources:
                                    targets.add(component)
                        await refresh(full=False, affected=targets or None)
                if incoming in done:
                    event = incoming.result()
                    if event.get("type") == "websocket.disconnect":
                        break
                    raw = event.get("text")
                    if raw is None:
                        await websocket.send_json({
                            "type": "error", "id": "",
                            "detail": "WebSocket-Nachricht muss JSON-Text sein",
                        })
                        continue
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        await websocket.send_json({
                            "type": "error", "id": "",
                            "detail": "Ungültiges JSON",
                        })
                        continue
                    if isinstance(message, dict) and message.get("type") == "call":
                        await execute_socket_call(websocket, message)
                    elif isinstance(message, dict) and message.get("type") == "analyze":
                        await execute_analysis(message)
                    elif isinstance(message, dict) and message.get("type") == "event":
                        await execute_local_event(message)
                    else:
                        await websocket.send_json({
                            "type": "error", "id": str(message.get("id", ""))
                            if isinstance(message, dict) else "",
                            "detail": "Unbekannte WebSocket-Nachricht",
                        })
        except WebSocketDisconnect:
            pass
        finally:
            effect_hub.remove(token)
            logger.info(
                "[SIC] websocket-disconnected view=%s page=%s",
                hex(id(token)), pathname,
            )

    # FastAPI wertet wegen ``from __future__ import annotations`` sonst den
    # lokal importierten WebSocket-Typ nicht auf.
    live_updates.__annotations__["websocket"] = WebSocket
    app.add_api_websocket_route("/__sic_ws", live_updates)

    index = config.output / "index.html"
    if index.exists():
        @app.get("/", include_in_schema=False)
        async def index_page():
            return FileResponse(index)

    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=config.output), name="static")
    return app


def serve_web(
    config_path: str | Path = "app.sic", *, reload: bool = False,
    log_level: str = "info",
) -> None:
    """Startet den Webserver. SIC-Backends benötigen keinen Prozess-Restart."""
    import uvicorn

    config_path = Path(config_path).resolve()
    config = load_web_config(config_path)
    numeric_level = getattr(logging, log_level.upper())
    logging.basicConfig(
        level=numeric_level,
        format="%(levelname)s %(name)s %(message)s",
    )
    logger.setLevel(numeric_level)
    logging.getLogger("uvicorn.error.sic.runtime").setLevel(numeric_level)
    if reload:
        # Uvicorns Prozess-Reload benötigt einen Importstring; SIC-Hot-Reload ist
        # ohnehin aktiv, daher wird diese Option nur als Hinweis behandelt.
        print("Hinweis: SIC-Backends werden bereits vor jedem Aufruf neu geprüft.")
    uvicorn.run(
        create_app(config_path), host=config.host, port=config.port,
        log_level=log_level,
    )
