# Web client bootstrap threat model

This document focuses on device bootstrap for the static web client. The client is ciphertext-only until MLS binding lands; key material is derived and stored locally without server access to plaintext.

## Scope and assumptions
- Web client runs in modern browsers without additional packages; only WebSocket connectivity to the gateway is required.
- User obtains a bootstrap secret through an out-of-band channel (QR code or one-time alphanumeric code) and uses it to start a session.
- Browser storage uses IndexedDB for long-lived secrets and session state.
- Gateway stores/forwards ciphertext only; MLS enrollment and signature verification will be added later.

## Assets
- Bootstrap secret (QR/one-time code) used to authenticate the first session.
- Resume tokens and pending outbound ciphertext queued locally.
- Future MLS key material (identity key, signature keys, group states) stored in IndexedDB.

## Adversaries and capabilities
- Network attackers who can observe/modify traffic between browser and gateway until TLS is established.
- Malicious scripts injected via XSS or compromised extensions.
- Phishing pages pretending to be the web client.
- Physical access to an unlocked device with a running session.

## Bootstrap flows
- **QR code**: user scans a QR containing the bootstrap secret on a trusted device, transferring it to the browser via clipboard or camera capture. The secret must be displayed only long enough for the scan and never cached in plaintext logs.
- **One-time code**: user types a short-lived alphanumeric code. The code should be rate-limited on the gateway and accepted once.
- After bootstrap, the client requests a `resume_token` for future reconnects and stores it in IndexedDB.

## Cross-device trust
- When adding a new browser, verify the device fingerprint (user agent + origin + timestamp) on the originating trusted device before issuing a new bootstrap secret.
- Require user confirmation (e.g., approve on an existing device) before the gateway accepts the new resume token binding.
- Display the list of active devices with last-seen metadata so users can revoke old resume tokens.

## Storage model (IndexedDB)
- Store resume tokens, last-used gateway URL, pending ciphertext queue, and MLS state (when available) in IndexedDB with origin isolation.
- Avoid localStorage/sessionStorage for secrets to reduce accidental leakage.
- Protect against partial writes: write to a new object store entry and swap only after fsync-equivalent completion.
- Provide a "clear local state" control to delete IndexedDB records and force re-bootstrap.

## Key handling and confidentiality
- Keep bootstrap secrets and resume tokens in memory only as long as needed; clear form fields after use.
- Never send plaintext or derived MLS keys to the gateway; only ciphertext leaves the browser.
- Use Web Crypto for key generation once MLS arrives; avoid exporting raw keys unless explicitly requested by the user.

## Phishing defenses
- Emphasize the canonical origin (e.g., `https://app.example`) in UI copy and onboarding instructions.
- Encourage users to verify TLS padlock and origin before scanning a QR or typing a one-time code.
- Consider binding bootstrap secrets to expected origin metadata so stolen codes cannot be redeemed on other origins.

## XSS and content security policy
- Enforce a strict Content Security Policy when the app is hosted: disallow inline scripts/styles, restrict script sources to the first-party origin, and set `connect-src` to `self` plus explicit `ws:`/`wss:` endpoints used for the gateway.
- Keep `eval` disabled; when the MLS WebAssembly binding arrives, prefer adding `'wasm-unsafe-eval'` to `script-src` instead of loosening to `unsafe-eval`.
- Escape all rendered text from gateway events; do not inject HTML from ciphertext or metadata.
- Avoid third-party analytics/ads that widen the attack surface.

## Recovery and reset
- Provide a recovery path when IndexedDB is lost: allow re-bootstrap with a fresh QR/one-time code and invalidate old resume tokens.
- Add a "reset all devices" flow that revokes every resume token and requires new bootstrap secrets for each device.
- Offer a "panic" action to wipe local IndexedDB and cached data immediately if compromise is suspected.
