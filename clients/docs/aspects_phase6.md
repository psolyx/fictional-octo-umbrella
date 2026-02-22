# Phase 6 Aspects planning gate (planning-only)

## Scope marker
- This document is planning-only for Phase 6.
- No runtime Aspects encryption/decryption feature is implemented in this phase.
- Federation remains a later phase.

## Encrypted payload envelope contract
Aspects payloads are intended to fit within existing signed social event payloads:

```json
{
  "payload": {
    "aspect_id": "asp_...",
    "key_id": "k_...",
    "alg": "XChaCha20-Poly1305",
    "nonce_b64": "...",
    "aad_b64": "...",
    "ciphertext_b64": "..."
  }
}
```

Required fields:
- `aspect_id`
- `key_id`
- `alg`
- `nonce_b64`
- `ciphertext_b64`

Optional field:
- `aad_b64`

## Key distribution posture (MLS-backed)
- Intended primitive: MLS (RFC 9420) for aspect membership key management.
- Aspect membership updates are planned to map to MLS group operations.
- Social events remain signed by user identity keys; encrypted payload remains opaque to the gateway.

## Rotation rules (planning)
- Define key rotation trigger conditions (member add/remove, compromise suspicion, scheduled rotation).
- Define overlap/deprecation windows for old `key_id` values.
- Define replay/error behavior when clients lack current keys.

## Non-member UX (planning)
- Non-members should render deterministic placeholders (for example: "Encrypted for aspect members").
- No plaintext leakage in metadata, logs, or previews.
- Clients should surface key-unavailable states without exposing sensitive membership details.
