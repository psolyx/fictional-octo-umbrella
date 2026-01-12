SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

LOCAL_VENV := $(CURDIR)/.venv
GATEWAY_VENV := $(abspath $(CURDIR)/../../gateway/.venv)
VENV := $(if $(wildcard $(GATEWAY_VENV)/bin/python),$(GATEWAY_VENV),$(LOCAL_VENV))
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTHONPATH := $(CURDIR)/src

.PHONY: setup deps fmt lint test check

$(PYTHON):
	@if [ "$(VENV)" = "$(LOCAL_VENV)" ]; then \
		echo "==> clients/cli: creating virtualenv"; \
		test -d $(VENV) || python3 -m venv $(VENV); \
	else \
		echo "==> clients/cli: using gateway virtualenv at $(GATEWAY_VENV)"; \
	fi

deps: $(PYTHON)
	@echo "==> clients/cli: checking deps"
	@if [ "$(VENV)" = "$(GATEWAY_VENV)" ]; then \
		$(PYTHON) -c 'import importlib.metadata as md; expected="3.13.2"; installed=md.version("aiohttp"); import sys; sys.exit(0 if installed == expected else f"Expected aiohttp=={expected} in gateway venv, found {installed}")'; \
	else \
		if $(PYTHON) -c 'import importlib.metadata as md; expected="3.13.2"; import aiohttp; installed=md.version("aiohttp"); import sys; sys.exit(0 if installed == expected else f"Expected aiohttp=={expected}, found {installed}")'; then \
			echo "aiohttp==3.13.2 already available; skipping pip install"; \
		else \
			$(PIP) install -r requirements.txt; \
			$(PYTHON) -c 'import importlib.metadata as md; expected="3.13.2"; import aiohttp; installed=md.version("aiohttp"); import sys; sys.exit(0 if installed == expected else f"Expected aiohttp=={expected}, found {installed}")'; \
		fi; \
	fi

setup: deps

fmt:
	@echo "==> clients/cli: no formatting configured; skipping"

lint:
	@echo "==> clients/cli: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test: deps
	@echo "==> clients/cli: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: setup fmt lint test
