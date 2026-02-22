const text_encoder = new TextEncoder();

const b64url_encode = (bytes) => {
  let binary = '';
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

const b64url_decode = (value) => {
  const padded = `${value}${'='.repeat((4 - (value.length % 4)) % 4)}`.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
};

const to_pkcs8_private_key = (private_key_bytes) => {
  if (private_key_bytes.length === 32) {
    const prefix = new Uint8Array([
      0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06,
      0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20,
    ]);
    const merged = new Uint8Array(prefix.length + private_key_bytes.length);
    merged.set(prefix, 0);
    merged.set(private_key_bytes, prefix.length);
    return merged;
  }
  return private_key_bytes;
};

const sort_value = (value) => {
  if (Array.isArray(value)) {
    return value.map((item) => sort_value(item));
  }
  if (value && typeof value === 'object') {
    return Object.keys(value)
      .sort()
      .reduce((acc, key) => {
        acc[key] = sort_value(value[key]);
        return acc;
      }, {});
  }
  return value;
};

const canonical_social_bytes = ({ user_id, prev_hash, ts_ms, kind, payload }) => {
  const normalized_payload = sort_value(payload);
  const body = {
    kind,
    payload: normalized_payload,
    prev_hash: prev_hash || '',
    ts_ms: Number.parseInt(String(ts_ms), 10),
    user_id,
  };
  const canonical_json = JSON.stringify(body, Object.keys(body).sort());
  return text_encoder.encode(canonical_json);
};

const sha256_hex = async (bytes) => {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
};

const sign_social_event = async ({ social_private_key_b64, user_id, prev_hash, ts_ms, kind, payload }) => {
  if (!crypto.subtle || !crypto.subtle.importKey || !crypto.subtle.sign) {
    throw new Error('SubtleCrypto Ed25519 is unavailable');
  }
  const canonical_bytes = canonical_social_bytes({ user_id, prev_hash, ts_ms, kind, payload });
  const private_key_bytes = b64url_decode(social_private_key_b64);
  const private_key = await crypto.subtle.importKey('pkcs8', to_pkcs8_private_key(private_key_bytes), { name: 'Ed25519' }, false, ['sign']);
  const signature = new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, private_key, canonical_bytes));
  return {
    sig_b64: b64url_encode(signature),
    event_hash: await sha256_hex(canonical_bytes),
    canonical_bytes,
  };
};

export { canonical_social_bytes, sha256_hex, sign_social_event };
