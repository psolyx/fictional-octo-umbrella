SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTHONPATH := $(CURDIR)/src
PIP_CACHE_DIR := $(CURDIR)/.pip_cache

.PHONY: setup fmt lint test check

ALLOW_AIOHTTP_STUB ?= 0

$(PYTHON):
	python3 -m venv --system-site-packages $(VENV)

$(VENV)/.deps_ok: $(PYTHON) requirements.txt
	@echo "==> gateway: checking deps"
	@. $(VENV)/bin/activate && \
	if [ "$(ALLOW_AIOHTTP_STUB)" = "1" ]; then \
	echo "aiohttp stub explicitly requested; skipping dependency installation"; \
	else \
	if $(PYTHON) -c 'import importlib.metadata as md; expected="3.13.2"; import aiohttp; installed=md.version("aiohttp"); import sys; sys.exit(0 if installed == expected else f"Expected aiohttp=={expected}, found {installed}")'; then \
	echo "aiohttp==3.13.2 already available; skipping pip install"; \
	else \
	mkdir -p $(PIP_CACHE_DIR); \
	PIP_CACHE_DIR=$(PIP_CACHE_DIR) $(PIP) install -r requirements.txt; \
	$(PYTHON) -c 'import importlib.metadata as md; expected="3.13.2"; import aiohttp; installed=md.version("aiohttp"); import sys; sys.exit(0 if installed == expected else f"Expected aiohttp=={expected}, found {installed}")'; \
	fi; \
	fi
	@touch $(VENV)/.deps_ok

setup: $(VENV)/.deps_ok
	@echo "==> gateway: creating virtualenv and installing deps"
	
fmt:
	@echo "==> gateway: no formatting configured; skipping"

lint: $(VENV)/.deps_ok
	@echo "==> gateway: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test: $(VENV)/.deps_ok
	@echo "==> gateway: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: setup fmt lint test
