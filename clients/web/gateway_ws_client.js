/* Minimal gateway v1 WebSocket client (ciphertext only). */
(() => {
  const connection_status = document.getElementById('connection_status');
  const debug_log = document.getElementById('debug_log');
  const event_log = document.getElementById('event_log');

  const gateway_url_input = document.getElementById('gateway_url');
  const bootstrap_token_input = document.getElementById('bootstrap_token');
  const device_id_input = document.getElementById('device_id');
  const device_credential_input = document.getElementById('device_credential');
  const resume_token_input = document.getElementById('resume_token');
  const conv_id_input = document.getElementById('conv_id');
  const from_seq_input = document.getElementById('from_seq');
  const seq_input = document.getElementById('seq');
  const msg_id_input = document.getElementById('msg_id');
  const ciphertext_input = document.getElementById('ciphertext_input');
  let social_user_id_input = null;
  let social_limit_input = null;
  let social_after_hash_input = null;
  let social_fetch_btn = null;
  let social_log_pre = null;
  let social_list = null;
  let dm_bridge_last_env_text = null;
  let dm_bridge_copy_btn = null;
  let dm_bridge_cli_block_input = null;
  let dm_bridge_parse_btn = null;
  let dm_bridge_send_btn = null;
  let dm_bridge_use_last_app_btn = null;
  let dm_bridge_send_last_app_btn = null;
  let dm_bridge_send_init_btn = null;
  let dm_bridge_status = null;
  let dm_bridge_autofill_status = null;
  let dm_bridge_expected_plaintext_pre = null;
  let dm_bridge_autofill_enabled_input = null;
  let dm_bridge_autofill_welcome_input = null;
  let dm_bridge_autofill_commit_input = null;
  let dm_bridge_autofill_app_input = null;
  let dm_import_env_input = null;
  let dm_expected_plaintext_input = null;

  const connect_start_btn = document.getElementById('connect_start');
  const connect_resume_btn = document.getElementById('connect_resume');
  const subscribe_btn = document.getElementById('subscribe_btn');
  const ack_btn = document.getElementById('ack_btn');
  const send_btn = document.getElementById('send_btn');
  const clear_log_btn = document.getElementById('clear_log');

  const db_name = 'gateway_web_demo';
  const db_version = 2;
  const store_name = 'settings';
  const transcripts_store_name = 'transcripts';
  const transcript_max_records = 200;
  const next_id = () => `msg-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const dm_kind_labels = {
    1: 'welcome',
    2: 'commit',
    3: 'app_ciphertext',
  };
  const cli_block_keys = ['welcome_env_b64', 'commit_env_b64', 'app_env_b64', 'expected_plaintext'];
  const dm_autofill_setting_keys = {
    enabled: 'dm_autofill_enabled',
    welcome: 'dm_autofill_welcome',
    commit: 'dm_autofill_commit',
    app: 'dm_autofill_app',
  };
  let last_conv_env_b64 = '';
  let parsed_app_env_b64 = '';
  let dm_outbox_welcome_env_b64 = '';
  let dm_outbox_commit_env_b64 = '';
  let dm_outbox_app_env_b64 = '';
  let transcript_status_text = null;
  let transcript_export_btn = null;
  let transcript_import_input = null;
  let transcript_paste_input = null;
  let transcript_paste_import_btn = null;
  let transcript_replay_btn = null;
  let transcript_summary_pre = null;
  let transcript_load_welcome_btn = null;
  let transcript_load_commit_btn = null;
  let transcript_load_app_btn = null;
  let transcript_last_import = null;
  const last_from_seq_by_conv_id = {};
  let last_selected_conv_id = null;

  const bytes_to_hex = (bytes) =>
    Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');

  const bytes_to_base64 = (bytes) => {
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 1) {
      binary += String.fromCharCode(bytes[offset]);
    }
    return btoa(binary);
  };

  const bytes_to_base64url = (bytes) => bytes_to_base64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

  const base64_to_bytes = (value) => {
    try {
      const binary = atob(value);
      const bytes = new Uint8Array(binary.length);
      for (let offset = 0; offset < binary.length; offset += 1) {
        bytes[offset] = binary.charCodeAt(offset);
      }
      return bytes;
    } catch (err) {
      return null;
    }
  };

  const sha256_hex = async (bytes) => {
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return bytes_to_hex(new Uint8Array(digest));
  };

  const build_canonical_transcript = (payload) => {
    const events = Array.isArray(payload.events) ? [...payload.events] : [];
    events.sort((a, b) => a.seq - b.seq);
    const canonical_events = events.map((event) => ({
      seq: event.seq,
      msg_id: typeof event.msg_id === 'string' ? event.msg_id : null,
      env: event.env,
    }));
    return {
      schema_version: 1,
      conv_id: payload.conv_id,
      from_seq: payload.from_seq === null ? null : payload.from_seq,
      next_seq: payload.next_seq === null ? null : payload.next_seq,
      events: canonical_events,
    };
  };

  const compute_transcript_digest = async (payload) => {
    const canonical_payload = build_canonical_transcript(payload);
    const canonical_json = JSON.stringify(canonical_payload);
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical_json));
    return bytes_to_base64url(new Uint8Array(digest));
  };

  const has_uppercase_key = (value) => {
    if (!value || typeof value !== 'object') {
      return false;
    }
    return Object.keys(value).some((key) => /[A-Z]/.test(key));
  };

  const describe_dm_env = (env_b64) => {
    if (typeof env_b64 !== 'string') {
      return null;
    }
    const env_bytes = base64_to_bytes(env_b64);
    if (!env_bytes || env_bytes.length < 1) {
      return null;
    }
    const kind = env_bytes[0];
    const payload_bytes = env_bytes.slice(1);
    const kind_label = dm_kind_labels[kind] || `unknown(0x${kind.toString(16).padStart(2, '0')})`;
    const payload_b64 = bytes_to_base64(payload_bytes);
    return { kind_label, payload_len: payload_bytes.length, payload_b64 };
  };

  const append_log = (line) => {
    const now = new Date().toISOString();
    debug_log.value += `[${now}] ${line}\n`;
    debug_log.scrollTop = debug_log.scrollHeight;
  };

  const reset_social_output = () => {
    if (social_log_pre) {
      social_log_pre.textContent = '';
    }
    if (social_list) {
      social_list.innerHTML = '';
    }
  };

  const render_social_error = (message) => {
    reset_social_output();
    if (social_log_pre) {
      social_log_pre.textContent = `error: ${message}`;
    }
  };

  const render_social_events = (events) => {
    reset_social_output();
    if (!Array.isArray(events)) {
      render_social_error('invalid response payload');
      return;
    }
    if (social_log_pre) {
      social_log_pre.textContent = JSON.stringify(events, null, 2);
    }
    if (!social_list) {
      return;
    }
    if (events.length === 0) {
      const empty_item = document.createElement('li');
      empty_item.textContent = 'no events';
      social_list.appendChild(empty_item);
      return;
    }
    events.forEach((event) => {
      const list_item = document.createElement('li');
      if (!event || typeof event !== 'object') {
        list_item.textContent = 'invalid event';
        social_list.appendChild(list_item);
        return;
      }
      const parts = [];
      if (event.user_id) {
        parts.push(`user_id=${event.user_id}`);
      }
      if (event.event_hash) {
        parts.push(`event_hash=${String(event.event_hash).slice(0, 12)}`);
      }
      if (event.kind) {
        parts.push(`kind=${event.kind}`);
      }
      if (typeof event.ts_ms !== 'undefined') {
        parts.push(`ts_ms=${event.ts_ms}`);
      }
      list_item.textContent = parts.length > 0 ? parts.join(' ') : 'event';
      social_list.appendChild(list_item);
    });
  };

  const to_social_base_url = (gateway_url) => {
    if (!gateway_url) {
      return null;
    }
    if (gateway_url.startsWith('ws://')) {
      return `http://${gateway_url.slice(5)}`;
    }
    if (gateway_url.startsWith('wss://')) {
      return `https://${gateway_url.slice(6)}`;
    }
    if (gateway_url.startsWith('http://') || gateway_url.startsWith('https://')) {
      return gateway_url;
    }
    return null;
  };

  const fetch_social_events = async () => {
    if (!social_user_id_input || !social_limit_input || !social_after_hash_input) {
      append_log('social feed inputs missing');
      return;
    }
    const user_id = social_user_id_input.value.trim();
    const limit_value = Number(social_limit_input.value);
    const after_hash = social_after_hash_input.value.trim();
    if (!user_id) {
      render_social_error('user_id required');
      return;
    }
    if (Number.isNaN(limit_value) || limit_value <= 0) {
      render_social_error('limit must be a positive number');
      return;
    }
    const gateway_url = gateway_url_input.value.trim();
    const base_url = to_social_base_url(gateway_url);
    if (!base_url) {
      render_social_error('gateway_url must start with ws:// or wss://');
      return;
    }
    const request_url = new URL('/v1/social/events', base_url);
    request_url.searchParams.set('user_id', user_id);
    request_url.searchParams.set('limit', String(limit_value));
    if (after_hash) {
      request_url.searchParams.set('after_hash', after_hash);
    }
    try {
      const response = await fetch(request_url.toString(), { method: 'GET' });
      if (!response.ok) {
        render_social_error(`http ${response.status} ${response.statusText}`);
        return;
      }
      const payload = await response.json();
      render_social_events(payload && payload.events ? payload.events : []);
    } catch (err) {
      render_social_error(err.message || 'fetch failed');
    }
    write_setting('social_user_id', user_id).catch((err) =>
      append_log(`failed to persist social_user_id: ${err.message}`)
    );
    write_setting('social_limit', limit_value).catch((err) =>
      append_log(`failed to persist social_limit: ${err.message}`)
    );
    write_setting('social_after_hash', after_hash).catch((err) =>
      append_log(`failed to persist social_after_hash: ${err.message}`)
    );
  };

  const render_event = (body, prefer_append = false) => {
    const entry = document.createElement('div');
    const parts = [];
    if (body.conv_id) {
      parts.push(`conv_id=${body.conv_id}`);
    }
    if (typeof body.seq !== 'undefined') {
      parts.push(`seq=${body.seq}`);
    }
    if (body.msg_id) {
      parts.push(`msg_id=${body.msg_id}`);
    }
    if (body.conv_home) {
      parts.push(`conv_home=${body.conv_home}`);
    }
    if (body.origin_gateway) {
      parts.push(`origin_gateway=${body.origin_gateway}`);
    }
    let env_display = typeof body.env !== 'undefined' ? JSON.stringify(body.env) : '';
    if (typeof body.env === 'string') {
      const env_details = describe_dm_env(body.env);
      if (env_details) {
        const payload_prefix = env_details.payload_b64.slice(0, 32);
        const payload_suffix = env_details.payload_b64.length > payload_prefix.length ? '...' : '';
        env_display =
          `dm_env(kind=${env_details.kind_label} payload_len=${env_details.payload_len}` +
          ` payload_b64_prefix=${payload_prefix}${payload_suffix})`;
      }
    }
    entry.textContent = `${parts.join(' ')} env=${env_display}`;
    if (prefer_append) {
      event_log.appendChild(entry);
    } else {
      event_log.prepend(entry);
    }
  };

  const open_db = () =>
    new Promise((resolve, reject) => {
      const request = indexedDB.open(db_name, db_version);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(store_name)) {
          db.createObjectStore(store_name, { keyPath: 'key' });
        }
        if (!db.objectStoreNames.contains(transcripts_store_name)) {
          const transcripts_store = db.createObjectStore(transcripts_store_name, { keyPath: 'key' });
          transcripts_store.createIndex('by_conv_id', 'conv_id', { unique: false });
        } else {
          const transcripts_store = request.transaction.objectStore(transcripts_store_name);
          if (!transcripts_store.indexNames.contains('by_conv_id')) {
            transcripts_store.createIndex('by_conv_id', 'conv_id', { unique: false });
          }
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('indexeddb open failed'));
    });

  const read_setting = async (key) => {
    const db = await open_db();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store_name, 'readonly');
      const store = tx.objectStore(store_name);
      const get_request = store.get(key);
      get_request.onsuccess = () => {
        resolve(get_request.result ? get_request.result.value : null);
      };
      get_request.onerror = () => reject(get_request.error || new Error('indexeddb read failed'));
      tx.oncomplete = () => db.close();
      tx.onerror = () => db.close();
    });
  };

  const cursor_key = (conv_id) => `cursor:${conv_id}`;

  const read_cursor = async (conv_id) => {
    if (!conv_id) {
      return null;
    }
    const stored_value = await read_setting(cursor_key(conv_id));
    if (stored_value && typeof stored_value === 'object' && typeof stored_value.next_seq === 'number') {
      return stored_value.next_seq;
    }
    if (typeof stored_value === 'number' && !Number.isNaN(stored_value)) {
      return stored_value;
    }
    return null;
  };

  const write_setting = async (key, value) => {
    const db = await open_db();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store_name, 'readwrite');
      const store = tx.objectStore(store_name);
      const put_request = store.put({ key, value });
      put_request.onsuccess = () => resolve();
      put_request.onerror = () => reject(put_request.error || new Error('indexeddb write failed'));
      tx.oncomplete = () => db.close();
      tx.onerror = () => db.close();
    });
  };

  const write_cursor = async (conv_id, next_seq) => {
    if (!conv_id) {
      return;
    }
    if (typeof next_seq !== 'number' || Number.isNaN(next_seq)) {
      return;
    }
    await write_setting(cursor_key(conv_id), next_seq);
  };

  const advance_cursor = async (conv_id, observed_seq) => {
    if (!conv_id) {
      return;
    }
    if (typeof observed_seq !== 'number' || Number.isNaN(observed_seq)) {
      return;
    }
    const stored_next_seq = (await read_cursor(conv_id)) ?? 1;
    const candidate_next_seq = observed_seq + 1;
    const next_seq = Math.max(stored_next_seq, candidate_next_seq, 1);
    await write_cursor(conv_id, next_seq);
  };

  const transcript_key = (conv_id, seq) => `${conv_id}:${seq}`;

  const record_transcript_event = async (conv_id, seq, msg_id, env) => {
    if (!conv_id) {
      return;
    }
    if (typeof seq !== 'number' || Number.isNaN(seq)) {
      return;
    }
    if (typeof env !== 'string') {
      return;
    }
    const db = await open_db();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(transcripts_store_name, 'readwrite');
      const store = tx.objectStore(transcripts_store_name);
      const record = { key: transcript_key(conv_id, seq), conv_id, seq, msg_id, env };
      store.put(record);
      if (store.indexNames.contains('by_conv_id')) {
        const index = store.index('by_conv_id');
        const range = IDBKeyRange.only(conv_id);
        const get_request = index.getAll(range);
        get_request.onsuccess = () => {
          const entries = Array.isArray(get_request.result) ? get_request.result : [];
          entries.sort((a, b) => a.seq - b.seq);
          if (entries.length > transcript_max_records) {
            const excess = entries.length - transcript_max_records;
            for (let offset = 0; offset < excess; offset += 1) {
              const entry = entries[offset];
              if (entry && entry.key) {
                store.delete(entry.key);
              }
            }
          }
        };
      }
      tx.oncomplete = () => {
        db.close();
        resolve();
      };
      tx.onerror = () => {
        db.close();
        reject(tx.error || new Error('indexeddb transcript write failed'));
      };
    });
  };

  const read_transcripts = async (conv_id) => {
    if (!conv_id) {
      return [];
    }
    const db = await open_db();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(transcripts_store_name, 'readonly');
      const store = tx.objectStore(transcripts_store_name);
      let get_request;
      if (store.indexNames.contains('by_conv_id')) {
        const index = store.index('by_conv_id');
        get_request = index.getAll(IDBKeyRange.only(conv_id));
      } else {
        get_request = store.getAll();
      }
      get_request.onsuccess = () => {
        let entries = Array.isArray(get_request.result) ? get_request.result : [];
        if (!store.indexNames.contains('by_conv_id')) {
          entries = entries.filter((entry) => entry && entry.conv_id === conv_id);
        }
        entries.sort((a, b) => a.seq - b.seq);
        resolve(entries);
      };
      get_request.onerror = () => reject(get_request.error || new Error('indexeddb transcript read failed'));
      tx.oncomplete = () => db.close();
      tx.onerror = () => db.close();
    });
  };

  const set_transcript_status = (message) => {
    if (transcript_status_text) {
      transcript_status_text.textContent = message;
    }
  };

  const set_transcript_summary = (summary) => {
    if (!transcript_summary_pre) {
      return;
    }
    if (!summary) {
      transcript_summary_pre.textContent = 'digest: missing\nevents: 0\nkinds: welcome=0 commit=0 app=0 unknown=0';
      return;
    }
    const digest_status = summary.digest_status || 'missing';
    const digest_value = summary.digest_value || 'none';
    const event_count = typeof summary.event_count === 'number' ? summary.event_count : 0;
    const kind_counts = summary.kind_counts || {};
    const welcome_count = kind_counts.welcome || 0;
    const commit_count = kind_counts.commit || 0;
    const app_count = kind_counts.app || 0;
    const unknown_count = kind_counts.unknown || 0;
    transcript_summary_pre.textContent =
      `digest: ${digest_status} (${digest_value})\n` +
      `events: ${event_count}\n` +
      `kinds: welcome=${welcome_count} commit=${commit_count} app=${app_count} unknown=${unknown_count}`;
  };

  const render_transcript_events = (conv_id, events) => {
    event_log.innerHTML = '';
    if (!Array.isArray(events) || events.length === 0) {
      return;
    }
    events.forEach((event) => {
      render_event(
        {
          conv_id,
          seq: event.seq,
          msg_id: event.msg_id,
          env: event.env,
        },
        true
      );
    });
  };

  const latest_transcript_env = (events) => {
    if (!Array.isArray(events) || events.length === 0) {
      return null;
    }
    const sorted = [...events].filter((event) => event && typeof event.seq === 'number');
    sorted.sort((a, b) => a.seq - b.seq);
    const last_event = sorted[sorted.length - 1];
    if (last_event && typeof last_event.env === 'string') {
      return last_event.env;
    }
    return null;
  };

  const classify_env_kind = (env_b64) => {
    if (typeof env_b64 !== 'string') {
      return { kind: null, kind_label: 'unknown', valid: false };
    }
    const env_bytes = base64_to_bytes(env_b64);
    if (!env_bytes || env_bytes.length < 1) {
      return { kind: null, kind_label: 'unknown', valid: false };
    }
    const kind = env_bytes[0];
    if (kind === 1) {
      return { kind, kind_label: 'welcome', valid: true };
    }
    if (kind === 2) {
      return { kind, kind_label: 'commit', valid: true };
    }
    if (kind === 3) {
      return { kind, kind_label: 'app', valid: true };
    }
    return { kind, kind_label: 'unknown', valid: true };
  };

  const summarize_transcript = (events) => {
    const summary = {
      kind_counts: {
        welcome: 0,
        commit: 0,
        app: 0,
        unknown: 0,
      },
      selected_envs: {
        welcome_env_b64: null,
        commit_env_b64: null,
        app_env_b64: null,
      },
    };
    if (!Array.isArray(events) || events.length === 0) {
      return summary;
    }
    const sorted = [...events].sort((a, b) => a.seq - b.seq);
    for (const event of sorted) {
      const result = classify_env_kind(event.env);
      if (!result.valid) {
        summary.kind_counts.unknown += 1;
        continue;
      }
      if (result.kind === 1) {
        summary.kind_counts.welcome += 1;
        if (!summary.selected_envs.welcome_env_b64) {
          summary.selected_envs.welcome_env_b64 = event.env;
        }
        continue;
      }
      if (result.kind === 2) {
        summary.kind_counts.commit += 1;
        if (!summary.selected_envs.commit_env_b64) {
          summary.selected_envs.commit_env_b64 = event.env;
        }
        continue;
      }
      if (result.kind === 3) {
        summary.kind_counts.app += 1;
        summary.selected_envs.app_env_b64 = event.env;
        continue;
      }
      summary.kind_counts.unknown += 1;
    }
    return summary;
  };

  const validate_transcript_payload = (payload) => {
    if (has_uppercase_key(payload)) {
      return { error: 'camelCase keys not allowed' };
    }
    const conv_id_value = payload && typeof payload.conv_id === 'string' ? payload.conv_id : null;
    if (!conv_id_value) {
      return { error: 'conv_id required' };
    }
    const raw_events = payload && Array.isArray(payload.events) ? payload.events : null;
    if (!raw_events) {
      return { error: 'events required' };
    }
    const seen_seq = new Set();
    const normalized = [];
    for (const event of raw_events) {
      if (!event || typeof event !== 'object') {
        continue;
      }
      if (has_uppercase_key(event)) {
        return { error: 'camelCase keys not allowed' };
      }
      const seq = typeof event.seq === 'number' ? event.seq : Number(event.seq);
      if (typeof seq !== 'number' || Number.isNaN(seq) || seq < 1 || !Number.isInteger(seq)) {
        return { error: 'invalid seq' };
      }
      if (seen_seq.has(seq)) {
        return { error: 'duplicate seq' };
      }
      seen_seq.add(seq);
      const env = typeof event.env === 'string' ? event.env : typeof event.env_b64 === 'string' ? event.env_b64 : null;
      if (typeof env !== 'string') {
        return { error: 'invalid env' };
      }
      const msg_id = typeof event.msg_id === 'string' && event.msg_id ? event.msg_id : null;
      normalized.push({ seq, msg_id, env });
    }
    normalized.sort((a, b) => a.seq - b.seq);
    const from_seq_value = payload && typeof payload.from_seq === 'number' ? payload.from_seq : null;
    const next_seq_value = payload && typeof payload.next_seq === 'number' ? payload.next_seq : null;
    const digest_value = payload && typeof payload.digest_sha256_b64 === 'string' ? payload.digest_sha256_b64 : null;
    const expected_plaintext =
      payload && typeof payload.expected_plaintext === 'string' ? payload.expected_plaintext : null;
    return {
      conv_id: conv_id_value,
      from_seq: from_seq_value,
      next_seq: next_seq_value,
      events: normalized,
      digest_sha256_b64: digest_value,
      expected_plaintext,
    };
  };

  const import_transcript_payload = async (payload) => {
    const validated = validate_transcript_payload(payload);
    if (validated.error) {
      set_transcript_status(`status: error (${validated.error})`);
      set_transcript_summary(null);
      return;
    }
    const digest_payload = {
      conv_id: validated.conv_id,
      from_seq: validated.from_seq,
      next_seq: validated.next_seq,
      events: validated.events,
    };
    let digest_status = 'missing';
    let digest_value = validated.digest_sha256_b64;
    if (digest_value) {
      const computed_digest = await compute_transcript_digest(digest_payload);
      digest_status = computed_digest === digest_value ? 'ok' : 'mismatch';
    } else {
      digest_value = null;
    }
    const summary = summarize_transcript(validated.events);
    summary.digest_status = digest_status;
    summary.digest_value = digest_value;
    summary.event_count = validated.events.length;
    transcript_last_import = {
      conv_id: validated.conv_id,
      from_seq: validated.from_seq,
      next_seq: validated.next_seq,
      events: validated.events,
      digest_sha256_b64: validated.digest_sha256_b64,
      expected_plaintext: validated.expected_plaintext,
      selected_envs: summary.selected_envs,
    };
    render_transcript_events(validated.conv_id, validated.events);
    set_transcript_summary(summary);
    const digest_note =
      digest_status === 'missing' ? '' : `; digest ${digest_status}: ${digest_value || 'none'}`;
    set_transcript_status(`status: imported ${validated.events.length} events${digest_note}`);
  };

  const find_dm_import_input = (label_text) => {
    const labels = Array.from(document.querySelectorAll('label'));
    for (const label of labels) {
      const label_value = label.textContent ? label.textContent.trim() : '';
      if (!label_value.startsWith(label_text)) {
        continue;
      }
      const input = label.querySelector('textarea, input');
      if (input) {
        return input;
      }
    }
    return null;
  };

  const hydrate_dm_import_inputs = () => {
    if (!dm_import_env_input) {
      dm_import_env_input = find_dm_import_input('incoming_env_b64');
    }
    if (!dm_expected_plaintext_input) {
      dm_expected_plaintext_input = find_dm_import_input('expected_plaintext');
    }
  };

  const update_dm_bridge_last_env = () => {
    if (!dm_bridge_last_env_text) {
      return;
    }
    if (!last_conv_env_b64) {
      dm_bridge_last_env_text.textContent = 'last env: none received yet';
      return;
    }
    const env_details = describe_dm_env(last_conv_env_b64);
    if (!env_details) {
      dm_bridge_last_env_text.textContent = 'last env: invalid base64';
      return;
    }
    dm_bridge_last_env_text.textContent =
      `last env: kind=${env_details.kind_label} payload_len=${env_details.payload_len}`;
  };

  const parse_cli_block = (block_text) => {
    const parsed = {
      welcome_env_b64: '',
      commit_env_b64: '',
      app_env_b64: '',
      expected_plaintext: '',
    };
    const lines = block_text.split(/\r?\n/);
    for (const raw_line of lines) {
      const line = raw_line.trim();
      if (!line) {
        continue;
      }
      const eq_index = line.indexOf('=');
      if (eq_index < 0) {
        continue;
      }
      const key = line.slice(0, eq_index).trim();
      if (!cli_block_keys.includes(key)) {
        continue;
      }
      const value = line.slice(eq_index + 1).trim();
      if (value) {
        parsed[key] = value;
      }
    }
    const found_keys = cli_block_keys.filter((key) => parsed[key]);
    return { parsed, found_keys };
  };

  const set_dm_bridge_status = (message) => {
    if (!dm_bridge_status) {
      return;
    }
    dm_bridge_status.textContent = message;
  };

  const get_dm_outbox_envs = () => ({
    welcome_env_b64: dm_outbox_welcome_env_b64 || '',
    commit_env_b64: dm_outbox_commit_env_b64 || '',
    app_env_b64: dm_outbox_app_env_b64 || '',
  });

  const read_dm_ui_envs = () => {
    const output_pre = document.getElementById('dm_output');
    if (!output_pre) {
      return { error: 'dm_output missing' };
    }
    const output_text = output_pre.textContent || '';
    if (!output_text.trim()) {
      return { error: 'dm_output empty' };
    }
    const envs = {
      welcome_env_b64: '',
      commit_env_b64: '',
      app_env_b64: '',
    };
    const env_regex = /^(welcome_env_b64|commit_env_b64|app_env_b64):\s*(\S+)/;
    const lines = output_text.split(/\r?\n/);
    for (const raw_line of lines) {
      const line = raw_line.trim();
      if (!line) {
        continue;
      }
      const match = line.match(env_regex);
      if (!match) {
        continue;
      }
      const key = match[1];
      const value = match[2];
      if (value) {
        envs[key] = value;
      }
    }
    const found_keys = Object.keys(envs).filter((key) => envs[key]);
    if (!found_keys.length) {
      return { error: 'no dm_ui envs found' };
    }
    return { envs, found_keys };
  };

  const read_dm_bridge_envs = () => {
    const outbox_envs = get_dm_outbox_envs();
    const outbox_keys = Object.keys(outbox_envs).filter((key) => outbox_envs[key]);
    if (outbox_keys.length > 0) {
      return { envs: outbox_envs, found_keys: outbox_keys, source: 'outbox' };
    }
    const fallback = read_dm_ui_envs();
    if (fallback.error) {
      return fallback;
    }
    return { envs: fallback.envs, found_keys: fallback.found_keys, source: 'dm_output' };
  };

  const maybe_dispatch_dm_commit_echo = (body) => {
    if (!body || typeof body !== 'object') {
      return;
    }
    const selected_conv_id = conv_id_input ? conv_id_input.value.trim() : '';
    if (!selected_conv_id || body.conv_id !== selected_conv_id) {
      return;
    }
    if (typeof body.env !== 'string') {
      return;
    }
    const env_bytes = base64_to_bytes(body.env);
    if (!env_bytes || env_bytes.length < 1) {
      append_log('dm commit echo check skipped: invalid env');
      return;
    }
    if (env_bytes[0] !== 2) {
      return;
    }
    const output = read_dm_bridge_envs();
    if (output.error) {
      append_log(`dm commit echo check skipped: ${output.error}`);
      return;
    }
    const commit_env_b64 = output.envs.commit_env_b64;
    if (!commit_env_b64) {
      append_log('dm commit echo check skipped: commit_env_b64 missing');
      return;
    }
    if (body.env !== commit_env_b64) {
      return;
    }
    const seq_value = typeof body.seq === 'number' ? body.seq : null;
    window.dispatchEvent(
      new CustomEvent('dm.commit.echoed', {
        detail: {
          conv_id: body.conv_id,
          env_b64: body.env,
          seq: seq_value,
        },
      })
    );
  };

  const maybe_dispatch_conv_event_received = (body) => {
    if (!body || typeof body !== 'object') {
      return;
    }
    const selected_conv_id = conv_id_input ? conv_id_input.value.trim() : '';
    if (!selected_conv_id || body.conv_id !== selected_conv_id) {
      return;
    }
    if (typeof body.conv_id !== 'string' || !body.conv_id) {
      return;
    }
    if (typeof body.env !== 'string' || typeof body.msg_id !== 'string') {
      return;
    }
    const seq_value = Number.isInteger(body.seq) ? body.seq : null;
    if (!seq_value || seq_value < 1) {
      return;
    }
    const env_bytes = base64_to_bytes(body.env);
    if (!env_bytes || env_bytes.length < 1) {
      return;
    }
    window.dispatchEvent(
      new CustomEvent('conv.event.received', {
        detail: {
          conv_id: body.conv_id,
          seq: seq_value,
          msg_id: body.msg_id,
          env: body.env,
        },
      })
    );
  };

  const validate_env_b64_for_send = (env_b64, label) => {
    if (!env_b64) {
      return { ok: false, reason: `missing ${label}` };
    }
    const env_bytes = base64_to_bytes(env_b64);
    if (!env_bytes || env_bytes.length < 1) {
      append_log(`invalid base64 for ${label}`);
      return { ok: false, reason: `invalid base64 for ${label}` };
    }
    return { ok: true, env_bytes };
  };

  const set_dm_expected_plaintext = (value) => {
    hydrate_dm_import_inputs();
    if (dm_expected_plaintext_input) {
      dm_expected_plaintext_input.value = value;
    } else if (dm_bridge_expected_plaintext_pre) {
      dm_bridge_expected_plaintext_pre.textContent = value ? `expected_plaintext: ${value}` : '';
    }
  };

  const set_dm_incoming_env = (value) => {
    hydrate_dm_import_inputs();
    if (dm_import_env_input) {
      dm_import_env_input.value = value;
      return true;
    }
    return false;
  };

  const update_dm_autofill_status = (summary) => {
    if (!dm_bridge_autofill_status) {
      return;
    }
    if (!summary) {
      dm_bridge_autofill_status.textContent = 'auto-fill: idle';
      return;
    }
    dm_bridge_autofill_status.textContent = summary;
  };

  const set_dm_autofill_controls_enabled = (enabled) => {
    const control_inputs = [
      dm_bridge_autofill_welcome_input,
      dm_bridge_autofill_commit_input,
      dm_bridge_autofill_app_input,
    ];
    control_inputs.forEach((input) => {
      if (input) {
        input.disabled = !enabled;
      }
    });
    if (!enabled) {
      update_dm_autofill_status(null);
    }
  };

  const persist_dm_autofill_settings = () => {
    const enabled = dm_bridge_autofill_enabled_input ? dm_bridge_autofill_enabled_input.checked : false;
    const welcome_enabled = dm_bridge_autofill_welcome_input ? dm_bridge_autofill_welcome_input.checked : false;
    const commit_enabled = dm_bridge_autofill_commit_input ? dm_bridge_autofill_commit_input.checked : false;
    const app_enabled = dm_bridge_autofill_app_input ? dm_bridge_autofill_app_input.checked : false;
    write_setting(dm_autofill_setting_keys.enabled, enabled).catch((err) =>
      append_log(`failed to persist dm_autofill_enabled: ${err.message}`)
    );
    write_setting(dm_autofill_setting_keys.welcome, welcome_enabled).catch((err) =>
      append_log(`failed to persist dm_autofill_welcome: ${err.message}`)
    );
    write_setting(dm_autofill_setting_keys.commit, commit_enabled).catch((err) =>
      append_log(`failed to persist dm_autofill_commit: ${err.message}`)
    );
    write_setting(dm_autofill_setting_keys.app, app_enabled).catch((err) =>
      append_log(`failed to persist dm_autofill_app: ${err.message}`)
    );
  };

  const handle_dm_autofill_toggle = () => {
    const enabled = dm_bridge_autofill_enabled_input ? dm_bridge_autofill_enabled_input.checked : false;
    set_dm_autofill_controls_enabled(enabled);
    persist_dm_autofill_settings();
  };

  const handle_dm_autofill_kind_toggle = () => {
    persist_dm_autofill_settings();
  };

  const maybe_autofill_dm_env = (body) => {
    if (!body || typeof body !== 'object') {
      return;
    }
    if (!dm_bridge_autofill_enabled_input || !dm_bridge_autofill_enabled_input.checked) {
      return;
    }
    const conv_id = typeof body.conv_id === 'string' ? body.conv_id : '';
    const target_conv_id = conv_id_input.value.trim();
    if (!conv_id || !target_conv_id || conv_id !== target_conv_id) {
      return;
    }
    if (typeof body.env !== 'string') {
      return;
    }
    const env_bytes = base64_to_bytes(body.env);
    if (!env_bytes || env_bytes.length < 1) {
      return;
    }
    const kind = env_bytes[0];
    const kind_label = dm_kind_labels[kind];
    if (!kind_label) {
      return;
    }
    const kind_allowed =
      (kind === 1 && dm_bridge_autofill_welcome_input && dm_bridge_autofill_welcome_input.checked) ||
      (kind === 2 && dm_bridge_autofill_commit_input && dm_bridge_autofill_commit_input.checked) ||
      (kind === 3 && dm_bridge_autofill_app_input && dm_bridge_autofill_app_input.checked);
    if (!kind_allowed) {
      return;
    }
    const did_set = set_dm_incoming_env(body.env);
    if (!did_set) {
      update_dm_autofill_status('auto-fill: idle');
      return;
    }
    const seq_value = typeof body.seq === 'number' && !Number.isNaN(body.seq) ? body.seq : '?';
    update_dm_autofill_status(
      `auto-fill: ${kind_label} env (seq=${seq_value} conv_id=${conv_id}) — click "Load ${kind_label} env" in DM UI`
    );
  };

  const send_ciphertext_with_deterministic_id = async (conv_id, ciphertext) => {
    if (!conv_id) {
      append_log('missing conv_id');
      return;
    }
    if (!ciphertext) {
      append_log('missing ciphertext');
      return;
    }
    let msg_id = msg_id_input.value.trim();
    if (!msg_id) {
      const env_bytes = base64_to_bytes(ciphertext);
      if (!env_bytes) {
        append_log('invalid base64 ciphertext');
        return;
      }
      msg_id = await sha256_hex(env_bytes);
      msg_id_input.value = msg_id;
    }
    client.send_ciphertext(conv_id, msg_id, ciphertext);
  };

  const handle_gateway_send_env = async (event) => {
    try {
      const detail = event && event.detail ? event.detail : null;
      if (!detail || typeof detail !== 'object') {
        append_log('gateway.send_env missing detail');
        return;
      }
      const conv_id = typeof detail.conv_id === 'string' ? detail.conv_id.trim() : '';
      const env_b64 = typeof detail.env_b64 === 'string' ? detail.env_b64.trim() : '';
      const msg_id = typeof detail.msg_id === 'string' ? detail.msg_id.trim() : '';
      if (!conv_id) {
        append_log('gateway.send_env missing conv_id');
        return;
      }
      if (!env_b64) {
        append_log('gateway.send_env missing env_b64');
        return;
      }
      const validation = validate_env_b64_for_send(env_b64, 'env_b64');
      if (!validation.ok) {
        append_log(`gateway.send_env ${validation.reason}`);
        return;
      }
      conv_id_input.value = conv_id;
      ciphertext_input.value = env_b64;
      msg_id_input.value = msg_id;
      await send_ciphertext_with_deterministic_id(conv_id, env_b64);
    } catch (err) {
      append_log(`gateway.send_env failed: ${err.message}`);
    }
  };

  class GatewayWsClient {
    constructor() {
      this.ws = null;
      this.pending_frames = [];
    }

    connect(url) {
      if (this.ws) {
        this.ws.close();
      }
      this.pending_frames = [];
      append_log(`connecting to ${url}`);
      this.ws = new WebSocket(url);
      this.ws.addEventListener('open', () => {
        connection_status.textContent = 'connected';
        append_log('websocket open');
        this.flush_pending();
      });
      this.ws.addEventListener('close', (evt) => {
        connection_status.textContent = 'disconnected';
        append_log(`websocket closed (code=${evt.code})`);
      });
      this.ws.addEventListener('error', (evt) => {
        append_log(`websocket error: ${evt.message || 'unknown'}`);
      });
      this.ws.addEventListener('message', (evt) => {
        let message;
        try {
          message = JSON.parse(evt.data);
        } catch (err) {
          append_log(`invalid json: ${evt.data}`);
          return;
        }
        this.handle_message(message);
      });
    }

    ensure_connected() {
      return this.ws && this.ws.readyState === WebSocket.OPEN;
    }

    send_frame(type, body) {
      const envelope = { v: 1, t: type, id: next_id(), ts: Date.now(), body: body || {} };
      if (this.ensure_connected()) {
        this.ws.send(JSON.stringify(envelope));
        append_log(`sent ${type}`);
        return;
      }
      if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
        this.pending_frames.push(envelope);
        append_log(`queued ${type} until open`);
        return;
      }
      append_log('websocket not connected');
    }

    flush_pending() {
      if (!this.ensure_connected()) {
        return;
      }
      while (this.pending_frames.length > 0) {
        const envelope = this.pending_frames.shift();
        this.ws.send(JSON.stringify(envelope));
        append_log(`sent queued ${envelope.t}`);
      }
    }

    start_session(auth_token, device_id, device_credential) {
      if (!auth_token) {
        append_log('missing auth_token');
        return;
      }
      const body = { auth_token };
      if (device_id) {
        body.device_id = device_id;
      }
      if (device_credential) {
        body.device_credential = device_credential;
      }
      this.send_frame('session.start', body);
    }

    resume_session(resume_token) {
      if (!resume_token) {
        append_log('missing resume_token');
        return;
      }
      this.send_frame('session.resume', { resume_token });
    }

    subscribe(conv_id, from_seq) {
      if (!conv_id) {
        append_log('missing conv_id');
        return;
      }
      const body = { conv_id };
      if (typeof from_seq === 'number' && !Number.isNaN(from_seq)) {
        body.from_seq = from_seq;
      }
      this.send_frame('conv.subscribe', body);
    }

    ack(conv_id, seq) {
      if (!conv_id) {
        append_log('missing conv_id');
        return;
      }
      if (typeof seq !== 'number' || Number.isNaN(seq)) {
        append_log('missing seq');
        return;
      }
      this.send_frame('conv.ack', { conv_id, seq });
    }

    send_ciphertext(conv_id, msg_id, ciphertext) {
      if (!conv_id) {
        append_log('missing conv_id');
        return;
      }
      if (!msg_id) {
        append_log('missing msg_id');
        return;
      }
      if (!ciphertext) {
        append_log('missing ciphertext');
        return;
      }
      this.send_frame('conv.send', { conv_id, msg_id, env: ciphertext });
    }

    handle_message(message) {
      if (!message || typeof message !== 'object') {
        append_log('ignored non-object message');
        return;
      }
      const body = message.body || {};
      if (message.t === 'ping') {
        this.send_frame('pong', {});
        append_log('responded to ping');
        return;
      }
      if (message.t === 'session.ready') {
        append_log(`session ready: ${JSON.stringify(body)}`);
        if (body.resume_token) {
          resume_token_input.value = body.resume_token;
          write_setting('resume_token', body.resume_token).catch((err) =>
            append_log(`failed to persist resume_token: ${err.message}`)
          );
        }
        return;
      }
      if (message.t === 'conv.event') {
        if (typeof body.env === 'string') {
          last_conv_env_b64 = body.env;
          update_dm_bridge_last_env();
          maybe_autofill_dm_env(body);
        }
        maybe_dispatch_dm_commit_echo(body);
        maybe_dispatch_conv_event_received(body);
        render_event(body);
        record_transcript_event(body.conv_id, body.seq, body.msg_id, body.env).catch((err) =>
          append_log(`failed to persist transcript: ${err.message}`)
        );
        advance_cursor(body.conv_id, body.seq).catch((err) =>
          append_log(`failed to persist conv.event cursor: ${err.message}`)
        );
        return;
      }
      if (message.t === 'conv.acked') {
        append_log(`conv.acked ${JSON.stringify(body)}`);
        advance_cursor(body.conv_id, body.seq).catch((err) =>
          append_log(`failed to persist conv.acked cursor: ${err.message}`)
        );
        return;
      }
      if (message.t === 'error') {
        append_log(`error ${JSON.stringify(body)}`);
        return;
      }
      append_log(`received ${message.t || 'unknown'}: ${JSON.stringify(body)}`);
    }
  }

  const client = new GatewayWsClient();

  const build_dm_bridge_panel = () => {
    const fieldset = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = 'DM Bridge';
    fieldset.appendChild(legend);

    const summary = document.createElement('p');
    summary.textContent = 'last env: none received yet';
    fieldset.appendChild(summary);

    const copy_row = document.createElement('div');
    copy_row.className = 'button-row';
    const copy_btn = document.createElement('button');
    copy_btn.type = 'button';
    copy_btn.textContent = 'Copy last env to DM import';
    copy_row.appendChild(copy_btn);
    fieldset.appendChild(copy_row);

    const cli_label = document.createElement('label');
    cli_label.textContent = 'Paste CLI block';
    const cli_block_input = document.createElement('textarea');
    cli_block_input.rows = 6;
    cli_block_input.cols = 64;
    cli_label.appendChild(cli_block_input);
    fieldset.appendChild(cli_label);

    const parse_row = document.createElement('div');
    parse_row.className = 'button-row';
    const parse_btn = document.createElement('button');
    parse_btn.type = 'button';
    parse_btn.textContent = 'Parse';
    parse_row.appendChild(parse_btn);
    fieldset.appendChild(parse_row);

    const send_row = document.createElement('div');
    send_row.className = 'button-row';
    const send_btn = document.createElement('button');
    send_btn.type = 'button';
    send_btn.textContent = 'Send app_env to gateway';
    send_row.appendChild(send_btn);
    fieldset.appendChild(send_row);

    const dm_ui_row = document.createElement('div');
    dm_ui_row.className = 'button-row';
    const use_last_app_btn = document.createElement('button');
    use_last_app_btn.type = 'button';
    use_last_app_btn.textContent = 'Use last DM UI app_env';
    const send_last_app_btn = document.createElement('button');
    send_last_app_btn.type = 'button';
    send_last_app_btn.textContent = 'Send last DM UI app_env to gateway';
    const send_init_btn = document.createElement('button');
    send_init_btn.type = 'button';
    send_init_btn.textContent = 'Send DM UI init envs (welcome then commit)';
    dm_ui_row.appendChild(use_last_app_btn);
    dm_ui_row.appendChild(send_last_app_btn);
    dm_ui_row.appendChild(send_init_btn);
    fieldset.appendChild(dm_ui_row);

    const status = document.createElement('p');
    status.textContent = 'status: idle';
    fieldset.appendChild(status);

    const autofill_row = document.createElement('div');
    autofill_row.className = 'button-row';
    const autofill_label = document.createElement('label');
    const autofill_input = document.createElement('input');
    autofill_input.type = 'checkbox';
    autofill_label.appendChild(autofill_input);
    autofill_label.appendChild(document.createTextNode(' Auto-fill DM UI from live events'));
    autofill_row.appendChild(autofill_label);
    fieldset.appendChild(autofill_row);

    const autofill_kind_row = document.createElement('div');
    autofill_kind_row.className = 'button-row';
    const welcome_label = document.createElement('label');
    const welcome_input = document.createElement('input');
    welcome_input.type = 'checkbox';
    welcome_input.checked = true;
    welcome_input.disabled = true;
    welcome_label.appendChild(welcome_input);
    welcome_label.appendChild(document.createTextNode(' welcome (kind=1)'));
    const commit_label = document.createElement('label');
    const commit_input = document.createElement('input');
    commit_input.type = 'checkbox';
    commit_input.checked = true;
    commit_input.disabled = true;
    commit_label.appendChild(commit_input);
    commit_label.appendChild(document.createTextNode(' commit (kind=2)'));
    const app_label = document.createElement('label');
    const app_input = document.createElement('input');
    app_input.type = 'checkbox';
    app_input.checked = true;
    app_input.disabled = true;
    app_label.appendChild(app_input);
    app_label.appendChild(document.createTextNode(' app (kind=3)'));
    autofill_kind_row.appendChild(welcome_label);
    autofill_kind_row.appendChild(commit_label);
    autofill_kind_row.appendChild(app_label);
    fieldset.appendChild(autofill_kind_row);

    const autofill_status = document.createElement('p');
    autofill_status.textContent = 'auto-fill: idle';
    fieldset.appendChild(autofill_status);

    const expected_plaintext_pre = document.createElement('pre');
    expected_plaintext_pre.textContent = '';
    fieldset.appendChild(expected_plaintext_pre);

    const dm_status = document.getElementById('dm_status');
    const dm_fieldset = dm_status ? dm_status.closest('fieldset') : null;
    if (dm_fieldset && dm_fieldset.parentNode) {
      dm_fieldset.parentNode.insertBefore(fieldset, dm_fieldset);
    } else {
      document.body.appendChild(fieldset);
    }

    dm_bridge_last_env_text = summary;
    dm_bridge_copy_btn = copy_btn;
    dm_bridge_cli_block_input = cli_block_input;
    dm_bridge_parse_btn = parse_btn;
    dm_bridge_send_btn = send_btn;
    dm_bridge_use_last_app_btn = use_last_app_btn;
    dm_bridge_send_last_app_btn = send_last_app_btn;
    dm_bridge_send_init_btn = send_init_btn;
    dm_bridge_status = status;
    dm_bridge_autofill_status = autofill_status;
    dm_bridge_expected_plaintext_pre = expected_plaintext_pre;
    dm_bridge_autofill_enabled_input = autofill_input;
    dm_bridge_autofill_welcome_input = welcome_input;
    dm_bridge_autofill_commit_input = commit_input;
    dm_bridge_autofill_app_input = app_input;
  };

  const build_transcript_panel = () => {
    const fieldset = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = 'Transcript';
    fieldset.appendChild(legend);

    const export_row = document.createElement('div');
    export_row.className = 'button-row';
    const export_btn = document.createElement('button');
    export_btn.type = 'button';
    export_btn.textContent = 'Export transcript';
    export_row.appendChild(export_btn);
    fieldset.appendChild(export_row);

    const import_label = document.createElement('label');
    import_label.textContent = 'Import transcript';
    const import_input = document.createElement('input');
    import_input.type = 'file';
    import_input.accept = 'application/json';
    import_label.appendChild(import_input);
    fieldset.appendChild(import_label);

    const paste_label = document.createElement('label');
    paste_label.textContent = 'Paste transcript JSON';
    const paste_input = document.createElement('textarea');
    paste_input.rows = 6;
    paste_input.cols = 64;
    paste_label.appendChild(paste_input);
    fieldset.appendChild(paste_label);

    const paste_row = document.createElement('div');
    paste_row.className = 'button-row';
    const paste_import_btn = document.createElement('button');
    paste_import_btn.type = 'button';
    paste_import_btn.textContent = 'Import pasted transcript';
    paste_row.appendChild(paste_import_btn);
    fieldset.appendChild(paste_row);

    const replay_row = document.createElement('div');
    replay_row.className = 'button-row';
    const replay_btn = document.createElement('button');
    replay_btn.type = 'button';
    replay_btn.textContent = 'Replay to DM Bridge';
    replay_row.appendChild(replay_btn);
    fieldset.appendChild(replay_row);

    const load_row = document.createElement('div');
    load_row.className = 'button-row';
    const load_welcome_btn = document.createElement('button');
    load_welcome_btn.type = 'button';
    load_welcome_btn.textContent = 'Load welcome into DM UI';
    const load_commit_btn = document.createElement('button');
    load_commit_btn.type = 'button';
    load_commit_btn.textContent = 'Load commit into DM UI';
    const load_app_btn = document.createElement('button');
    load_app_btn.type = 'button';
    load_app_btn.textContent = 'Load app into DM UI';
    load_row.appendChild(load_welcome_btn);
    load_row.appendChild(load_commit_btn);
    load_row.appendChild(load_app_btn);
    fieldset.appendChild(load_row);

    const status = document.createElement('p');
    status.textContent = 'status: idle';
    fieldset.appendChild(status);

    const summary_pre = document.createElement('pre');
    summary_pre.textContent = 'digest: missing\nevents: 0\nkinds: welcome=0 commit=0 app=0 unknown=0';
    fieldset.appendChild(summary_pre);

    const dm_fieldset = dm_bridge_last_env_text ? dm_bridge_last_env_text.closest('fieldset') : null;
    if (dm_fieldset && dm_fieldset.parentNode) {
      dm_fieldset.parentNode.insertBefore(fieldset, dm_fieldset.nextSibling);
    } else {
      document.body.appendChild(fieldset);
    }

    transcript_status_text = status;
    transcript_export_btn = export_btn;
    transcript_import_input = import_input;
    transcript_paste_input = paste_input;
    transcript_paste_import_btn = paste_import_btn;
    transcript_replay_btn = replay_btn;
    transcript_summary_pre = summary_pre;
    transcript_load_welcome_btn = load_welcome_btn;
    transcript_load_commit_btn = load_commit_btn;
    transcript_load_app_btn = load_app_btn;
  };

  const build_social_panel = () => {
    const fieldset = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = 'Social feed';
    fieldset.appendChild(legend);

    const user_id_label = document.createElement('label');
    user_id_label.textContent = 'user_id';
    const user_id_input = document.createElement('input');
    user_id_input.type = 'text';
    user_id_input.id = 'social_user_id';
    user_id_input.size = 32;
    user_id_label.appendChild(user_id_input);
    fieldset.appendChild(user_id_label);

    const limit_label = document.createElement('label');
    limit_label.textContent = 'limit';
    const limit_input = document.createElement('input');
    limit_input.type = 'number';
    limit_input.id = 'social_limit';
    limit_input.min = '1';
    limit_input.value = '50';
    limit_label.appendChild(limit_input);
    fieldset.appendChild(limit_label);

    const after_hash_label = document.createElement('label');
    after_hash_label.textContent = 'after_hash (optional)';
    const after_hash_input = document.createElement('input');
    after_hash_input.type = 'text';
    after_hash_input.id = 'social_after_hash';
    after_hash_input.size = 48;
    after_hash_label.appendChild(after_hash_input);
    fieldset.appendChild(after_hash_label);

    const button_row = document.createElement('div');
    button_row.className = 'button-row';
    const fetch_btn = document.createElement('button');
    fetch_btn.id = 'social_fetch_events';
    fetch_btn.textContent = 'Fetch events';
    button_row.appendChild(fetch_btn);
    fieldset.appendChild(button_row);

    const output_label = document.createElement('p');
    output_label.textContent = 'Events';
    fieldset.appendChild(output_label);

    const list = document.createElement('ul');
    list.id = 'social_list';
    fieldset.appendChild(list);

    const pre = document.createElement('pre');
    pre.id = 'social_log';
    fieldset.appendChild(pre);

    const event_fieldset = event_log.closest('fieldset');
    if (event_fieldset && event_fieldset.parentNode) {
      event_fieldset.parentNode.insertBefore(fieldset, event_fieldset);
    } else {
      document.body.appendChild(fieldset);
    }

    social_user_id_input = user_id_input;
    social_limit_input = limit_input;
    social_after_hash_input = after_hash_input;
    social_fetch_btn = fetch_btn;
    social_log_pre = pre;
    social_list = list;
  };

  const hydrate_inputs = async () => {
    try {
      const saved_url = await read_setting('gateway_url');
      if (saved_url) {
        gateway_url_input.value = saved_url;
      }
      const saved_resume_token = await read_setting('resume_token');
      if (saved_resume_token) {
        resume_token_input.value = saved_resume_token;
      }
      if (social_user_id_input) {
        const saved_user_id = await read_setting('social_user_id');
        if (saved_user_id) {
          social_user_id_input.value = saved_user_id;
        }
      }
      if (social_limit_input) {
        const saved_limit = await read_setting('social_limit');
        if (typeof saved_limit === 'number' && !Number.isNaN(saved_limit)) {
          social_limit_input.value = String(saved_limit);
        }
      }
      if (social_after_hash_input) {
        const saved_after_hash = await read_setting('social_after_hash');
        if (saved_after_hash) {
          social_after_hash_input.value = saved_after_hash;
        }
      }
      if (dm_bridge_autofill_enabled_input) {
        const saved_autofill_enabled = await read_setting(dm_autofill_setting_keys.enabled);
        dm_bridge_autofill_enabled_input.checked = saved_autofill_enabled === true;
      }
      if (dm_bridge_autofill_welcome_input) {
        const saved_autofill_welcome = await read_setting(dm_autofill_setting_keys.welcome);
        dm_bridge_autofill_welcome_input.checked = saved_autofill_welcome !== false;
      }
      if (dm_bridge_autofill_commit_input) {
        const saved_autofill_commit = await read_setting(dm_autofill_setting_keys.commit);
        dm_bridge_autofill_commit_input.checked = saved_autofill_commit !== false;
      }
      if (dm_bridge_autofill_app_input) {
        const saved_autofill_app = await read_setting(dm_autofill_setting_keys.app);
        dm_bridge_autofill_app_input.checked = saved_autofill_app !== false;
      }
      set_dm_autofill_controls_enabled(
        dm_bridge_autofill_enabled_input ? dm_bridge_autofill_enabled_input.checked : false
      );
    } catch (err) {
      append_log(`failed to hydrate inputs: ${err.message}`);
    }
  };

  connect_start_btn.addEventListener('click', () => {
    const url = gateway_url_input.value.trim();
    if (!url) {
      append_log('gateway url required');
      return;
    }
    write_setting('gateway_url', url).catch((err) => append_log(`failed to persist gateway_url: ${err.message}`));
    client.connect(url);
    const auth_token = bootstrap_token_input.value.trim();
    const device_id = device_id_input.value.trim();
    const device_credential = device_credential_input.value.trim();
    client.start_session(auth_token, device_id || undefined, device_credential || undefined);
  });

  connect_resume_btn.addEventListener('click', () => {
    const url = gateway_url_input.value.trim();
    if (!url) {
      append_log('gateway url required');
      return;
    }
    write_setting('gateway_url', url).catch((err) => append_log(`failed to persist gateway_url: ${err.message}`));
    client.connect(url);
    const resume_token = resume_token_input.value.trim();
    client.resume_session(resume_token);
  });

  const prefill_from_seq = async () => {
    const conv_id = conv_id_input.value.trim();
    if (!conv_id) {
      from_seq_input.value = '';
      return;
    }
    const stored_next_seq = (await read_cursor(conv_id)) ?? 1;
    from_seq_input.value = String(stored_next_seq);
  };

  const normalize_conv_id = (value) => {
    if (typeof value !== 'string') {
      return '';
    }
    return value.trim();
  };

  const maybe_dispatch_conv_selected = (value) => {
    const conv_id = normalize_conv_id(value);
    if (conv_id === last_selected_conv_id) {
      return;
    }
    last_selected_conv_id = conv_id;
    window.dispatchEvent(
      new CustomEvent('conv.selected', {
        detail: {
          conv_id,
        },
      })
    );
  };

  subscribe_btn.addEventListener('click', async () => {
    const conv_id = conv_id_input.value.trim();
    maybe_dispatch_conv_selected(conv_id);
    if (from_seq_input.value === '') {
      const stored_next_seq = (await read_cursor(conv_id)) ?? 1;
      last_from_seq_by_conv_id[conv_id] = stored_next_seq;
      client.subscribe(conv_id, stored_next_seq);
      return;
    }
    const from_seq_value = Number(from_seq_input.value);
    last_from_seq_by_conv_id[conv_id] = from_seq_value;
    client.subscribe(conv_id, from_seq_value);
  });

  ack_btn.addEventListener('click', () => {
    const seq_value = Number(seq_input.value);
    client.ack(conv_id_input.value.trim(), seq_value);
  });

  send_btn.addEventListener('click', async () => {
    const conv_id = conv_id_input.value.trim();
    const ciphertext = ciphertext_input.value.trim();
    await send_ciphertext_with_deterministic_id(conv_id, ciphertext);
  });

  clear_log_btn.addEventListener('click', () => {
    debug_log.value = '';
    event_log.innerHTML = '';
  });

  conv_id_input.addEventListener('change', () => {
    prefill_from_seq().catch((err) => append_log(`failed to prefill from_seq: ${err.message}`));
    maybe_dispatch_conv_selected(conv_id_input.value);
  });

  conv_id_input.addEventListener('input', () => {
    maybe_dispatch_conv_selected(conv_id_input.value);
  });

  conv_id_input.addEventListener('blur', () => {
    prefill_from_seq().catch((err) => append_log(`failed to prefill from_seq: ${err.message}`));
    maybe_dispatch_conv_selected(conv_id_input.value);
  });

  const initial_conv_id = normalize_conv_id(conv_id_input ? conv_id_input.value : '');
  if (initial_conv_id) {
    maybe_dispatch_conv_selected(initial_conv_id);
  }

  window.addEventListener('dm.outbox.updated', (event) => {
    const detail = event && event.detail ? event.detail : null;
    if (!detail || typeof detail !== 'object') {
      return;
    }
    dm_outbox_welcome_env_b64 =
      typeof detail.welcome_env_b64 === 'string' ? detail.welcome_env_b64 : '';
    dm_outbox_commit_env_b64 =
      typeof detail.commit_env_b64 === 'string' ? detail.commit_env_b64 : '';
    dm_outbox_app_env_b64 =
      typeof detail.app_env_b64 === 'string' ? detail.app_env_b64 : '';
  });

  window.addEventListener('gateway.send_env', (event) => {
    handle_gateway_send_env(event);
  });

  build_dm_bridge_panel();
  build_transcript_panel();
  if (dm_bridge_copy_btn) {
    dm_bridge_copy_btn.addEventListener('click', () => {
      if (!last_conv_env_b64) {
        append_log('no conv.event env to copy');
        return;
      }
      const did_set = set_dm_incoming_env(last_conv_env_b64);
      if (!did_set) {
        append_log('dm_ui incoming_env_b64 input not found');
        return;
      }
      append_log('copied last env to dm_ui');
    });
  }
  if (dm_bridge_parse_btn) {
    dm_bridge_parse_btn.addEventListener('click', () => {
      const block_text = dm_bridge_cli_block_input ? dm_bridge_cli_block_input.value : '';
      if (!block_text || !block_text.trim()) {
        set_dm_bridge_status('status: error (paste CLI block)');
        return;
      }
      const { parsed, found_keys } = parse_cli_block(block_text);
      if (!found_keys.length) {
        set_dm_bridge_status('status: error (no CLI fields found)');
        return;
      }
      if (parsed.welcome_env_b64) {
        set_dm_incoming_env(parsed.welcome_env_b64);
      }
      if (parsed.expected_plaintext !== '') {
        set_dm_expected_plaintext(parsed.expected_plaintext);
      } else if (dm_bridge_expected_plaintext_pre) {
        dm_bridge_expected_plaintext_pre.textContent = '';
      }
      if (parsed.app_env_b64) {
        parsed_app_env_b64 = parsed.app_env_b64;
        ciphertext_input.value = parsed.app_env_b64;
        msg_id_input.value = '';
      }
      const missing_keys = cli_block_keys.filter((key) => !parsed[key]);
      const missing_summary = missing_keys.length ? `; missing: ${missing_keys.join(', ')}` : '';
      set_dm_bridge_status(`status: parsed (${found_keys.join(', ')})${missing_summary}`);
    });
  }
  if (dm_bridge_send_btn) {
    dm_bridge_send_btn.addEventListener('click', async () => {
      const conv_id = conv_id_input.value.trim();
      const app_env_b64 = parsed_app_env_b64 || ciphertext_input.value.trim();
      if (!app_env_b64) {
        append_log('missing app_env_b64 for send');
        return;
      }
      await send_ciphertext_with_deterministic_id(conv_id, app_env_b64);
    });
  }
  if (dm_bridge_use_last_app_btn) {
    dm_bridge_use_last_app_btn.addEventListener('click', () => {
      const output = read_dm_bridge_envs();
      if (output.error) {
        set_dm_bridge_status(`status: error (${output.error})`);
        return;
      }
      const app_env_b64 = output.envs.app_env_b64;
      const validation = validate_env_b64_for_send(app_env_b64, 'app_env_b64');
      if (!validation.ok) {
        set_dm_bridge_status(`status: error (${validation.reason})`);
        return;
      }
      parsed_app_env_b64 = app_env_b64;
      ciphertext_input.value = app_env_b64;
      msg_id_input.value = '';
      const source_label = output.source === 'outbox' ? 'outbox' : 'dm_output';
      set_dm_bridge_status(`status: loaded app_env from ${source_label}`);
    });
  }
  if (dm_bridge_send_last_app_btn) {
    dm_bridge_send_last_app_btn.addEventListener('click', async () => {
      const conv_id = conv_id_input.value.trim();
      if (!conv_id) {
        set_dm_bridge_status('status: error (conv_id required)');
        return;
      }
      const output = read_dm_bridge_envs();
      if (output.error) {
        set_dm_bridge_status(`status: error (${output.error})`);
        return;
      }
      const app_env_b64 = output.envs.app_env_b64;
      const validation = validate_env_b64_for_send(app_env_b64, 'app_env_b64');
      if (!validation.ok) {
        set_dm_bridge_status(`status: error (${validation.reason})`);
        return;
      }
      await send_ciphertext_with_deterministic_id(conv_id, app_env_b64);
      const source_label = output.source === 'outbox' ? 'outbox' : 'dm_output';
      set_dm_bridge_status(`status: sent app_env from ${source_label}`);
    });
  }
  if (dm_bridge_send_init_btn) {
    dm_bridge_send_init_btn.addEventListener('click', async () => {
      const conv_id = conv_id_input.value.trim();
      if (!conv_id) {
        set_dm_bridge_status('status: error (conv_id required)');
        return;
      }
      const output = read_dm_bridge_envs();
      if (output.error) {
        set_dm_bridge_status(`status: error (${output.error})`);
        return;
      }
      const welcome_env_b64 = output.envs.welcome_env_b64;
      const commit_env_b64 = output.envs.commit_env_b64;
      const welcome_validation = validate_env_b64_for_send(welcome_env_b64, 'welcome_env_b64');
      if (!welcome_validation.ok) {
        set_dm_bridge_status(`status: error (${welcome_validation.reason})`);
        return;
      }
      const commit_validation = validate_env_b64_for_send(commit_env_b64, 'commit_env_b64');
      if (!commit_validation.ok) {
        set_dm_bridge_status(`status: error (${commit_validation.reason})`);
        return;
      }
      await send_ciphertext_with_deterministic_id(conv_id, welcome_env_b64);
      await send_ciphertext_with_deterministic_id(conv_id, commit_env_b64);
      const source_label = output.source === 'outbox' ? 'outbox' : 'dm_output';
      set_dm_bridge_status(`status: sent dm_ui init envs from ${source_label}`);
    });
  }
  if (dm_bridge_autofill_enabled_input) {
    dm_bridge_autofill_enabled_input.addEventListener('change', () => {
      handle_dm_autofill_toggle();
    });
  }
  if (dm_bridge_autofill_welcome_input) {
    dm_bridge_autofill_welcome_input.addEventListener('change', () => {
      handle_dm_autofill_kind_toggle();
    });
  }
  if (dm_bridge_autofill_commit_input) {
    dm_bridge_autofill_commit_input.addEventListener('change', () => {
      handle_dm_autofill_kind_toggle();
    });
  }
  if (dm_bridge_autofill_app_input) {
    dm_bridge_autofill_app_input.addEventListener('change', () => {
      handle_dm_autofill_kind_toggle();
    });
  }

  if (transcript_export_btn) {
    transcript_export_btn.addEventListener('click', async () => {
      const conv_id = conv_id_input.value.trim();
      if (!conv_id) {
        set_transcript_status('status: error (conv_id required)');
        return;
      }
      try {
        const entries = await read_transcripts(conv_id);
        if (!entries.length) {
          set_transcript_status('status: no transcripts found');
          return;
        }
        const from_seq_value = last_from_seq_by_conv_id[conv_id];
        const next_seq_value = await read_cursor(conv_id);
        const payload = {
          schema_version: 1,
          conv_id,
          from_seq: typeof from_seq_value === 'number' && !Number.isNaN(from_seq_value) ? from_seq_value : null,
          next_seq: typeof next_seq_value === 'number' && !Number.isNaN(next_seq_value) ? next_seq_value : null,
          events: entries.map((entry) => ({
            seq: entry.seq,
            msg_id: typeof entry.msg_id === 'string' && entry.msg_id ? entry.msg_id : null,
            env: entry.env,
          })),
        };
        const digest_sha256_b64 = await compute_transcript_digest(payload);
        const export_payload = {
          ...payload,
          digest_sha256_b64,
        };
        const blob = new Blob([JSON.stringify(export_payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `transcript-${conv_id}-${Date.now()}.json`;
        link.click();
        URL.revokeObjectURL(url);
        set_transcript_status(`status: exported ${entries.length} events; digest: ${digest_sha256_b64}`);
      } catch (err) {
        set_transcript_status(`status: error (${err.message})`);
      }
    });
  }

  if (transcript_import_input) {
    transcript_import_input.addEventListener('change', () => {
      const file = transcript_import_input.files ? transcript_import_input.files[0] : null;
      if (!file) {
        return;
      }
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const payload = JSON.parse(reader.result);
          await import_transcript_payload(payload);
        } catch (err) {
          set_transcript_status(`status: error (${err.message || 'invalid json'})`);
          set_transcript_summary(null);
        }
      };
      reader.readAsText(file);
      transcript_import_input.value = '';
    });
  }

  if (transcript_paste_import_btn) {
    transcript_paste_import_btn.addEventListener('click', async () => {
      const paste_value = transcript_paste_input ? transcript_paste_input.value.trim() : '';
      if (!paste_value) {
        set_transcript_status('status: error (paste transcript json)');
        set_transcript_summary(null);
        return;
      }
      try {
        const payload = JSON.parse(paste_value);
        await import_transcript_payload(payload);
      } catch (err) {
        set_transcript_status(`status: error (${err.message || 'invalid json'})`);
        set_transcript_summary(null);
      }
    });
  }

  const load_transcript_env_to_dm = (kind_label) => {
    if (!transcript_last_import || !transcript_last_import.selected_envs) {
      set_transcript_status(`status: error (no imported transcript to load ${kind_label})`);
      return;
    }
    const selected_envs = transcript_last_import.selected_envs;
    let env_b64 = null;
    if (kind_label === 'welcome') {
      env_b64 = selected_envs.welcome_env_b64;
    } else if (kind_label === 'commit') {
      env_b64 = selected_envs.commit_env_b64;
    } else if (kind_label === 'app') {
      env_b64 = selected_envs.app_env_b64;
    }
    if (!env_b64) {
      set_transcript_status(`status: error (no ${kind_label} env found)`);
      return;
    }
    const did_set = set_dm_incoming_env(env_b64);
    if (!did_set) {
      set_transcript_status('status: error (dm_ui incoming_env_b64 input not found)');
      return;
    }
    if (transcript_last_import.expected_plaintext) {
      set_dm_expected_plaintext(transcript_last_import.expected_plaintext);
    }
    set_transcript_status(`status: loaded ${kind_label} into dm_ui`);
  };

  if (transcript_load_welcome_btn) {
    transcript_load_welcome_btn.addEventListener('click', () => {
      load_transcript_env_to_dm('welcome');
    });
  }
  if (transcript_load_commit_btn) {
    transcript_load_commit_btn.addEventListener('click', () => {
      load_transcript_env_to_dm('commit');
    });
  }
  if (transcript_load_app_btn) {
    transcript_load_app_btn.addEventListener('click', () => {
      load_transcript_env_to_dm('app');
    });
  }

  if (transcript_replay_btn) {
    transcript_replay_btn.addEventListener('click', () => {
      const conv_id = conv_id_input.value.trim();
      const imported_events =
        transcript_last_import && Array.isArray(transcript_last_import.events) ? transcript_last_import.events : [];
      if (imported_events.length && (!conv_id || transcript_last_import.conv_id === conv_id)) {
        const latest_env = latest_transcript_env(imported_events);
        if (latest_env) {
          last_conv_env_b64 = latest_env;
          update_dm_bridge_last_env();
          set_transcript_status('status: replayed imported transcript');
          return;
        }
      }
      if (!conv_id) {
        set_transcript_status('status: error (conv_id required)');
        return;
      }
      read_transcripts(conv_id)
        .then((entries) => {
          const latest_env = latest_transcript_env(entries);
          if (!latest_env) {
            set_transcript_status('status: no transcript env found');
            return;
          }
          last_conv_env_b64 = latest_env;
          update_dm_bridge_last_env();
          set_transcript_status('status: replayed recorded transcript');
        })
        .catch((err) => set_transcript_status(`status: error (${err.message})`));
    });
  }

  build_social_panel();
  if (social_fetch_btn) {
    social_fetch_btn.addEventListener('click', () => {
      fetch_social_events().catch((err) => render_social_error(err.message || 'fetch failed'));
    });
  }
  hydrate_inputs();
})();
