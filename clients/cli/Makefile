SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTHONPATH := $(CURDIR)/src

.PHONY: setup fmt lint test check

setup:
	@echo "==> clients/cli: creating virtualenv and installing deps"
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install -r requirements.txt

fmt:
	@echo "==> clients/cli: no formatting configured; skipping"

lint:
	@echo "==> clients/cli: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test:
	@echo "==> clients/cli: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: setup fmt lint test
