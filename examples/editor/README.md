# SIC Editor-Webdemo

Eine eigenständige Editor-Anwendung für SIC-Projekte. Als Workspace wird
`examples/basic` geöffnet.

## Start

```bash
make editor
```

Danach den Editor unter <http://127.0.0.1:8001> öffnen.

## Projektverwaltung

- Dateien und Verzeichnisse werden im Project-Panel angezeigt.
- Ein Klick auf eine Datei öffnet sie im Editor.
- `Ctrl+S` beziehungsweise `Cmd+S` schreibt Änderungen in den Workspace.
- `＋F` legt eine Datei im ausgewählten Ordner an, `＋D` einen Unterordner.
- Das Drei-Punkte-Menü einer Zeile bietet Umbenennen und Löschen.
- Bei Ordnern können über dieses Menü außerdem Dateien und Unterordner angelegt werden.
- `↻` lädt den Dateibaum neu.
- Pfade werden serverseitig auf den konfigurierten Workspace begrenzt.

Über die Run-Konfiguration in der Statusleiste kann ein Goal aus dem Workspace
ausgewählt und mit `▶` ausgeführt werden. Benötigte Eingaben werden vor dem
Start abgefragt; Ergebnis und Konsolenausgabe erscheinen im Run-Fenster.

Ein Klick auf eine Zeilennummer setzt oder entfernt einen Breakpoint. `D`
startet das ausgewählte Goal im Debugger. Das Debug-Fenster bietet Fortsetzen,
Schritt über und Stop sowie Stack-, Variablen- und Laufzeitausgabe. Entsprechend
der deklarativen Auswertung liegen Debug-Schritte auf `goal`-, `let`- und
`var`-Bindungen. Bereits ausgewertete Bindungen werden während des Debuggens
zusätzlich in einer gemeinsamen Spalte rechts neben der längsten Quellzeile
als Inline-Werte eingeblendet.

Mit `⟳` wird der Serve-Modus für das ausgewählte Goal aktiviert. Änderungen
werden nach kurzer Verzögerung gespeichert, das Goal wird erneut ausgewertet
und die Inline-Werte werden automatisch aktualisiert. Ein erneuter Klick auf
`⟳` beendet den Modus. `examples/basic/calculation.sic` enthält dafür eine
mehrstufige Beispielberechnung.

Der Editor unterstützt außerdem Zeilennummern, eigenes semantisches
Syntax-Highlighting, Diagnosen, Verwendungshervorhebung und Autocomplete.
