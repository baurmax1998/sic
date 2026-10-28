# SIC Web (experimentell)

Die Webschicht ist absichtlich ein dünner FastAPI-Host. Konfiguration, Seiten
und Backendlogik bleiben SIC-Programme. Ein vollständiges Beispiel liegt in
`examples/todo`.

## Start

```bash
sic build examples/todo/app.sic
sic serve examples/todo/app.sic
```

`build` wertet alle Page-Goals aus und erzeugt HTML mit eingebettetem CSS,
JavaScript und dem SIC-Browser-Client. `serve` baut die Seiten ebenfalls und
startet FastAPI mit Host und Port aus der SIC-Konfiguration.

Für ausführliche Laufzeitdiagnose kann der Server mit Debug-Logs gestartet
werden:

```bash
sic serve examples/todo/app.sic --log-level debug
```

Auf Stufe `info` erscheinen WebSocket-Verbindungen, Aktionen,
Effektverteilung, Treffer und View-Neuberechnungen. `debug` ergänzt einzelne
Berechnungen, Cache-Treffer, Overrides und Listener. Die Browserkonsole zeigt
zusätzlich gesendete Aktionen, Ergebnisse und View-Aktualisierungen.
Effekt-Payloads erscheinen erst auf Stufe `debug` und können sensible Daten
enthalten.

## Konfiguration

`app.sic` liefert den Standardbibliothekstyp `App::web`. Erforderlich sind nur
Port, Seiten und der Name des Backend-Pakets:

```sic
goal app: App::web = {
    port: 8000,
    pages: ["frontend/app.sic"],
    backend: "backend"
}
```

`backend: "backend"` bezeichnet zugleich das Verzeichnis `backend/` relativ
zur Konfiguration und den SIC-Paketnamen. Alle `.sic`-Dateien darin werden
automatisch entdeckt. Das Goal einer Datei bestimmt den Modulnamen, sodass
beispielsweise `goal createTodo` als `createTodo::backend` verfügbar wird. Eine
reine Effektdatei wie `effects.sic` wird als Modul `effects` registriert und
stellt dadurch etwa `Todos::effects::backend` bereit.

`actions`, `endpoints` und `modules` werden nicht mehr in `app.sic` registriert.
Alle Backend-Goals sind über die View-WebSocket-Verbindung aufrufbar. Titel
(`"SIC App"`), Host (`"127.0.0.1"`) und Ausgabeordner (`.out`) besitzen
Defaults. Backendprogramme werden anhand ihres Änderungszeitpunkts vor einem
Aufruf automatisch neu kompiliert.

### Code-Hot-Reload

Der Entwicklungsserver überwacht die registrierten Page-Dateien und alle
`.sic`-Dateien im Backend-Verzeichnis. Für jede aktive View wird aus dem
geprüften AST der statisch erreichbare Berechnungsgraph auf Quelldateien
abgebildet:

- Änderungen an ihrer Page lösen unmittelbar eine Neuberechnung aus.
- Änderungen an einer erreichbaren Backend-Berechnung oder Effektdeklaration
  invalidieren den Backend-Registry-Stand und berechnen die View neu.
- Änderungen an nicht erreichbaren Backend-Dateien aktualisieren diese View
  nicht.
- Compilerfehler werden über WebSocket als Diagnose eingeblendet; nach der
  Korrektur versucht der nächste Datei-Event die Berechnung erneut.

Die Neuberechnung ersetzt derzeit weiterhin den vollständigen View-Wurzelknoten.
Neu angelegte oder entfernte Backend-Dateien sowie Änderungen an `app.sic`
benötigen vorerst einen Server-Neustart, weil sie die Projektstruktur verändern.

## Komponenten

HTML wird über zwei kleine, sichere Bausteine erzeugt:

```sic
text::web("Text <wird escaped>")
element::web("p", {"class": "intro"}, [child])
```

`element` nimmt Tag, `Map<String, String>` mit Attributen und `List<Html::web>`
mit bereits gerenderten Kindern entgegen und liefert selbst `Html::web`.
Dadurch kann HTML nicht mit beliebigen Strings verwechselt werden. Attributwerte
werden ebenfalls escaped. Void-Elemente wie `input` benötigen eine leere Kinderliste.

Eine wiederverwendbare Komponente ist ein normales SIC-Modul:

```sic
goal card: Html::web = element::web("article", {"class": "card"}, [heading])
let heading = element::web("h2", {"class": "title"}, [
    text::web(title: String)
])
```

Nach der Registrierung als Modul `card` im Paket `components` wird sie mit
benannten, statisch geprüften Argumenten zusammengesetzt:

```sic
goal pageHtml: Html::web = card::frontend(title: "Hallo")
```

Jedes `let` eines Moduls ist ebenfalls exportierbar. Dadurch können kleine
Komponenten intern bleiben oder gezielt von anderen Modulen zusammengesetzt
werden. Das Todo-Beispiel trennt Layout, Todo-Oberfläche und Browserverhalten
unter `examples/todo/frontend/`. Wenn Modul und Goal gleich heißen, genügt der
kurze Paketpfad `layout::frontend` statt `layout::layout::frontend`.

## Seiten

Ein Page-Goal hat den Typ `Page::web` aus der Web-Standardbibliothek. Dieser
Typ verlangt die Felder `output`, `title`, `html`, `css` und `js` als Strings:

```sic
goal page: Page::web = {
    output: "index.html",
    title: "Todos",
    html: todoPage::frontend(),
    css: "",
    js: "sic.call(\"todos\").then(console.log);"
}
```

Im Browser steht `sic.call(name, daten)` zur Verfügung. Der Aufruf wird über
die WebSocket-Verbindung der View übertragen. `request.method` enthält dabei
`"WS"`, `request.path` den internen Aktionspfad
`/__sic_action/<goal>`. HTTP-Methoden und öffentliche Routen sind nicht
Bestandteil dieser App-Konfiguration.

Zusätzlich unterstützt der Klebecode:

- `data-sic-call="goal"` auf Buttons
- `data-sic-submit="goal"` auf Formularen
- `data-sic-output="goal"` für die einfache Text-/JSON-Ausgabe
- die Events `sic:result` und `sic:error`

In mehrzeiligen SIC-String-Buildern müssen literale JavaScript- und
CSS-Klammern als `{{` und `}}` geschrieben werden.

## Reaktive Views und Komponenten

Alternativ zu `Page::web` liefert eine Frontend-Datei direkt `View::web`. Der
Build verwendet dann `index.html` und den Projekttitel. Konkrete Elemente sind
keine Python-Komponenten: Sie werden als sichere `Component::web`-String-Builder
in SIC definiert. Primitive Interpolationen werden maskiert, Komponenten sicher
eingebettet.

```sic
goal input: Component::web = """
<input
    value="{value: String}"
    sic:bind-value="{value}"
    sic:oninput="{on_change}"
>
"""
```

Eine View kann pro Verbindung langlebige Variablen besitzen:

```sic
goal view: View::web = """
<main>
    {input::frontend(value: draft, on_change: next => draft <- next)}
    {preview::frontend(title: draft)}
    {todoList::frontend(todos: todos)}
</main>
"""

var draft: String = ""
let todos = listTodos::backend()
```

`var` wird einmal pro View-Instanz initialisiert. `<-` invalidiert über den
Abhängigkeitsgraphen nur die verwendenden Komponenten. Die auslösende
`sic:bind-value`-Kante ist bereits im Browser aktuell und wird ausgelassen.
Passende Effects invalidieren weiterhin ihre Berechnungen; anschließend werden
logische Komponenten statt einzelner DOM-Knoten ersetzt. Details und
Lebenszyklusregeln stehen in `web-reactivity.md`.

## Backend-Aufrufe

Freie Namen eines Backend-Goals werden aus den WebSocket-Aktionswerten
versorgt:

```sic
goal response: String = "Hallo " + (name: String)
```

Zusätzlich ist `request` mit den Feldern `method`, `path`, `query`,
`pathParams`, `headers` und `body` verfügbar. Formularstrings werden anhand der
statisch ermittelten SIC-Eingabetypen nach `Int`, `Float` oder `Bool`
konvertiert.

Normale Ergebnisse werden als JSON zurückgegeben. Ein Response-Record kann
Status und Body festlegen:

```sic
goal response = {status: 201, body: {ok: true}}
```

`err` wird als typisierte WebSocket-Fehlermeldung zurückgegeben.
Dateioperationen laufen unter einem prozessweiten Lock, damit die JSON-Demo
nicht durch parallele Aufrufe beschädigt wird. Lesezugriffe abonnieren
automatisch den technischen
`FileChanged::files::std`-Effekt, Schreibzugriffe lösen ihn aus. Diese
prozesslokale Effektverteilung ist noch kein Transaktionssystem.
