SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTHONPATH := $(CURDIR)/src
PIP_CACHE_DIR := $(CURDIR)/.pip_cache

# Keep the pinned version here so the Makefile can validate deterministically.
AIOHTTP_VERSION ?= 3.13.2

ALLOW_AIOHTTP_STUB ?= 0

.PHONY: setup fmt lint test check clean

$(PYTHON):
	python3 -m venv $(VENV)

$(VENV)/.deps_ok: $(PYTHON) requirements.txt
	@echo "==> gateway: checking deps"
	@. $(VENV)/bin/activate && \
	if [ "$(ALLOW_AIOHTTP_STUB)" = "1" ]; then \
		echo "aiohttp stub explicitly requested; skipping dependency installation"; \
	else \
		# Pre-check: quiet (no traceback) if aiohttp isn't installed yet.
		if $(PYTHON) -c 'import importlib.util, importlib.metadata as md, sys; expected="$(AIOHTTP_VERSION)"; spec=importlib.util.find_spec("aiohttp"); sys.exit(1) if spec is None else sys.exit(0 if md.version("aiohttp")==expected else 1)'; then \
			echo "aiohttp==$(AIOHTTP_VERSION) already available; skipping pip install"; \
		else \
			mkdir -p $(PIP_CACHE_DIR); \
			PIP_CACHE_DIR=$(PIP_CACHE_DIR) $(PIP) install -r requirements.txt; \
			# Post-install check: strict, and prints a clear error if mismatched.
			$(PYTHON) -c 'import importlib.metadata as md, sys; expected="$(AIOHTTP_VERSION)"; installed=md.version("aiohttp"); sys.exit(0) if installed==expected else sys.exit(f"Expected aiohttp=={expected}, found {installed}")'; \
		fi; \
	fi
	@touch $(VENV)/.deps_ok

setup: $(VENV)/.deps_ok
	@echo "==> gateway: deps ready"

fmt:
	@echo "==> gateway: no formatting configured; skipping"

lint: $(VENV)/.deps_ok
	@echo "==> gateway: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test: $(VENV)/.deps_ok
	@echo "==> gateway: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: setup fmt lint test

clean:
	rm -rf $(VENV) $(PIP_CACHE_DIR)
