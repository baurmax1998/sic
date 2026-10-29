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

Der Editor unterstützt außerdem Zeilennummern, eigenes semantisches
Syntax-Highlighting, Diagnosen, Verwendungshervorhebung und Autocomplete.
