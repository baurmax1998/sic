# SIC Todo-Webdemo

```bash
sic build examples/todo/app.sic
sic serve examples/todo/app.sic
```

Danach: <http://127.0.0.1:8000>

Die statisch abgeleiteten Schnittstellen aller SIC-Dateien der Codebasis
lassen sich separat erzeugen:

```bash
sic describe examples/todo/app.sic
```

Dabei entstehen unter `.out/i/` gespiegelte, C-ähnliche `.i`-Dateien,
zum Beispiel `.out/i/backend/create_todo.i`. Verwendete Imports erhalten
ebenfalls eine auflösbare Datei, etwa `.out/i/std/files/write_json.i`. Die
Beschreibungen enthalten für jedes Goal und `let` die freien Eingaben,
überschreibbaren Zwischenwerte, typisierten Ausgänge sowie mögliche Fehler.
Zusätzlich entsteht pro SIC-Datei unter `.out/t/` ein vollständiger transitiver
Abhängigkeitsbaum, etwa `.out/t/frontend/app`. Er verfolgt lokale `let`s,
Eingaben, Fehler, Projektimporte und deren Standardbibliotheks- und Typimporte;
gemeinsam verwendete Teilbäume sind mit `shared` markiert.

## Struktur

```text
app.sic                 # Webprojekt und Routen
frontend/
  app.sic               # reaktive View::web
  todoEditor.sic        # in SIC definierte Component::web
  todoPreview.sic
  todoList.sic
  todoItem.sic
backend/
  effects.sic
  list_todos.sic
  create_todo.sic
  toggle_todo.sic
  delete_todo.sic
  todos.json
.out/                    # generierte Ausgabe (ignoriert)
```

Das typisierte `App::web` in `app.sic` enthält nur `port`, `pages` und
`backend: "backend"`. Alle SIC-Dateien unter `backend/` werden automatisch als
Backend-Paket entdeckt; `actions`, `modules` und HTTP-Endpunkte müssen nicht
registriert werden. Host, Titel und Ausgabeordner entstehen automatisch.
`frontend/app.sic` liefert direkt `View::web`. Editor, Vorschau, Liste und
Todo-Zeile sind sichere `Component::web`-String-Builder und vollständig in SIC
definiert. Eingefügte Werte werden automatisch HTML-maskiert.

Die View-Variable `draft` wird über `sic:oninput` und `<-` aktualisiert. Der
Abhängigkeitsgraph ersetzt daraufhin nur die Vorschau-Komponente; die auslösende
`sic:bind-value`-Kante des Inputs gilt bereits als aktuell, damit Fokus und
Cursor erhalten bleiben. Die Todo-Zeilen entstehen mit `map`; ihre Event-Lambdas
rufen die Goals aus dem Paket `backend` auf. Die Aktionen melden
`Todos::effects::backend`, und `listTodos` hört auf diesen fachlichen Effect.
Aktive Views aktualisieren dadurch ihre logischen Komponenten über WebSocket.
Auch Änderungen an erreichbaren Quellen lösen im Entwicklungsserver eine
Neuberechnung aus. Das vollständige Modell beschreibt `doc/web-reactivity.md`.
