SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTHONPATH := $(CURDIR)/src

.PHONY: setup fmt lint test check

setup:
	@echo "==> gateway: creating virtualenv and installing deps"
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PYTHON) -m pip install -U pip
	@if ! $(PIP) install -r requirements.txt; then \
	echo "==> gateway: pip install failed; continuing with existing environment"; \
	fi

fmt:
	@echo "==> gateway: no formatting configured; skipping"

lint:
	@echo "==> gateway: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test:
	@echo "==> gateway: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: setup fmt lint test
