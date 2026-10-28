# Reaktive SIC-Weboberflächen

Dieses Dokument legt das Zielmodell der SIC-Webschicht fest. Weboberflächen
werden in SIC definiert; Python stellt nur Compiler-, Server- und
Browserinfrastruktur bereit.

## Öffentliche Webtypen

`View::web` ist die Wurzel einer Seite. `Component::web` ist eine sichere,
reaktive Rendergrenze. Konkrete Elemente wie Input, Checkbox, Liste oder
Todo-Zeile sind keine Python-Standardkomponenten, sondern normale
SIC-Berechnungen mit dem Ergebnistyp `Component::web`.

Konfigurationstypen wie `App::web` bleiben technische Projekttypen.

## Sichere String-Builder

Ein String-Builder erhält durch seinen erwarteten Typ seine Semantik:

```sic
goal preview: Component::web = """
<div class="preview">{title: String}</div>
"""
```

Für Builder mit dem Typ `Component::web` oder `View::web` gilt:

- Statischer Text ist vertrauenswürdiger Template-Text.
- Eingefügte primitive Werte werden HTML-sicher maskiert.
- `Component::web` wird ohne erneute Maskierung eingebettet.
- `List<Component::web>` wird als sichere Komponentenliste eingebettet.
- Normale Strings werden niemals implizit zu Komponenten.
- Komponentenaufrufe bleiben intern als Graphknoten erhalten und werden nicht
  vorzeitig zu anonymen Strings reduziert.

## Reaktive Variablen

Eine View-Instanz darf langlebige Variablen besitzen:

```sic
var draft: String = ""
```

Ein Event verändert sie mit einer Zuweisung:

```sic
next => draft <- next
```

Der Initialwert wird einmal pro View-Instanz ausgewertet. Lesen erzeugt eine
Abhängigkeit; Schreiben invalidiert die abhängigen Graphknoten. Mehrere
Zuweisungen eines Events werden als ein Aktualisierungszyklus verarbeitet.

Variablenänderungen transportieren Daten. Effects tun dies nicht.

## Events und Bindings

Webevents werden im sicheren Builder markiert:

```sic
goal input: Component::web = """
<input
    value="{value: String}"
    sic:bind-value="{value}"
    sic:oninput="{on_change}"
>
"""
```

` sic:on... ` bindet eine typisierte SIC-Funktion, nicht JavaScript-Text.
` sic:bind-value ` kennzeichnet die DOM-Eigenschaft, die den angegebenen Wert
repräsentiert. Die Browsernachricht enthält View, Komponenteninstanz,
Eventbindung und neuen Wert.

Wenn der Handler die zugrunde liegende Variable aktualisiert, gilt genau die
auslösende Binding-Kante bereits als aktuell. Sie wird nicht erneut gerendert.
Andere Verwendungen derselben Variable bleiben normale Abhängigkeiten. Dadurch
bleiben Fokus und Cursor eines Eingabefelds erhalten, während beispielsweise
die Vorschau aktualisiert wird.

## Effects

Ein Effect-Payload ist ausschließlich ein Filterwert:

```sic
effect TodosChanged: Int
on TodosChanged::effects::backend = id
```

Ein passender Effect invalidiert die hörende Berechnung. Ihr neuer Wert stammt
aus ihrer erneuten Auswertung, nicht aus dem Effect. Ein Listener ohne Filter
hört auf jede Meldung der Effect-Identität.

Explizite Scopes sind nicht erforderlich. Die laufenden Graphen bilden die
Verteilungshierarchie:

```text
System -> Backends -> Views -> Komponenten
```

Ein Frontendevent erreicht zunächst seinen View-Graphen. Ein Backendeffect wird
an alle aktiven View-Graphen verteilt, die passende Listener besitzen. Eine
weitere Systemebene kann dasselbe Abonnementmodell erneut verwenden.

## Abhängigkeitsgraph und Rendergrenzen

Jede aktive View besitzt einen Graphen aus Berechnungen, Variablen,
Effect-Listenern und Komponenteninstanzen. Während der Auswertung werden
Leseabhängigkeiten aufgezeichnet.

```text
listTodos::backend -> todos -> TodoList::frontend

draft -> Input::frontend
draft -> TodoPreview::frontend
```

Bei einer Invalidierung wird der Graph vorwärts bis zu den betroffenen
`Component::web`-Grenzen verfolgt. Diese Komponenten werden vollständig neu
ausgewertet und im Browser als Einheit ersetzt. Es gibt keinen Vergleich von
HTML-Texten und keinen feingranularen DOM-Diff.

Kinder sind gegenüber ihren Eltern eigenständige Grenzen. Eine Abhängigkeit in
einem Komponentenargument wird nach Möglichkeit dem Kind und nicht dem
umgebenden Template zugeordnet.

## Komponentenidentität

Die erste Implementierung gewinnt die Identität aus View-Instanz,
Parent-Komponente, statischem Aufruf im geprüften AST und Auswertungspfad. Bei
Listen darf zunächst die logische Listenkomponente vollständig ersetzt werden.
Ein explizites `key` kann später ergänzt werden, falls der Graph für
zustandsbehaftete, umsortierbare Listenelemente nicht ausreicht.

## Dynamische Listener

Listener gehören dem Graphknoten, der sie bei seiner Auswertung erzeugt hat.
Nach einer Neuberechnung ersetzt die neue Listenermenge atomar die alte.
Entfernte Komponenten melden ihre Listener ab. Beim WebSocket-Abbruch wird der
gesamte View-Graph einschließlich aller Listener entfernt; ein Lease dient nur
als Ausfallsicherung.

Listenstruktur und Einzelelemente dürfen unterschiedlich abonnieren:

```sic
# erkennt auch neue und gelöschte IDs
on TodosChanged::effects::backend
goal listTodos: List<Todo> = ...

# aktualisiert ein bereits bekanntes Element selektiv
on TodosChanged::effects::backend = id
goal getTodo: Todo? = ...
```

## Aktualisierungsablauf

### Variablenänderung

1. Eventhandler ausführen.
2. Veränderte `var`-Knoten markieren.
3. Eventherkunft und bereits aktuelle Bindings notieren.
4. Abhängigkeiten vorwärts verfolgen.
5. Betroffene Komponenten einmalig neu auswerten.
6. Komponenten-Replacements an den Browser senden.

### Effect

1. Effect anhand Identität und optionalem Filter verteilen.
2. Passende Berechnungen invalidieren.
3. Berechnungen erneut auswerten.
4. Invalidierung über Datenabhängigkeiten weiterreichen.
5. Betroffene Komponenten ersetzen.

## Umsetzungsschritte

1. Sichere, typisierte Web-String-Builder.
2. Erhaltene Komponenteninstanzen und komponentenweises Replacement.
3. `var` und `<-` mit Lebensdauer pro View.
4. `sic:on...`-Handler.
5. `sic:bind-value` und Herkunftsunterdrückung.
6. Dynamische Listener am Graphlebenszyklus.
7. Webkomponenten in SIC statt Python.
8. Migration der Todo-Anwendung.
