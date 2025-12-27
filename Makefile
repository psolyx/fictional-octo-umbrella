# Makefile (repo root)
# Stable command surface for humans and agents:
#   make setup fmt lint test check

SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c

.PHONY: help setup fmt lint test check clean \
        setup-node setup-rust setup-go \
        fmt-node fmt-rust fmt-go \
        lint-node lint-rust lint-go \
        test-node test-rust test-go \
        components

help:
	@echo "Targets:"
	@echo "  make setup   - install deps / toolchain prep (best effort)"
	@echo "  make fmt     - format (best effort)"
	@echo "  make lint    - lint (best effort)"
	@echo "  make test    - run tests (best effort)"
	@echo "  make check   - fmt + lint + test"
	@echo ""
	@echo "This Makefile auto-detects Node/Rust/Go projects and also runs component Makefiles if present."

# ---- Meta targets ----

setup: components setup-node setup-rust setup-go

fmt: components fmt-node fmt-rust fmt-go

lint: components lint-node lint-rust lint-go

test: components test-node test-rust test-go

check: fmt lint test

clean:
	@echo "Nothing to clean at root by default. Add component clean targets as needed."

# ---- Component dispatch (optional) ----
# If you add gateway/Makefile or clients/cli/Makefile later, these will run automatically.

components:
	@set -euo pipefail; \
	for d in gateway clients/cli clients/web; do \
	  if [[ -f "$$d/Makefile" ]]; then \
	    echo "==> make -C $$d check (component)"; \
	    $(MAKE) -C "$$d" check; \
	  fi; \
	done

# ---- Node detection ----

setup-node:
	@set -euo pipefail; \
	if [[ -f package.json ]]; then \
	  echo "==> Node: installing deps"; \
	  if [[ -f pnpm-lock.yaml ]]; then pnpm i --frozen-lockfile; \
	  elif [[ -f yarn.lock ]]; then yarn install --frozen-lockfile; \
	  elif [[ -f package-lock.json ]]; then npm ci; \
	  else npm i; fi; \
	else \
	  echo "==> Node: skipped (no package.json)"; \
	fi

fmt-node:
	@set -euo pipefail; \
	if [[ -f package.json ]]; then \
	  echo "==> Node: format"; \
	  if npm run | grep -qE ' fmt(\s|:)'; then npm run fmt; \
	  elif npm run | grep -qE ' format(\s|:)'; then npm run format; \
	  else echo "No npm fmt/format script; skipping."; fi; \
	else echo "==> Node: skipped"; fi

lint-node:
	@set -euo pipefail; \
	if [[ -f package.json ]]; then \
	  echo "==> Node: lint"; \
	  if npm run | grep -qE ' lint(\s|:)'; then npm run lint; \
	  else echo "No npm lint script; skipping."; fi; \
	else echo "==> Node: skipped"; fi

test-node:
	@set -euo pipefail; \
	if [[ -f package.json ]]; then \
	  echo "==> Node: test"; \
	  if npm run | grep -qE ' test(\s|:)'; then npm test; \
	  else echo "No npm test script; skipping."; fi; \
	else echo "==> Node: skipped"; fi

# ---- Rust detection ----

setup-rust:
	@set -euo pipefail; \
	if [[ -f Cargo.toml ]]; then \
	  echo "==> Rust: fetching deps"; \
	  cargo fetch; \
	else echo "==> Rust: skipped (no Cargo.toml)"; fi

fmt-rust:
	@set -euo pipefail; \
	if [[ -f Cargo.toml ]]; then \
	  echo "==> Rust: fmt"; \
	  cargo fmt --all; \
	else echo "==> Rust: skipped"; fi

lint-rust:
	@set -euo pipefail; \
	if [[ -f Cargo.toml ]]; then \
	  echo "==> Rust: clippy"; \
	  cargo clippy --all-targets --all-features -- -D warnings; \
	else echo "==> Rust: skipped"; fi

test-rust:
	@set -euo pipefail; \
	if [[ -f Cargo.toml ]]; then \
	  echo "==> Rust: test"; \
	  cargo test --all; \
	else echo "==> Rust: skipped"; fi

# ---- Go detection ----

setup-go:
	@set -euo pipefail; \
	if [[ -f go.mod ]]; then \
	  echo "==> Go: downloading deps"; \
	  go mod download; \
	else echo "==> Go: skipped (no go.mod)"; fi

fmt-go:
	@set -euo pipefail; \
	if [[ -f go.mod ]]; then \
	  echo "==> Go: fmt"; \
	  gofmt -w $$(go list -f '{{.Dir}}' ./... | tr '\n' ' '); \
	else echo "==> Go: skipped"; fi

lint-go:
	@set -euo pipefail; \
	if [[ -f go.mod ]]; then \
	  echo "==> Go: lint (basic)"; \
	  go vet ./...; \
	else echo "==> Go: skipped"; fi

test-go:
	@set -euo pipefail; \
	if [[ -f go.mod ]]; then \
	  echo "==> Go: test"; \
	  go test ./...; \
	else echo "==> Go: skipped"; fi
