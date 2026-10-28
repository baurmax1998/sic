UV ?= uv
APP ?= examples/todo/app.sic
EDITOR_APP ?= examples/editor/app.sic
FILE ?= $(APP)
LOG_LEVEL ?= info

.DEFAULT_GOAL := help

.PHONY: help install run editor serve build check test repl clean

help: ## Verfügbare Befehle anzeigen
	@echo "Verfügbare Befehle:"
	@echo "  make install              Abhängigkeiten installieren"
	@echo "  make run                  Todo-Webanwendung starten"
	@echo "  make editor               Editor-Webanwendung starten"
	@echo "  make build                Webanwendung bauen"
	@echo "  make check FILE=datei.sic SIC-Datei statisch prüfen"
	@echo "  make test                 Tests ausführen"
	@echo "  make repl                 Interaktive SIC-Sitzung starten"
	@echo "  make clean                Generierte Dateien entfernen"

install: ## Python-Abhängigkeiten installieren
	$(UV) sync --dev

run: ## Beispiel-Webanwendung starten
	$(UV) run sic serve $(APP) --log-level $(LOG_LEVEL)

editor: ## Editor-Webanwendung starten
	$(UV) run sic serve $(EDITOR_APP) --log-level $(LOG_LEVEL)

serve: run ## Alias für run

build: ## Beispiel-Webanwendung bauen
	$(UV) run sic build $(APP)

check: ## SIC-Datei prüfen (FILE=...)
	$(UV) run sic check $(FILE)

test: ## Tests ausführen
	$(UV) run pytest

repl: ## SIC-REPL starten
	$(UV) run sic repl

clean: ## Generierte Dateien entfernen
	rm -rf examples/todo/.out examples/editor/.out .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
