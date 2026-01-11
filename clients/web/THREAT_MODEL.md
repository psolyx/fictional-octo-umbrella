# device bootstrap threat model (web client)

## 1) scope and non-goals
- scope: web client device bootstrap, including identity and device key material handling, resume_token handling, and reconnect flows through the gateway.
- scope includes storage choices in the browser and how they interact with mls state and ciphertext replay.
- non-goals: designing new protocol fields, changing gateway behavior, or altering mls wire formats.
- non-goals: plaintext handling, message search, or server-side analytics.

## 2) assets
- identity keys (polycentric system key pair) bound to a user identity.
- device credentials (mls credential and signature key pair).
- mls state and epoch secrets.
- key_packages used for onboarding and multi_device joins.
- cursors and sequence tracking (next_seq and from_seq).
- conversation ciphertext and envelopes stored for offline delivery.
- resume_token used to resume a session with the gateway.

## 3) trust boundaries
- browser: trusted to enforce origin isolation but not trusted against xss or malicious extensions.
- gateway: stores and forwards ciphertext only; not trusted with plaintext or mls secrets.
- storage: browser storage is untrusted against local compromise and rollback.
- network: untrusted; must assume active attackers and tls termination at cdn edges.
- cdn: untrusted for confidentiality; trusted only for availability and routing.

## 4) adversary models
- malicious javascript (xss or supply chain injection in static assets).
- malicious browser extension with page or storage access.
- compromised device (malware or physical access).
- network attacker (mitm, replay, injection, or downgrade attempts).
- malicious gateway or operator (metadata inspection, selective dropping, replay).

## 5) device bootstrap flows and failure modes

### initial provisioning
- flow: first device generates identity keys and a device credential, registers key_packages, and establishes mls state for new conversations.
- failure modes: key loss, partial writes of mls state, or replayed bootstrap responses.
- mitigations: atomic storage writes with versioning, use of monotonic counters in mls state, and strict validation of server responses.

### resume and reconnect
- flow: device reconnects using resume_token, requests replay from from_seq, and advances cursors with next_seq.
- failure modes: token theft, replayed or reordered responses, and cursor rollback.
- mitigations: short-lived resume_token, bound to device identity and origin, and monotonic cursor enforcement to ignore stale replies.

### multi_device separation
- flow: each device maintains independent credentials and mls state; joins are authenticated using key_packages and in-group commits.
- failure modes: device state mixup, shared storage leakage, or cross_device rollback.
- mitigations: per_device storage namespaces, explicit device_id labeling, and refusing to load mls state from a different device context.

## 6) storage model and mitigations

### what is stored
- encrypted mls state, device credentials, key_packages, and minimal cursor state.
- cached ciphertext envelopes required for offline replay.

### what must not be stored
- plaintext messages, plaintext mls secrets, raw unencrypted key material, or any derived contact graph.

### integrity and rollback
- store mls state with version and epoch metadata to detect rollback.
- reject older epochs and cursors; only advance next_seq monotonically.
- record a hash of the latest accepted state to detect tampering in local storage.

## 7) web-specific mitigations
- csp baseline: default-src 'self'; connect-src 'self' https: wss: to allow websocket and sse; object-src 'none'; base-uri 'none'; frame-ancestors 'none'.
- script-src should be 'self' with no unsafe-eval; add 'wasm-unsafe-eval' only if webassembly mls requires it.
- no dynamic code loading from remote origins; static assets are pinned and integrity checked when possible.
- avoid exposing secrets to service workers or shared storage; prefer per_origin storage with strict access.

## 8) open risks and follow-ups
- interop test suite covering web and cli clients in shared conversations.
- formal review of webassembly mls binding security and constant-time behavior.
- storage hardening for rollback resistance across browser restarts and upgrades.
- recovery flow for lost devices without reusing compromised credentials.
