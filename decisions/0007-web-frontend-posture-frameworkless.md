# 0007: Web frontend posture — frameworkless and static

## Status
Accepted

## Context
- ARCHITECTURE.md and ROADMAP.md previously implied reuse of upstream Polycentric web UI code, which relies on larger JS frameworks and build chains.
- The repository already ships a static `clients/web` skeleton with CSP guidance and no package manager dependencies, proving the feasibility of a frameworkless path.
- The project values small supply-chain surface area, offline-friendly workflows, and auditable artifacts for security-sensitive E2EE chat and MLS integrations.
- Browser MLS bindings are already governed by ADR 0005 (Go-to-WASM harness) and should remain compatible without introducing additional toolchains.

## Decision
- Adopt a frameworkless web UI posture using plain JavaScript (optionally Web Components) with static HTML/CSS/JS artifacts committed to the repo.
- Exclude React/Vue and similar frameworks, and keep Node/npm/yarn/pnpm out of both the deployed and development-critical paths for the web UI.
- Maintain a strict CSP that explicitly whitelists WS/SSE endpoints via `connect-src`; when MLS WASM is integrated, prefer adding `'wasm-unsafe-eval'` instead of enabling `unsafe-eval`.
- Allow only small, self-contained JS modules as dependencies; prioritize vendored/offline-friendly assets and avoid network-fetched packages.
- Keep the Go-to-WASM MLS harness (ADR 0005) as the sole browser MLS binding strategy to align behavior with CLI and gateway code.

## Consequences
- Dependency and supply-chain exposure shrink, making audits and offline reproducibility easier.
- UI iteration speed may slow without higher-level frameworks, so UI scope should stay intentionally minimal and protocol-focused.
- Documentation and roadmap milestones must reinforce the static/no-build posture to prevent accidental introduction of large toolchains.
- Interop with upstream Polycentric web code should treat shared pieces as reference only; integration must respect the frameworkless/static constraints.
