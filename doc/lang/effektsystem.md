# SIC – Konzept für ein reaktives Effektsystem

> **Entwurf vom 27. Oktober 2026.** Ergänzung zum
> [Sprachkonzept 0.1](konzept.md); keine Beschreibung bereits implementierter
> Funktionen.

## 1. Ziel und Grundidee

SIC beschreibt ein gewünschtes Ergebnis und die Werte, von denen dieses
Ergebnis abhängt. Das Effektsystem ergänzt diesen Berechnungsgraphen um
explizite Änderungsmeldungen: Eine Aktion meldet eine Änderung, aktive
Berechnungsinstanzen reagieren darauf, und die Laufzeit berechnet deren
benötigte abhängige Ergebnisse neu.

Der erste Anwendungsfall sind lebende Weboberflächen. Jede geöffnete Oberfläche
besitzt ihren eigenen Berechnungskontext und eine WebSocket-Verbindung. Ändert
eine Aktion Daten, können alle betroffenen Oberflächen aktualisiert werden,
ohne dass Anwendungscode einen Reload oder eine manuelle Synchronisierung
beschreibt.

Effekte sind benannt, typisiert und über Herkunftspfade eindeutig adressierbar.
Fachliche Effekte werden ausdrücklich definiert. Bibliotheken können
automatische technische Effekte und Abonnements bereitstellen.

## 2. Begriffe

| Begriff | Bedeutung |
|---|---|
| **Effekttyp** | Eindeutige Identität einer Änderungsmeldung mit ihrem Payload-Typ |
| **Effektmeldung** | Konkretes Auftreten eines Effekts mit einem Payload |
| **Effekt-Ausgang** | Benannter Ausgang einer Berechnung, über den Meldungen entnommen werden können |
| **Listener** | Abonnement einer aktiven Berechnungsinstanz auf einen Effekttyp, optional mit Payload-Filter |
| **Berechnungsinstanz** | Konkrete Auswertung einer Berechnung mit Eingaben, Overrides und Laufzeitkontext |
| **View-Instanz** | Eine aktive Oberfläche mit ihren Berechnungsinstanzen und ihrer Verbindung |

Dieses Konzept verwendet Effekte als Änderungsmeldungen mit reaktiver
Neuberechnung. Allgemeine fortsetzbare algebraische Effekte sind nicht
Bestandteil dieses Entwurfs.

## 3. Vereinbarte Sprachbausteine

### Effekttyp deklarieren

```sic
effect Todos: Int
```

`Todos` ist die Effektidentität, `Int` der Payload-Typ. Hier transportiert jede
Meldung die ID einer geänderten Aufgabe. Erstellen, Ändern und Löschen können
denselben Effekt auslösen.

Ein registriertes Herkunftsmodul macht ihn beispielsweise als
`Todos::effects::backend` verfügbar. Gleichnamige Effekte unterschiedlicher
Herkunft sind unterschiedliche Effekte. Die Deklaration muss verfügbar sein,
bevor das verwendende Programm statisch geprüft wird; die konkrete Integration
von Effektdeklarationen in Module wird noch festgelegt.

### Effekt auslösen

```sic
emit todosChanged: Todos::effects::backend = createTodo.id
```

- `todosChanged` ist der benannte Effekt-Ausgang der Berechnung.
- `Todos::effects::backend` bestimmt Effektidentität und Payload-Typ.
- `createTodo.id` liefert den Payload und muss hier `Int` sein.

`emit` ist eine Deklaration, keine Anweisung an dieser Quelltextposition. Sie
darf vor dem Goal oder zwischen Definitionen stehen. Bei erfolgreichem
Abschluss der zugehörigen Berechnung wird ihr Payload ermittelt und die Meldung
erzeugt. Bei einem fehlgeschlagenen Goal entsteht dessen deklarierte
Erfolgsmeldung nicht.

Die Referenz auf `createTodo.id` liest das bereits erfolgreich berechnete
Ergebnis. Sie führt weder einen erneuten Aufruf noch einen Wertzyklus ein. Der
Compiler behandelt die Meldung als Abschlussabhängigkeit.

### Auf Effekte reagieren

```sic
on Todos::effects::backend
```

Die aktive Berechnungsinstanz hört auf jede Meldung dieses Effekttyps.

Als bisheriger Syntaxvorschlag für einen Filter gilt:

```sic
on Todos::effects::backend = id
```

Hier wird der Payload mit dem Wert von `id` verglichen. Das ist ein
Gleichheitsfilter, keine Bindung einer neuen Variable. Für `Todos: Int` muss
`id` ein `Int` sein. Eine Syntax für komplexere Prädikate ist noch offen.

### Ausgehende Meldungen verwerfen

```sic
void FileChanged::files::std
```

`void` verwirft Meldungen dieses Effekttyps, die aus dem aktuellen
Berechnungsaufruf nach außen propagieren würden. Die zugrunde liegende
Operation, beispielsweise das Schreiben einer Datei, wird weiterhin
ausgeführt. Andere Aufrufe und deren Meldungen werden nicht global deaktiviert.

### Automatische Listener unterdrücken

```sic
ignore FileChanged::files::std
```

`ignore` unterdrückt die aus dieser Auswertung übernommenen automatischen
Abonnements dieses Effekttyps. Es verhindert keine Leseoperation und verwirft
keine ausgehenden Meldungen.

Der Unterschied ist gerichtet: `void` betrifft ausgehende Meldungen, `ignore`
eingehende Reaktivität. `on` bleibt das Schlüsselwort für ausdrücklich
gewünschte Listener.

## 4. Vollständiges Todo-Beispiel

Die folgenden Blöcke stehen für getrennte registrierte Module. Die Datei sei
bereits mit einer gültigen Todo-Liste initialisiert. Herkunftspfade werden wie
bisher vom Host registriert.

### Effekte: `effects::backend`

```sic
effect Todos: Int
```

### Aktion: `createTodo::backend`

```sic
void FileChanged::files::std
ignore FileChanged::files::std
emit todosChanged: Todos::effects::backend = createTodo.id

goal createTodo: Todo =
    if saved
    then todo
    else err persistenceError = "Todo konnte nicht gespeichert werden"

let saved = write_json::files::std(updated, "backend/todos.json")
let updated: List<Todo> = todos + [todo]
let todos = read_json::files::std("backend/todos.json")
let todo = {id: id: Int, title: title: String, done: false}
```

`void` unterdrückt den technischen Schreibeffekt. `ignore` verhindert, dass der
interne Lesezugriff die Aktion reaktiv macht. Zusätzlich gilt grundsätzlich:
Eine abgeschlossene Aktion wird durch Änderungen nicht automatisch erneut
ausgeführt.

Die Aktion liefert das erstellte Todo zurück und meldet dessen ID über den
Effekt-Ausgang `todosChanged`. Sie wird weiterhin mit benannten Eingaben
aufgerufen:

```sic
createTodo::backend(id: nextId, title: title)
```

### Liste: `listTodos::backend`

```sic
ignore FileChanged::files::std
on Todos::effects::backend

goal listTodos: List<Todo> =
    read_json::files::std("backend/todos.json")
```

Die Liste reagiert ausdrücklich auf fachliche Todo-Änderungen. Der automatische
Datei-Listener wird unterdrückt. Externe Dateiänderungen aktualisieren diese
Liste deshalb nicht automatisch, sofern sie keine fachliche Meldung erzeugen.

### Einzelne Aufgabe

```sic
ignore FileChanged::files::std
on Todos::effects::backend = id

goal getTodo: Todo? =
    todos.find(todo => todo.id == id)

let todos: List<Todo> =
    read_json::files::std("backend/todos.json")
```

Ein Aufruf mit `id: 42` reagiert auf `Todos`-Meldungen mit Payload `42`.

## 5. Effekte als benannte Ausgänge abfangen

Analog zu benannten Fehlerausgängen kann ein Aufrufer einen Effekt ausdrücklich
entnehmen:

```sic
created, todosChanged =
    createTodo::backend(id: nextId, title: title)
```

Die Entnahme verhindert die weitere automatische Verteilung dieser Meldungen.
Ohne explizite Entnahme propagieren sie weiter. Anders als ein Fehler beendet
ein Effekt den normalen Berechnungsweg nicht. Allein das Entnehmen eines
Effekts macht den normalen Rückgabewert deshalb nicht nullable.

Der Name des Ausgangs ist vom Effekttyp getrennt. Unterschiedliche Berechnungen
dürfen ihre Ausgänge unterschiedlich benennen und dennoch denselben Effekt
`Todos::effects::backend` erzeugen.

Bei Bibliotheksfunktionen wäre beispielsweise möglich:

```sic
saved, fileChanged =
    write_json::files::std(updated, "backend/todos.json")
```

Der Ausgangsname `fileChanged` wird von der Funktion deklariert. Seine
explizite Entnahme fängt ihn ab. `void FileChanged::files::std` ist dagegen
eine Deklaration zum Verwerfen aller nach außen gehenden Meldungen dieses Typs
im aktuellen Aufruf.

Noch festzulegen ist die Wertrepräsentation entnommener Meldungen. Ein Aufruf
kann null, eine oder mehrere Meldungen erzeugen. Empfehlung: ein geordneter,
typisierter Meldungsstrom beziehungsweise eine Liste; keine stillschweigende
Reduktion auf die letzte Meldung. Bei gemischter Entnahme von Fehlern und
Effekten bleiben die bisherigen Fehlerregeln relevant.

## 6. Technische Effekte der Dateibibliothek

Die Dateibibliothek kann intern einen Effekt mit dem kanonisch aufgelösten
Dateipfad als Payload anbieten:

```sic
effect FileChanged: String
```

- Ein Lesezugriff registriert in einem lebenden Berechnungskontext automatisch
  ein passendes Abonnement auf den gelesenen Pfad.
- Ein erfolgreicher Schreibzugriff erzeugt eine entsprechende Meldung.
- Ein Dateiwächter kann Änderungen durch externe Programme als denselben Effekt
  einspeisen.

Äquivalente Pfade müssen dieselbe Ressourcenidentität ergeben. Die genaue
Behandlung von Arbeitsverzeichnissen, symbolischen Links und
Plattformunterschieden gehört in den Vertrag der Dateibibliothek.

Fachliche Module können diese technische Reaktivität mit `ignore` und `void`
abschirmen und durch `on Todos` beziehungsweise `emit ...: Todos` ersetzen. Das
ist eine ausdrückliche Entscheidung; die Laufzeit leitet fachliche Bedeutung
nicht selbst aus Dateinamen ab.

## 7. Laufzeit und WebSocket

### Öffnen einer Oberfläche

1. Der Server erzeugt eine View-Instanz und berechnet ihr Goal.
2. Die Auswertung erfasst die tatsächlich verwendeten Berechnungen und deren
   Wertabhängigkeiten.
3. Explizite und erlaubte automatische Listener werden der jeweiligen aktiven
   Instanz zugeordnet.
4. Der Browser erhält die Oberfläche; die WebSocket-Verbindung ordnet spätere
   Events und Updates dieser Instanz zu.

Jede geöffnete UI erhält ihren eigenen Kontext. Gemeinsame Ergebnis-Caches sind
keine Voraussetzung dieses Modells.

### Ausführen einer Aktion

1. Der Browser sendet ein UI-Event mit den nötigen Werten.
2. Der Server führt das zugeordnete Event-Lambda als neuen Aktionsaufruf aus.
3. Untergeordnete Operationen erzeugen Meldungen. Benannte Entnahme und `void`
   werden an ihren jeweiligen Aufrufgrenzen angewendet.
4. Bei erfolgreichem Goal werden dessen deklarierte `emit`-Ausgänge erzeugt.
5. Die verbleibenden Meldungen werden verteilt.

Empfehlung: Meldungen während einer Aktion sammeln und erst nach deren Abschluss
zustellen. So beginnen reaktive Neuberechnungen nicht mitten in einem
Schreibvorgang. Die Fehlerbehandlung solcher gesammelten Meldungen braucht eine
eigene Regel, siehe Abschnitt 10.

### Aktualisieren der Oberflächen

1. Das Effektverzeichnis findet alle passenden aktiven Listener im zulässigen
   Anwendungsbereich.
2. Deren Berechnungen werden als veraltet markiert.
3. Die Markierung folgt den tatsächlichen Wertabhängigkeiten.
4. Weiterhin benötigte Ergebnisse werden neu berechnet.
5. Betroffene UI-Teilbäume werden über WebSocket aktualisiert.

In der Todo-Ansicht betrifft das auch `nextId` und die davon abhängigen
Event-Bindungen. Nur sichtbaren Text zu ersetzen würde nicht ausreichen.

Mehrere Meldungen können dieselbe Berechnung betreffen. Die Laufzeit fasst
anstehende Neuberechnungen zusammen, ohne dabei für andere Empfänger relevante
Payloads zu verlieren. Aktionen selbst werden niemals durch dieses Verfahren
wiederholt.

## 8. Lebensdauer, Isolation und Overrides

Listener gehören aktiven Instanzen, nicht bloß einer Quelldatei. Beim Entfernen
eines UI-Abschnitts werden seine nicht mehr benötigten Listener entfernt. Bei
Neuberechnung werden Abhängigkeiten und Abonnements abgeglichen, einschließlich
nicht mehr gewählter Zweige.

Für eine erste Version kann eine geschlossene Verbindung die View-Instanz
freigeben; Wiederverbinden erzeugt eine frische Ansicht. Eine aufwendigere
Wiederaufnahme ist später möglich.

Effekte werden an alle passenden Instanzen innerhalb ihres Laufzeit- beziehungsweise
Anwendungsbereichs verteilt. Mehrere Serverprozesse benötigen dafür einen
gemeinsamen Verteilmechanismus. Benutzer- und Mandantengrenzen sowie die
Autorisierung jeder neu ausgeführten Datenabfrage müssen erhalten bleiben.

Overrides schneiden weiterhin Abhängigkeitsgraphen ab. Wird etwa `todos` durch
einen festen Wert ersetzt, darf aus dem nicht ausgeführten Lesezweig kein
automatisches Abonnement entstehen. Ein ausdrücklich am aktiven Goal
deklariertes `on` gilt dagegen weiterhin, selbst wenn einzelne
Datenabhängigkeiten ersetzt wurden.

## 9. Statische Prüfung und interne Struktur

Der Compiler erweitert AST und Registry um Effektdeklarationen,
Effekt-Ausgänge, Listener und Unterdrückungsdeklarationen. Die Registry kennt
vollständige Effektidentitäten und Payload-Typen sowie die Effektschnittstellen
externer Funktionen.

Zu prüfen sind insbesondere:

- Auflösbarkeit der Herkunftspfade und eindeutige Ausgangsnamen;
- Übereinstimmung von Payload-Ausdruck und Effekttyp;
- Typverträglichkeit von Listenerfiltern;
- Erreichbarkeit zusätzlicher Abhängigkeiten aus Effektdeklarationen;
- Gültigkeit benannter Entnahmen an Berechnungsaufrufen;
- echte Wertzyklen, getrennt von erlaubten Abschlussreferenzen auf das Goal.

Deklarationen zählen als Verwendungen im Sinne der bisherigen SIC-Regeln. Die
Regel „Goal zuerst“ wird präzisiert: Es ist die erste Wertdefinition;
Effektmetadaten dürfen davor stehen. Die genaue Definitionsreihenfolge
zusätzlicher, nur vom Payload benötigter Werte muss der Compiler entsprechend
berücksichtigen.

Intern genügt zunächst ein Verzeichnis nach Effektidentität, mit
Instanzreferenz und optionalem Filter. Hinzu kommen Abhängigkeiten zwischen
Berechnungsinstanzen, stabile UI-Abschnittskennungen und eine
Meldungswarteschlange. Zwischengespeicherte Ergebnisse können die Auswertung
optimieren; die konzeptionelle Grundlage sind die lebenden Instanzen und ihre
Abonnements.

`ignore` sollte automatische Abonnements dieser Auswertung unterdrücken, ohne
eine anderweitig aktive Instanz global zu verändern. Für die erste Version
empfiehlt sich, Listener innerhalb eines Aufrufs als dessen
Abonnementbeiträge zu behandeln. Ein ausdrückliches `on` bleibt erhalten, auch
wenn derselbe Typ mit `ignore` für automatische Beiträge ausgeschlossen wird.

## 10. Noch festzulegende Semantik

Vor einer Implementierung müssen die folgenden Punkte verbindlich entschieden
und mit Konformitätstests beschrieben werden.

### Fehler und Zustellung

Deklarierte `emit`-Ausgänge eines Goals entstehen nur bei dessen erfolgreichem
Abschluss. Davon zu unterscheiden sind Meldungen bereits erfolgreich
ausgeführter untergeordneter Operationen. Wenn beispielsweise ein Schreibzugriff
erfolgreich war und die umgebende Aktion später fehlschlägt, darf seine Meldung
nicht ohne Weiteres verloren gehen: Ohne Transaktion hat die Außenwelt sich
bereits geändert.

Empfehlung für die erste Version:

- Meldungen erfolgreicher Unteroperationen bleiben erhalten, sofern sie nicht
  entnommen oder mit `void` verworfen wurden;
- deklarierte Erfolgsmeldungen des fehlgeschlagenen Goals entstehen nicht;
- die gesammelten Meldungen werden auch nach einem Fehler erst an der äußeren
  Aktionsgrenze zugestellt;
- echte Transaktionen dürfen später eine abweichende Commit-/Rollback-Regel
  definieren.

### Repräsentation entnommener Effekte

Empfohlen wird `List<P>`, wobei `P` der Payload-Typ des Effekts ist. Kein
Auftreten ergibt eine leere Liste, nicht `null`; Reihenfolge und Mehrfachvorkommen
bleiben erhalten. Das Entnehmen eines Effekts allein macht den normalen Ausgang
nicht nullable. Werden im selben Aufruf Fehler entnommen, gelten zusätzlich die
Nullable-Regeln der Fehlerausgänge.

Diese Festlegung benötigt entweder eine syntaktisch eindeutig ableitbare
Listentypisierung oder einen eigenen nominalen Meldungsstromtyp, falls später
Metadaten wie Sequenznummer, Ursprung und Zeitpunkt sichtbar werden sollen.

### Reihenfolge, Bündelung und Wiederholung

Die Laufzeit darf mehrere Invalidierungen derselben Berechnungsinstanz zu einer
Neuberechnung bündeln. Sie darf dadurch aber keine Meldungen aus einem
entnommenen Meldungsstrom oder für andere gefilterte Listener entfernen.
Innerhalb einer Aktion sollte die Erzeugungsreihenfolge stabil bleiben.

Für einen einzelnen Prozess kann zunächst höchstens-einmalige Zustellung gelten.
Ein verteilter Verteilmechanismus muss dagegen ausdrücklich festlegen, ob er
höchstens einmal, mindestens einmal oder effektiv genau einmal zustellt.
Listener und Neuberechnungen sollten deshalb nicht von der Einmaligkeit einer
Meldung abhängen.

### Gleichheit und Filter

Der Gleichheitsfilter `on E = value` ist nur für Payload-Typen zulässig, für die
SIC eine totale, stabile Gleichheit definiert. Kanonisierung technischer
Ressourcen muss vor dem Vergleich stattfinden. Prädikatfilter, Bereichsfilter
und Muster sind nicht Teil der ersten Version.

### Reaktive Zyklen

Wertzyklen bleiben statisch verboten. Zusätzlich braucht die Laufzeit Schutz vor
dynamischen Effektzyklen, etwa wenn eine reaktive Neuberechnung erneut denselben
Effekt erzeugt. Aktionen werden nie automatisch wiederholt; für andere
Berechnungen sollte die erste Version entweder `emit` auf ausdrücklich als
Aktion ausgeführte Aufrufe begrenzen oder Zustellungswellen mit Zyklenerkennung
und einem festen Abbruchfehler verwenden.

### Sicherheits- und Verteilungsbereich

Eine Meldung benötigt neben ihrer Effektidentität einen nicht vom
Anwendungspayload vorgetäuschten Laufzeitbereich, mindestens Anwendung und
Mandant. Dieser Bereich ist Teil des Zustellungsumschlags, nicht zwingend des
sichtbaren SIC-Payloads. Bei jeder Neuberechnung werden Authentisierung und
Autorisierung aus dem Kontext der betroffenen View-Instanz erneut angewendet.

### Modul- und Schnittstellenformat

Offen bleiben die Ablage von `effect`-Deklarationen, ihre Darstellung in
generierten Schnittstellen sowie die Deklaration automatischer Effekte externer
Funktionen. Das Schnittstellenformat muss mindestens Effektidentität,
Payload-Typ, Ausgangsname und die Unterscheidung zwischen automatischen
Listenern und ausgehenden Meldungen transportieren.

## 11. Abgrenzung der ersten Version

Eine erste umsetzbare Version umfasst:

- nominale, typisierte Effekte mit Herkunftspfad;
- `emit`, `on`, Gleichheitsfilter, `void` und `ignore`;
- benannte Entnahme als geordnete Payload-Liste;
- automatische `FileChanged`-Listener und -Meldungen;
- aktionsweise gepufferte Zustellung;
- instanzbezogene Invalidierung und Neuberechnung;
- Lebensdauerbindung an eine WebSocket-View-Instanz.

Nicht Bestandteil dieser ersten Version sind allgemeine algebraische Effekte,
beliebige Listenerprädikate, dauerhafte Wiederaufnahme geschlossener Views,
verteilte Genau-einmal-Zustellung und Transaktionen über externe Operationen.
