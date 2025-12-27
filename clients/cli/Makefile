SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

PYTHON ?= python3
PYTHONPATH := $(CURDIR)/src

.PHONY: setup fmt lint test check

setup:
	@echo "==> clients/cli: no setup steps required"

fmt:
	@echo "==> clients/cli: no formatting configured; skipping"

lint:
	@echo "==> clients/cli: syntax check"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m compileall -q src tests

test:
	@echo "==> clients/cli: running unit tests"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests

check: fmt lint test
