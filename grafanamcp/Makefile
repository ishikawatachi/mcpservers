VENV   := $(HOME)/tmp/grafanamcp-venv
PYTHON := /opt/homebrew/bin/python3.13
BIN    := $(VENV)/bin

.PHONY: venv test lint typecheck clean

venv:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet -e ".[dev]"

test: venv
	PYTHONPATH=src $(BIN)/pytest tests/ -v --tb=short

lint: venv
	$(BIN)/ruff check src/ tests/

typecheck: venv
	$(BIN)/mypy src/

clean:
	rm -rf $(VENV)
