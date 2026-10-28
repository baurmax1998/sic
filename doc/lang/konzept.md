# SIC – Sprachkonzept und Sprachübersicht

> **Stand:** experimentelle Sprache, Version 0.1. Diese Beschreibung orientiert
> sich am aktuellen Parser, Typprüfer und Interpreter im Verzeichnis `src/lang`.
>
> Das [Konzept für ein reaktives Effektsystem](effektsystem.md) bildet die
> Grundlage der experimentellen Effekt- und WebSocket-Implementierung.

SIC ist eine **statisch typisierte, ausdrucksorientierte und zielorientierte**
Sprache. Ein Programm beschreibt zuerst das gewünschte Ergebnis (`goal`) und
anschließend nur die Werte, die für dieses Ergebnis benötigt werden. Die
Laufzeit wertet den dadurch entstehenden Abhängigkeitsgraphen bedarfsgesteuert
aus.

Eine SIC-Datei endet auf `.sic`.

## 1. Die Grundidee

Ein klassisches Programm beschreibt häufig die Arbeitsschritte von oben nach
unten. SIC beginnt stattdessen mit dem Ergebnis:

```sic
goal total: Int = area * price
let area = width * height
let width = 6
let height = 3
let price = 1200
```

Das Programm kann man so lesen:

1. Das Ziel ist `total` vom Typ `Int`.
2. `total` benötigt `area` und `price`.
3. Deshalb dürfen danach `area` und `price` definiert werden.
4. `area` benötigt wiederum `width` und `height`.
5. Die Auswertung berechnet nur Werte, die tatsächlich für `total` gebraucht
   werden.

Das Ergebnis ist `21600`.

Diese umgekehrte Reihenfolge ist eine bewusste Spracheigenschaft und keine bloße
Stilregel.

## 2. Aufbau eines Programms

Ein ausführbares Programm besitzt **genau ein** `goal`. Das `goal` muss die
erste Wertdefinition sein. Effektmetadaten dürfen davor stehen. Danach folgen
bei Bedarf `let`-Definitionen. Ein reines Effektmodul darf ausschließlich
`effect`-Deklarationen enthalten.

```sic
goal <name> [: <typ>] = <ausdruck>
let <name>  [: <typ>] = <ausdruck>
```

Beispiel:

```sic
goal greeting: String = prefix + name
let prefix = "Hallo "
let name = "Ada"
```

Regeln:

- Namen und Werte sind unveränderlich.
- Es gibt keine Zuweisungen und keine veränderlichen Variablen.
- Jede Top-Level-Definition darf nur einmal vorkommen.
- Eine `let`-Definition ist nur zulässig, wenn ihr Name zuvor bereits benötigt
  wurde. Unbenutzte Definitionen werden statisch abgelehnt.
- Vorwärtsreferenzen sind deshalb normal und beabsichtigt.
- Abhängigkeitszyklen wie `a -> b -> a` werden statisch abgelehnt.
- Eine Typannotation ist optional, muss aber gesetzt werden, wenn der Typ nicht
  eindeutig hergeleitet werden kann.

Ungültig ist beispielsweise:

```sic
# Ungültig: goal steht nicht zuerst.
let answer = 42
goal result: Int = answer
```

Ebenfalls ungültig:

```sic
# Ungültig: unused wird vom goal nicht benötigt.
goal result: Int = 42
let unused = 1
```

### Freie Namen als Eingaben

Ein Name, der nicht mit `let` definiert wird, ist eine Eingabe des Programms:

```sic
goal total: Int = amount * quantity
```

Hier sind `amount` und `quantity` Eingaben. Ihr Typ wird aus der Verwendung als
`Int` abgeleitet. Beim Einbetten über die Python-API können sie übergeben werden:

```python
from sic.lang import run

result = run(
    "goal total: Int = amount * quantity",
    arguments={"amount": 12, "quantity": 3},
)
assert result.value == 36
```

`sic run` besitzt zurzeit keine Kommandozeilenoption für solche Eingaben. Ohne
bereitgestellten Wert entsteht deshalb ein Laufzeitfehler.

## 3. Lexikalische Regeln

- Bezeichner verwenden ASCII-Buchstaben, Ziffern und `_`; das erste Zeichen
  muss ein Buchstabe oder `_` sein.
- Groß- und Kleinschreibung werden unterschieden.
- Leerzeichen und Zeilenumbrüche trennen nur Tokens; es gibt keine
  Einrückungssyntax.
- Semikolons existieren nicht.
- Kommentare beginnen mit `#` und reichen bis zum Zeilenende.
- Normale Strings verwenden doppelte Anführungszeichen und JSON-kompatible
  Escapes, zum Beispiel `"Zeile 1\nZeile 2"`.

```sic
goal answer: Int = value + 1  # Kommentar
let value = 41
```

## 4. Typsystem

SIC prüft das vollständige Programm vor der Ausführung. Es gibt keine
impliziten Umwandlungen, insbesondere nicht zwischen `Int`, `Float`, `Bool` und
`String`.

### Eingebaute Typen

| Typ | Beispiel | Bedeutung |
|---|---|---|
| `Bool` | `true`, `false` | Wahrheitswert |
| `Int` | `42` | Ganzzahl |
| `Float` | `3.5` | Fließkommazahl |
| `String` | `"Hallo"` | Zeichenkette |
| `T?` | `Int?` | `T` oder `null` |
| `List<T>` | `List<String>` | homogene Liste |
| `Map<K, V>` | `Map<String, Int>` | Schlüssel-Wert-Abbildung |
| `Name` | `Customer` | inferierter Record-Typ |
| `Name::herkunft` | `View::web` | registrierter externer Typ |

`List` benötigt genau einen, `Map` genau zwei Typparameter.

### Typinferenz und Annotationen

Typen werden aus Literalen, Operationen, Funktionsverwendungen und
Annotationen abgeleitet:

```sic
goal total: Int = orders.map(order => order.amount: Int).sum()
let orders = [{amount: 10}, {amount: 20}]
```

Aus `order.amount: Int` ergibt sich die Anforderung, dass `Order`-ähnliche Werte
ein Feld `amount` vom Typ `Int` besitzen.

Eine Annotation kann an Definitionen oder Ausdrücken stehen:

```sic
goal name: String = raw: String
```

Bei längeren Ausdrücken sind Klammern oft klarer:

```sic
goal result: Int = (value: Int) + 1
```

SIC verfolgt das Prinzip „Typ bei der ersten notwendigen Verwendung“. Ist ein
Name dort bereits vollständig typisiert, gilt eine spätere identische
Definitionstypannotation als redundant und wird abgelehnt:

```sic
# Ungültig: Der Typ von orders wurde schon bei der Verwendung festgelegt.
goal total: Int = orders: List<Order>.map(o => o.amount: Int).sum()
let orders: List<Order> = [{amount: 2}]
```

Richtig ist in diesem Fall:

```sic
goal total: Int = orders: List<Order>.map(o => o.amount: Int).sum()
let orders = [{amount: 2}]
```

### Nullable-Werte

`T?` enthält entweder einen Wert vom Typ `T` oder `null`:

```sic
goal first: Int = values.first() ?? 0
let values = [1, 2, 3]
```

Ein nullable Wert darf nicht ungeprüft als normaler Wert verwendet werden.
Möglichkeiten zum Entpacken sind:

```sic
# Fallback
goal a: Int =
    let maybe: Int? = null
    in maybe ?? 0
```

```sic
# Verengung durch null-Prüfung
goal b: Int =
    let maybe: Int? = 4
    in if maybe != null then maybe + 1 else 0
```

```sic
# Pattern Matching
goal c: Int =
    let maybe: Int? = 4
    in match maybe {
        null => 0,
        value => value + 1
    }
```

Sicherer Zugriff mit `?.` propagiert `null`:

```sic
goal city: String =
    let customer: Customer? = null
    in customer?.address?.city ?? "unbekannt"
```

`?.` ist nur auf nullable Werten zulässig.

### Records

Records sind benannte Felder in geschweiften Klammern:

```sic
goal person: Person = {
    name: "Ada",
    age: 36,
    active: true
}
```

Felder werden mit `.` gelesen:

```sic
goal name: String = (person: Person).name: String
let person = {name: "Ada", age: 36}
```

Record-Typen wie `Person`, `Customer` oder `Order` brauchen keine separate
Typdeklaration. Der Typprüfer sammelt ihre Feldanforderungen aus den
Verwendungen. Record-Literale sind geschlossen: Fehlt ein statisch verlangtes
Feld oder besitzt es den falschen Typ, wird das Programm abgelehnt.

### Maps

Map-Literale unterscheiden sich durch Stringliterale als Schlüssel von
Records:

```sic
goal score: Int = (scores: Map<String, Int>)["Grace"]
let scores = {"Ada": 10, "Grace": 12}
```

Ein fehlender Schlüssel bei `map[key]` ist ein Laufzeitfehler. Für optionalen
Zugriff dient `.get(key)`.

Das leere Literal `{}` wird anhand des erwarteten Typs als leerer Record oder
leere Map interpretiert.

## 5. Ausdrücke und Operatoren

Fast alle Konstrukte in SIC sind Ausdrücke und liefern einen Wert.

### Literale und Zugriffe

```sic
true
42
3.14
"Text"
null
[1, 2, 3]
{name: "Ada", active: true}
{"Ada": 10, "Grace": 12}
values[0]
person.name
```

Listen, Maps und Records sind typisiert. Elemente einer Liste müssen denselben
Typ besitzen.

### Operatoren

Von niedriger zu hoher Bindungsstärke:

1. `??`
2. `or`
3. `and`
4. `==`, `!=`, `<`, `<=`, `>`, `>=`
5. `+`, `-`
6. `*`, `/`, `%`
7. Präfixoperatoren `not`, `-`
8. Aufruf, Index, Feldzugriff und Typannotation

Klammern überschreiben die Reihenfolge.

| Operator | Zulässige Typen | Ergebnis |
|---|---|---|
| `not x` | `Bool` | `Bool` |
| `-x` | derzeit `Int` | `Int` |
| `+` | zwei `Int`, `Float`, `String` oder gleichartige Listen | derselbe Typ |
| `-`, `*`, `%` | zwei gleichartige `Int` oder `Float` | derselbe Typ |
| `/` | zwei `Float` | `Float` |
| `<`, `<=`, `>`, `>=` | gleichartige `Int`, `Float` oder `String` | `Bool` |
| `==`, `!=` | kompatible Typen | `Bool` |
| `and`, `or` | `Bool` | `Bool` |
| `a ?? b` | `a: T?`, `b: T` | `T` |

`and`, `or` und `??` werten die rechte Seite nur aus, wenn sie benötigt wird.

### Bedingte Ausdrücke

```sic
goal label: String =
    if score >= 90 then "sehr gut" else "weiter üben"
```

Die Bedingung muss `Bool` sein; beide Zweige müssen denselben Ergebnistyp
besitzen. Nur der gewählte Zweig wird ausgeführt.

### Lokale Bindungen

Eine lokale Bindung gilt nur im Ausdruck hinter `in`:

```sic
goal total: Int =
    let subtotal = [1, 2, 3].sum()
    in subtotal * 2
```

Sie ist nicht mit einer Top-Level-`let`-Definition zu verwechseln.

### Lambdas und Funktionsaufrufe

Ein Lambda mit einem Parameter:

```sic
x => x * 2
```

Mit mehreren Parametern:

```sic
(total, item) => total + item.amount
```

Lambdatypen werden aus ihrer Verwendung hergeleitet. Normale Funktionen und
Lambdas werden mit positionalen Argumenten aufgerufen:

```sic
calculate(orders)
```

Benannte Argumente besitzen in SIC eine besondere Bedeutung: Sie rufen eine
Top-Level-Berechnung oder registrierte externe Funktion auf. Siehe Abschnitt
„Berechnungen“.

### `match`

```sic
goal label: String = match status {
    200 => "ok",
    404 => "fehlt",
    _ => "unbekannt"
}
```

Unterstützte Muster sind:

- `null`
- Bool-, Zahlen- und Stringliterale
- `_` als Wildcard
- ein Name als bindendes Auffangmuster

Ein `match` muss mit `_` oder einem bindenden Namen vollständig gemacht werden.
Dieses Auffangmuster muss der letzte Fall sein. Bei einem nullable Ausgangswert
ist zusätzlich ein expliziter `null`-Fall erforderlich.

### String-Builder

Dreifache Anführungszeichen erzeugen einen mehrzeiligen, interpolierten String:

```sic
goal greeting: String = """Hallo {name}!
Du hast {messages.count()} Nachrichten.
{{name}} bleibt wörtlicher Text."""
let name = "Ada"
let messages = [1, 2, 3]
```

`{ausdruck}` interpoliert einen SIC-Ausdruck. `{{` und `}}` erzeugen literale
Klammern. `null` wird als `null`, Bool-Werte werden als `true` beziehungsweise
`false` dargestellt.

## 6. Collection-Operationen

### Listen

Für `List<T>` stehen folgende Methoden zur Verfügung:

| Methode | Typische Signatur | Bedeutung |
|---|---|---|
| `filter(f)` | `(T => Bool) -> List<T>` | passende Elemente |
| `map(f)` | `(T => U) -> List<U>` | Elemente transformieren |
| `flat_map(f)` | `(T => List<U>) -> List<U>` | transformieren und abflachen |
| `fold(start, f)` | `(U, (U, T) => U) -> U` | links falten |
| `sum()` | `List<Int/Float> -> Int/Float` | Summe |
| `any(f)` | `(T => Bool) -> Bool` | mindestens ein Treffer |
| `all(f)` | `(T => Bool) -> Bool` | alle treffen zu |
| `count()` | `() -> Int` | Anzahl |
| `take(n)` | `(Int) -> List<T>` | erste `n` Elemente |
| `drop(n)` | `(Int) -> List<T>` | erste `n` Elemente überspringen |
| `first()` | `() -> T?` | erstes Element oder `null` |
| `last()` | `() -> T?` | letztes Element oder `null` |
| `find(f)` | `(T => Bool) -> T?` | erster Treffer oder `null` |
| `sort()` | `() -> List<T>` | sortiert `Int`, `Float` oder `String` |
| `group_by(f)` | `(T => K) -> Map<K, List<T>>` | nach Schlüssel gruppieren |

Beispiel:

```sic
goal unpaidTotal: Int = orders
    .filter(order => not order.paid)
    .map(order => order.amount: Int)
    .sum()

let orders = [
    {amount: 10, paid: false},
    {amount: 20, paid: true}
]
```

### Maps

Für `Map<K, V>` existieren:

| Methode | Ergebnis |
|---|---|
| `keys()` | `List<K>` |
| `values()` | `List<V>` |
| `get(key)` | `V?` |
| `contains_key(key)` | `Bool` |

## 7. Berechnungen und Overrides

Jedes Top-Level-`goal` und jedes Top-Level-`let` ist eine aufrufbare
**Berechnung**. Berechnungen erhalten benannte Argumente:

```sic
goal result: Int = a + b
let b = c * d
```

Mögliche Aufrufe aus einem anderen SIC-Programm sind:

```sic
result(a: 10, b: 5)
result(a: 10, c: 2, d: 3)
b(c: 2, d: 3)
```

Ein Argument kann entweder

- eine freie Eingabe bereitstellen oder
- eine erreichbare Zwischenberechnung überschreiben.

`result(a: 10, b: 5)` ersetzt `b` direkt. Dadurch werden `c` und `d` nicht mehr
benötigt und der komplette Teilgraph unterhalb von `b` wird abgeschnitten. Das
ist ein zentrales SIC-Konzept.

Berechnungsaufrufe:

- verwenden ausschließlich benannte Argumente,
- lehnen unbekannte oder doppelte Argumente ab,
- verlangen alle statisch nötigen Eingaben,
- dürfen keine positionalen und benannten Argumente mischen.

Der Typprüfer betrachtet die Anforderungen aller möglichen `if`- und
`match`-Zweige. Zur Laufzeit wird trotzdem nur der tatsächlich gewählte Zweig
ausgeführt.

## 8. Module und Herkunftspfade

SIC besitzt aktuell keine `import`-Anweisung. Externe Funktionen, Typen und
andere SIC-Dateien werden vom Host in einem `ModuleRegistry` registriert und
über einen Herkunftspfad angesprochen:

```sic
invoice::prices::shop(base: 100.0, discount: 20.0)
read_json::files::std("customers.json")
View::web
```

Die Reihenfolge ist:

```text
symbol::modul::paket
```

Das Symbol steht also zuerst, seine Herkunft folgt danach.

Python kann ein SIC-Modul registrieren:

```python
from sic.lang import ModuleRegistry

registry = ModuleRegistry()
registry.register_source("prices", "shop", source)
```

Danach sind das `goal` und alle Top-Level-`let`-Berechnungen des Moduls über
`::<modul>::<paket>` erreichbar. Die Registrierung prüft nur das Programm; sie
führt dessen Anwendungslogik nicht aus.

## 9. Benannte Fehler

`err` beendet den aktuell ausgewerteten Berechnungsweg:

```sic
err divideByZero
err divideByZero = "Der Divisor darf nicht null sein"
```

Die zweite Form besitzt einen typisierten Nutzwert. Ein Fehlername darf
innerhalb seiner erreichbaren Definitionen nicht zugleich mit und ohne Nutzwert
verwendet werden.

Beispiel:

```sic
goal quotient: Float =
    if divisor == 0.0
    then err divideByZero = "Divisor ist null"
    else numerator / divisor
```

Ein normaler Aufruf propagiert den Fehler automatisch. Ein überschriebener
Teilgraph und ein nicht gewählter Zweig lösen keinen Fehler aus.

### Fehler als Ausgang abfangen

Ein Berechnungsaufruf kann einmal ausgeführt und in mehrere benannte Ausgänge
zerlegt werden:

```sic
goal message: String =
    if divideByZero != null then divideByZero else "ok"

quotient, divideByZero =
    quotient::math::example(numerator: 10.0, divisor: 0.0)
```

Die Syntax benötigt mindestens zwei Namen vor `=`. Nur ausdrücklich entnommene
Fehler werden abgefangen. Andere Fehler propagieren weiter.

Sobald ein Fehlerausgang entnommen wird, können normale Ausgänge fehlen. Daher
werden sie nullable:

- normaler Ergebnis- oder Zwischenwert: `T?`
- Fehler mit Nutzwert: `T?`
- Fehler ohne Nutzwert: `Bool?` (`true` bedeutet: Fehler trat auf)

Vor einer normalen Verwendung muss die Anwesenheit mit `!= null`, `match` oder
`??` nachgewiesen werden. Gleichnamige Fehler aus verschiedenen Herkünften
müssen eindeutig sein; eine Umbenennung beim Entnehmen wird noch nicht
unterstützt.

## 10. Reaktive Effekte (experimentell)

Effekte sind typisierte Änderungsmeldungen. Ein Modul kann einen Effekttyp
deklarieren:

```sic
effect Todos: Int
```

Andere Module lösen ihn nach erfolgreichem Abschluss ihres Goals aus oder
abonnieren ihn:

```sic
emit todosChanged: Todos::effects::backend = createTodo.id
on Todos::effects::backend = id
```

Der Ausdruck hinter `on ... =` ist ein Gleichheitsfilter und keine Bindung.
`void Effekt::herkunft` verwirft ausgehende Meldungen dieses Typs an der
aktuellen Aufrufgrenze. `ignore Effekt::herkunft` unterdrückt dagegen nur
automatische Listener der aktuellen Auswertung. Ausdrückliche `on`-Listener
bleiben erhalten.

Effekte können wie Fehler als benannte Ausgänge entnommen werden:

```sic
saved, fileChanged =
    write_text::files::std("neu", "datei.txt")
```

Ein entnommener Effektausgang ist eine geordnete `List<P>` seiner Payloads und
propagiert nicht weiter. Anders als ein entnommener Fehler macht er normale
Ausgänge nicht nullable. `ExecutionResult.effects` und
`ExecutionResult.subscriptions` stellen die Laufzeitmetadaten für Hosts bereit.

Dateileseoperationen abonnieren automatisch `FileChanged::files::std` für den
kanonischen Pfad; erfolgreiche Schreiboperationen erzeugen diesen Effekt.
Deklarative Web-Views werden über WebSocket neu ausgewertet, sobald eine
passende Meldung eintrifft. Die Verteilung ist derzeit prozesslokal und ersetzt
den vollständigen View-Wurzelknoten.

Das vollständige semantische Modell und die weiterführenden Anforderungen sind
im [Effektsystem-Entwurf](effektsystem.md) beschrieben.

## 11. Standardbibliothek

Der Standard-Registry enthält folgende allgemeine Funktionen:

| Funktion | Bedeutung |
|---|---|
| `read_json::files::std(path)` | JSON lesen; Rückgabetyp durch Verwendung/Annotation festlegen |
| `write_json::files::std(value, path)` | JSON schreiben, liefert `Bool` |
| `read_text::files::std(path)` | Textdatei lesen |
| `write_text::files::std(value, path)` | Textdatei schreiben, liefert `Bool` |
| `print::console::std(value)` | Wert ausgeben und unverändert zurückgeben |

Beispiel:

```sic
goal names: List<String> =
    read_json::files::std("customers.json"): List<Customer>
        .map(customer => customer.name: String)
```

Externe Werte werden an der Laufzeitgrenze gegen den statisch erwarteten Typ
validiert. Ein JSON-Feld mit falschem Typ erzeugt daher einen Laufzeitfehler,
statt unkontrolliert weiterverarbeitet zu werden.

Die Standardbibliothek enthält außerdem Webtypen und Webfunktionen. Diese sind
in [SIC Web](../web.md) dokumentiert.

## 12. Auswertungsmodell

Die Verarbeitung besteht aus drei Phasen:

1. **Parsen:** Syntax und Quellpositionen werden erfasst.
2. **Statische Prüfung:** Definitionsreihenfolge, Namen, Typen, Recordfelder,
   Berechnungsargumente und Abhängigkeitszyklen werden geprüft.
3. **Bedarfsgesteuerte Ausführung:** Das `goal` wird angefordert; seine
   Abhängigkeiten werden rekursiv berechnet und zwischengespeichert.

Wichtige Folgen:

- Nicht benötigte Definitionen sind bereits syntaktisch-konzeptionell
  unerwünscht und werden abgelehnt.
- Nicht gewählte Zweige werden nicht ausgeführt.
- `and`, `or` und `??` arbeiten kurzschließend.
- Externe Eingaben und Funktionsresultate werden zur Laufzeit validiert.
- Seiteneffekte entstehen nur durch explizite externe Funktionen wie
  `write_json::files::std` oder `print::console::std`.

## 13. Informelle Syntaxübersicht

Die folgende EBNF ist als Orientierung gedacht; der Parsercode bleibt für
Grenzfälle maßgeblich.

```ebnf
program       = { effect-meta }, goal, { definition | capture | effect-meta }
              | effect-declaration, { effect-declaration } ;
effect-meta   = effect-declaration | emit | listener | suppression ;
effect-declaration = "effect", name, ":", type ;
emit          = "emit", name, ":", qualified-name, "=", expression ;
listener      = "on", qualified-name, [ "=", expression ] ;
suppression   = ( "void" | "ignore" ), qualified-name ;
goal          = "goal", name, [ ":", type ], "=", expression ;
definition    = "let", name, [ ":", type ], "=", expression ;
capture       = name, ",", name, { ",", name }, "=", calculation-call ;

type          = qualified-name, [ "<", type, { ",", type }, ">" ], [ "?" ] ;
qualified-name= name, { "::", name } ;

expression    = literal
              | name
              | list
              | record-or-map
              | lambda
              | local-let
              | if-expression
              | match-expression
              | error-expression
              | unary-expression
              | expression, binary-op, expression
              | expression, "(", [ arguments ], ")"
              | expression, "[", expression, "]"
              | expression, ".", name
              | expression, "?.", name
              | expression, ":", type
              | "(", expression, ")" ;

local-let     = "let", name, [ ":", type ], "=", expression,
                "in", expression ;
if-expression = "if", expression, "then", expression, "else", expression ;
match-expression
              = "match", expression, "{", case, { [","], case }, "}" ;
case          = pattern, "=>", expression ;
lambda        = name, "=>", expression
              | "(", name, { ",", name }, ")", "=>", expression ;
error-expression
              = "err", name, [ "=", expression ] ;
arguments     = expression, { ",", expression }
              | named-argument, { ",", named-argument } ;
named-argument= name, ":", expression ;
```

## 14. Kommandozeile

Nach Installation des Projekts steht das Programm `sic` zur Verfügung:

```bash
sic check program.sic       # parsen und statisch prüfen
sic run program.sic         # prüfen und goal ausführen
sic repl                    # mehrere Programme interaktiv ausführen
sic describe .              # Schnittstellen nach .out/i und .out/t schreiben
sic build app.sic           # experimentelles Webprojekt bauen
sic serve app.sic           # experimentellen Webserver starten
```

`check` zeigt den Namen und den hergeleiteten Typ des Goals. Fehler enthalten
Datei, Zeile, Spalte und einen markierten Quellbereich.

## 15. Vollständiges Beispiel

```sic
goal report: String =
    let unpaid = customers
        .flat_map(customer => customer.orders)
        .filter(order => not order.paid)
    in """Offene Rechnungen: {unpaid.count()}
Gesamtsumme: {unpaid.map(order => order.amount: Int).sum()}"""

let customers: List<Customer> = [
    {
        orders: [
            {amount: 80, paid: false},
            {amount: 45, paid: true}
        ]
    },
    {
        orders: [
            {amount: 25, paid: false}
        ]
    }
]
```

Ergebnis:

```text
Offene Rechnungen: 2
Gesamtsumme: 105
```

Dieses Beispiel zeigt das typische SIC-Modell: Das gewünschte Ergebnis steht
oben, seine Daten folgen danach, Transformationen sind Ausdrücke und die
Ausführung folgt automatisch den statisch geprüften Abhängigkeiten.

## 16. Derzeitige Grenzen

Für das Verständnis der aktuellen Implementierung sind folgende Grenzen
wichtig:

- Es gibt noch kein natives Datei- oder Paket-Importsystem; Module werden durch
  den Host beziehungsweise die Web-Projektlogik registriert.
- Es gibt keine veränderlichen Variablen, Schleifen oder Klassen. Iteration
  erfolgt über Listenoperationen.
- Es gibt keine benutzerdefinierte Typdeklarationssyntax; Records entstehen aus
  Anforderungen und Annotationen.
- Fehlerausgänge können beim Abfangen noch nicht umbenannt werden.
- `sic run` nimmt noch keine freien Eingaben als CLI-Argumente an.
- Effektverteilung und Webunterstützung sind experimentell. Die Verteilung ist
  prozesslokal. SIC-Quelldateien werden im Entwicklungsserver überwacht; für
  externe Änderungen an Nutzdaten gibt es noch keinen allgemeinen Dateiwächter.
  Persistente View-Wiederaufnahme und verteilte Genau-einmal-Zustellung fehlen.
- Reaktive Webupdates berechnen derzeit die View neu und ersetzen ihren
  vollständigen Wurzelknoten; feingranulare UI-Patches sind noch offen.
- LLM-gestützte Generierung ist experimentell.
