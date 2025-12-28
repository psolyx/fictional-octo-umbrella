SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTHONPATH := $(CURDIR)/src

.PHONY: setup fmt lint test check

ALLOW_AIOHTTP_STUB ?= 0

setup:
	@echo "==> gateway: creating virtualenv and installing deps"
	@test -d $(VENV) || python3 -m venv $(VENV)
	@. $(VENV)/bin/activate && \
	if [ "$(ALLOW_AIOHTTP_STUB)" = "1" ]; then \
	echo "aiohttp stub explicitly requested; skipping dependency installation"; \
	else \
	$(PIP) install -r requirements.txt; \
	$(PYTHON) -c 'import importlib.metadata as md, sys; expected="3.13.2"; installed=md.version("aiohttp"); '"'"'\
	    sys.exit(f"Expected aiohttp=={expected}, found {installed}") if installed != expected else None'"'"''
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
