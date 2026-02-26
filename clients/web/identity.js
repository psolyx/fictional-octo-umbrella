const identity_storage_key = 'polycentric_identity_v1';
const session_storage_key = 'polycentric_gateway_session_v1';
const gateway_url_storage_key = 'polycentric_gateway_url_v1';

const account_status_line = document.getElementById('account_status_line');
const account_import_textarea = document.getElementById('account_import_json');
const account_generate_btn = document.getElementById('account_generate_btn');
const account_import_btn = document.getElementById('account_import_btn');
const account_export_btn = document.getElementById('account_export_btn');
const account_rotate_device_btn = document.getElementById('account_rotate_device_btn');
const account_logout_btn = document.getElementById('account_logout_btn');
const account_logout_all_btn = document.getElementById('account_logout_all_btn');
const account_sessions_refresh_btn = document.getElementById('account_sessions_refresh_btn');
const account_sessions_list = document.getElementById('account_sessions_list');
const account_sessions_status = document.getElementById('account_sessions_status');

const bootstrap_token_input = document.getElementById('bootstrap_token');
const device_id_input = document.getElementById('device_id');
const device_credential_input = document.getElementById('device_credential');
const resume_token_input = document.getElementById('resume_token');
const gateway_url_input = document.getElementById('gateway_url');

const required_identity_fields = [
  'auth_token',
  'user_id',
  'device_id',
  'device_credential',
  'social_private_key_b64',
  'social_public_key_b64',
];

const b64url_encode = (bytes) => {
  let binary = '';
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};

const random_b64url = (size) => b64url_encode(crypto.getRandomValues(new Uint8Array(size)));

const normalize_identity = (candidate) => {
  if (!candidate || typeof candidate !== 'object') {
    throw new Error('identity must be a JSON object');
  }
  const normalized = {};
  required_identity_fields.forEach((field) => {
    if (typeof candidate[field] !== 'string' || !candidate[field].trim()) {
      throw new Error(`identity field missing or empty: ${field}`);
    }
    normalized[field] = candidate[field].trim();
  });
  return normalized;
};

const read_identity = () => {
  const raw_value = localStorage.getItem(identity_storage_key);
  if (!raw_value) return null;
  try {
    return normalize_identity(JSON.parse(raw_value));
  } catch (_err) {
    return null;
  }
};

const save_identity = (identity) => {
  const normalized = normalize_identity(identity);
  localStorage.setItem(identity_storage_key, JSON.stringify(normalized));
  return normalized;
};

const read_session = () => {
  const raw_value = localStorage.getItem(session_storage_key);
  if (!raw_value) return {};
  try {
    const parsed = JSON.parse(raw_value);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_err) {
    return {};
  }
};

const save_session = (session_patch) => {
  const current = read_session();
  const updated = { ...current, ...session_patch };
  localStorage.setItem(session_storage_key, JSON.stringify(updated));
  return updated;
};

const derive_http_base_url = (gateway_url) => {
  if (typeof gateway_url !== 'string') {
    return '';
  }
  const trimmed = gateway_url.trim();
  if (!trimmed) {
    return '';
  }
  if (trimmed.startsWith('ws://')) {
    return `http://${trimmed.slice('ws://'.length).replace(/\/v1\/ws$/, '')}`;
  }
  if (trimmed.startsWith('wss://')) {
    return `https://${trimmed.slice('wss://'.length).replace(/\/v1\/ws$/, '')}`;
  }
  return trimmed.replace(/\/v1\/ws$/, '');
};

const clear_local_session_state = () => {
  localStorage.removeItem(session_storage_key);
  if (resume_token_input) resume_token_input.value = '';
  if (account_sessions_list) account_sessions_list.textContent = '';
  if (account_sessions_status) account_sessions_status.textContent = 'sessions: cleared';
  window.dispatchEvent(new CustomEvent('gateway.session.cleared'));
};

const set_sessions_status = (text) => {
  if (!account_sessions_status) return;
  account_sessions_status.textContent = text;
};

const post_session_action = async (path, payload = null) => {
  const session = read_session();
  const session_token = typeof session.session_token === 'string' ? session.session_token.trim() : '';
  if (!session_token) {
    return { ok: true, skipped: true };
  }
  const stored_gateway_url = localStorage.getItem(gateway_url_storage_key) || '';
  const gateway_url = typeof session.gateway_url === 'string' && session.gateway_url.trim()
    ? session.gateway_url
    : stored_gateway_url;
  const http_base_url = derive_http_base_url(gateway_url);
  if (!http_base_url) {
    throw new Error('missing gateway URL');
  }
  const request = {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session_token}`,
      'Content-Type': 'application/json',
    },
  };
  if (payload !== null) {
    request.body = JSON.stringify(payload);
  }
  const response = await fetch(`${http_base_url}${path}`, request);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return { ok: true, skipped: false };
};

const update_account_status = (prefix = 'ready') => {
  const identity = read_identity();
  if (!account_status_line) return;
  if (!identity) {
    account_status_line.textContent = `${prefix}: no identity loaded`;
    return;
  }
  account_status_line.textContent = `${prefix}: user_id=${identity.user_id} device_id=${identity.device_id}`;
};

const fetch_sessions_list = async () => {
  const session = read_session();
  const session_token = typeof session.session_token === 'string' ? session.session_token.trim() : '';
  if (!session_token) {
    set_sessions_status('sessions: no active session');
    if (account_sessions_list) account_sessions_list.textContent = '';
    return;
  }
  const stored_gateway_url = localStorage.getItem(gateway_url_storage_key) || '';
  const gateway_url = typeof session.gateway_url === 'string' && session.gateway_url.trim()
    ? session.gateway_url
    : stored_gateway_url;
  const http_base_url = derive_http_base_url(gateway_url);
  if (!http_base_url) {
    set_sessions_status('sessions: missing gateway URL');
    return;
  }
  const response = await fetch(`${http_base_url}/v1/session/list`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${session_token}`,
    },
  });
  if (response.status === 401) {
    clear_local_session_state();
    set_sessions_status('sessions: unauthorized; local session cleared');
    update_account_status('ready');
    return;
  }
  if (response.status === 429) {
    set_sessions_status('sessions: rate limited; try again soon');
    return;
  }
  if (!response.ok) {
    set_sessions_status(`sessions: HTTP ${response.status}`);
    return;
  }
  const payload = await response.json();
  const sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
  if (account_sessions_list) {
    account_sessions_list.textContent = '';
    sessions.forEach((row) => {
      const item = document.createElement('li');
      const badge = row.is_current ? ' (This device)' : '';
      const summary = document.createElement('span');
      summary.textContent = `device_id=${String(row.device_id || '')}${badge} session_id=${String(row.session_id || '')} expires_at_ms=${String(row.expires_at_ms || '')}`;
      item.appendChild(summary);

      const revoke_session_btn = document.createElement('button');
      revoke_session_btn.type = 'button';
      revoke_session_btn.textContent = 'Revoke session';
      revoke_session_btn.addEventListener('click', async () => {
        const include_self = Boolean(row.is_current) && window.confirm('Revoke current session?');
        if (row.is_current && !include_self) {
          set_sessions_status('sessions: current session revoke canceled');
          return;
        }
        await revoke_session_target({ session_id: String(row.session_id || ''), include_self });
      });
      item.appendChild(revoke_session_btn);

      const revoke_device_btn = document.createElement('button');
      revoke_device_btn.type = 'button';
      revoke_device_btn.textContent = 'Revoke device';
      revoke_device_btn.addEventListener('click', async () => {
        const include_self = Boolean(row.is_current) && window.confirm('Revoke all sessions for this device including current session?');
        await revoke_session_target({ device_id: String(row.device_id || ''), include_self });
      });
      item.appendChild(revoke_device_btn);

      account_sessions_list.appendChild(item);
    });
  }
  set_sessions_status(`sessions: loaded ${sessions.length}`);
};

const revoke_session_target = async ({ session_id = null, device_id = null, include_self = false }) => {
  const session = read_session();
  const session_token = typeof session.session_token === 'string' ? session.session_token.trim() : '';
  if (!session_token) {
    set_sessions_status('sessions: no active session');
    return;
  }
  const stored_gateway_url = localStorage.getItem(gateway_url_storage_key) || '';
  const gateway_url = typeof session.gateway_url === 'string' && session.gateway_url.trim()
    ? session.gateway_url
    : stored_gateway_url;
  const http_base_url = derive_http_base_url(gateway_url);
  if (!http_base_url) {
    set_sessions_status('sessions: missing gateway URL');
    return;
  }
  const body = { include_self };
  if (session_id) body.session_id = session_id;
  if (device_id) body.device_id = device_id;
  const response = await fetch(`${http_base_url}/v1/session/revoke`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session_token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    clear_local_session_state();
    set_sessions_status('sessions: unauthorized; local session cleared');
    update_account_status('ready');
    return;
  }
  if (response.status === 429) {
    set_sessions_status('sessions: rate limited; try again soon');
    return;
  }
  if (!response.ok) {
    set_sessions_status(`sessions: HTTP ${response.status}`);
    return;
  }
  const payload = await response.json();
  set_sessions_status(`sessions: revoked ${String(payload.revoked || 0)}`);
  await fetch_sessions_list();
};

const export_identity = async () => {
  const identity = read_identity();
  if (!identity) {
    update_account_status('export failed');
    return;
  }
  const identity_json = JSON.stringify(identity, null, 2);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(identity_json);
  }
  const blob = new Blob([identity_json], { type: 'application/json' });
  const download_url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = download_url;
  link.download = 'polycentric_identity.json';
  link.click();
  URL.revokeObjectURL(download_url);
  update_account_status('identity exported');
};

const load_gateway_defaults = () => {
  const identity = read_identity();
  const session = read_session();
  const stored_gateway_url = localStorage.getItem(gateway_url_storage_key) || '';
  if (gateway_url_input && stored_gateway_url && !gateway_url_input.value.trim()) {
    gateway_url_input.value = stored_gateway_url;
  }
  if (!identity) {
    update_account_status();
    return;
  }
  if (bootstrap_token_input) bootstrap_token_input.value = identity.auth_token;
  if (device_id_input) device_id_input.value = identity.device_id;
  if (device_credential_input) device_credential_input.value = identity.device_credential;
  if (resume_token_input && typeof session.resume_token === 'string') {
    resume_token_input.value = session.resume_token;
  }
  update_account_status();
};

const create_identity = async () => {
  if (!crypto.subtle || !crypto.subtle.generateKey || !crypto.subtle.exportKey) {
    throw new Error('WebCrypto unavailable for identity generation');
  }
  const key_pair = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
  const private_key_pkcs8 = new Uint8Array(await crypto.subtle.exportKey('pkcs8', key_pair.privateKey));
  const private_key_bytes = private_key_pkcs8.slice(-32);
  const public_key_bytes = new Uint8Array(await crypto.subtle.exportKey('raw', key_pair.publicKey));
  const social_public_key_b64 = b64url_encode(public_key_bytes);
  const auth_token = `Bearer ${social_public_key_b64}`;
  return {
    auth_token,
    user_id: social_public_key_b64,
    device_id: `d_${random_b64url(16)}`,
    device_credential: random_b64url(32),
    social_private_key_b64: b64url_encode(private_key_bytes),
    social_public_key_b64,
  };
};

if (account_generate_btn) {
  account_generate_btn.addEventListener('click', async () => {
    try {
      const identity = await create_identity();
      save_identity(identity);
      load_gateway_defaults();
      window.dispatchEvent(new CustomEvent('identity.updated', { detail: { identity } }));
    } catch (error) {
      update_account_status(`generate failed (${error.message})`);
    }
  });
}

if (account_import_btn) {
  account_import_btn.addEventListener('click', () => {
    try {
      const raw_json = account_import_textarea ? account_import_textarea.value.trim() : '';
      if (!raw_json) throw new Error('paste identity JSON first');
      const identity = save_identity(JSON.parse(raw_json));
      load_gateway_defaults();
      window.dispatchEvent(new CustomEvent('identity.updated', { detail: { identity } }));
      update_account_status('identity imported');
    } catch (error) {
      update_account_status(`import failed (${error.message})`);
    }
  });
}

if (account_export_btn) {
  account_export_btn.addEventListener('click', () => {
    void export_identity().catch((error) => update_account_status(`export failed (${error.message})`));
  });
}

if (account_rotate_device_btn) {
  account_rotate_device_btn.addEventListener('click', () => {
    try {
      const identity = read_identity();
      if (!identity) throw new Error('create or import identity first');
      const rotated = {
        ...identity,
        device_id: `d_${random_b64url(16)}`,
        device_credential: random_b64url(32),
      };
      save_identity(rotated);
      load_gateway_defaults();
      window.dispatchEvent(new CustomEvent('identity.updated', { detail: { identity: rotated } }));
      update_account_status('device rotated');
    } catch (error) {
      update_account_status(`rotate failed (${error.message})`);
    }
  });
}

if (account_logout_btn) {
  account_logout_btn.addEventListener('click', async () => {
    let status_prefix = 'logged out';
    try {
      await post_session_action('/v1/session/logout');
    } catch (_error) {
      status_prefix = 'server logout failed (cleared local state)';
    }
    clear_local_session_state();
    update_account_status(status_prefix);
  });
}

if (account_logout_all_btn) {
  account_logout_all_btn.addEventListener('click', async () => {
    let status_prefix = 'logged out all devices';
    try {
      await post_session_action('/v1/session/logout_all', { include_self: true });
    } catch (_error) {
      status_prefix = 'server logout-all failed (cleared local state)';
    }
    clear_local_session_state();
    update_account_status(status_prefix);
  });
}

if (account_sessions_refresh_btn) {
  account_sessions_refresh_btn.addEventListener('click', () => {
    void fetch_sessions_list();
  });
}

window.addEventListener('gateway.session.ready', (event) => {
  const detail = event && event.detail ? event.detail : {};
  const session_token = typeof detail.session_token === 'string' ? detail.session_token : '';
  const resume_token = typeof detail.resume_token === 'string' ? detail.resume_token : '';
  const gateway_url = typeof detail.gateway_url === 'string' ? detail.gateway_url : '';
  if (session_token || resume_token || gateway_url) {
    save_session({ session_token, resume_token, gateway_url });
  }
  if (gateway_url) {
    localStorage.setItem(gateway_url_storage_key, gateway_url);
  }
  load_gateway_defaults();
  void fetch_sessions_list();
});

if (gateway_url_input) {
  gateway_url_input.addEventListener('change', () => {
    const gateway_url = gateway_url_input.value.trim();
    if (gateway_url) {
      localStorage.setItem(gateway_url_storage_key, gateway_url);
    }
  });
}

window.addEventListener('load', () => {
  load_gateway_defaults();
  void fetch_sessions_list();
});

export { read_identity, save_identity, update_account_status };
