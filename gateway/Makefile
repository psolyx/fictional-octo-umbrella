SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

PYTHON ?= python3
PYTHONPATH := $(CURDIR)/src

.PHONY: setup fmt lint test check

setup:
	@echo "==> gateway: no setup steps required"

fmt:
	@echo "==> gateway: no formatting configured; skipping"

lint:
	@echo "==> gateway: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test:
	@echo "==> gateway: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: fmt lint test
