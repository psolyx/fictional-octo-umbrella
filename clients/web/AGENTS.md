# AGENTS.md (clients/web/)

This file applies to changes under clients/web/.

## Constraints
- Do not introduce npm/yarn/pnpm or any network-fetched dependencies; this web client must remain static-only.
- Use snake_case for all protocol fields and variable names; avoid camelCase everywhere in this scope.
- Only handle ciphertext payloads until MLS binding lands; do not attempt plaintext handling here.
