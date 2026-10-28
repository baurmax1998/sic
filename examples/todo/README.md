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
  app.sic               # deklarative App::web
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
`frontend/app.sic` liefert direkt `View::web`; dort ist nur die sichtbare
Todo-Liste eine Datenabhängigkeit. Die nächste ID wird beim Erstellen im Backend
aus dem aktuellen Datenbestand bestimmt. Die Todo-Zeilen entstehen mit `map`;
Event-Lambdas rufen unmittelbar die Goals aus dem Paket `backend` auf. Die Aktionen
melden `Todos::effects::backend`; `listTodos` hört auf diesen fachlichen Effekt.
Aktive Views werden daraufhin über WebSocket neu ausgewertet, ohne Seiten-Reload.
Auch Änderungen an der Frontend-Datei oder an statisch erreichbaren
Backend-Dateien lösen im Entwicklungsserver automatisch eine Neuberechnung aus.

Die UI verwendet die Standardbibliothekstypen `App::web` und `View::web` sowie
`Column::web`, `Input::web`, `ListView::web`, `Row::web`, `Checkbox::web`,
`Text::web` und `Button::web`.
