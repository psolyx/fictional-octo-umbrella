# MLSWG conformance vectors (trimmed)

These JSON files vendor a minimal, deterministic subset of the MLSWG conformance suite for offline CI use. They cover:

- **crypto-basics** — HKDF label derivations and AEAD protection using `X25519_AES128GCM_SHA256_Ed25519`.
- **tree-math** — core balanced-tree index relationships for a 7-leaf tree.

The files are reduced to keep runtime fast and input sizes bounded. If upstream vectors change, add new cases here and note any known-bad inputs before skipping them in the harness runner.
