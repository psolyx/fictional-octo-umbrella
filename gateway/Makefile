SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTHONPATH := $(CURDIR)/src

.PHONY: setup fmt lint test check

ALLOW_AIOHTTP_STUB ?= 1

setup:
	@echo "==> gateway: creating virtualenv and installing deps"
	@test -d $(VENV) || python3 -m venv --system-site-packages $(VENV)
	@. $(VENV)/bin/activate && \
		( python -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("aiohttp") else 1)' && \
		  echo "aiohttp already installed; skipping download" || \
		  if [ "$(ALLOW_AIOHTTP_STUB)" = "1" ]; then \
		    echo "aiohttp not found; using stub modules (set ALLOW_AIOHTTP_STUB=0 to enforce install)"; \
		  else \
		    $(PYTHON) -m pip install -U pip && \
		    $(PIP) install -r requirements.txt; \
		  fi )

fmt:
	@echo "==> gateway: no formatting configured; skipping"

lint:
	@echo "==> gateway: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test:
	@echo "==> gateway: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: setup fmt lint test
