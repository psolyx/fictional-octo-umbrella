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

  const connect_start_btn = document.getElementById('connect_start');
  const connect_resume_btn = document.getElementById('connect_resume');
  const subscribe_btn = document.getElementById('subscribe_btn');
  const ack_btn = document.getElementById('ack_btn');
  const send_btn = document.getElementById('send_btn');
  const clear_log_btn = document.getElementById('clear_log');

  const db_name = 'gateway_web_demo';
  const store_name = 'settings';
  const next_id = () => `msg-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
  const dm_kind_labels = {
    1: 'welcome',
    2: 'commit',
    3: 'app_ciphertext',
  };

  const bytes_to_hex = (bytes) =>
    Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');

  const bytes_to_base64 = (bytes) => {
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 1) {
      binary += String.fromCharCode(bytes[offset]);
    }
    return btoa(binary);
  };

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

  const append_log = (line) => {
    const now = new Date().toISOString();
    debug_log.value += `[${now}] ${line}\n`;
    debug_log.scrollTop = debug_log.scrollHeight;
  };

  const render_event = (body) => {
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
      const env_bytes = base64_to_bytes(body.env);
      if (env_bytes && env_bytes.length >= 1) {
        const kind = env_bytes[0];
        const payload_bytes = env_bytes.slice(1);
        const payload_b64 = bytes_to_base64(payload_bytes);
        const kind_label = dm_kind_labels[kind] || `unknown(0x${kind.toString(16).padStart(2, '0')})`;
        const payload_prefix = payload_b64.slice(0, 32);
        const payload_suffix = payload_b64.length > payload_prefix.length ? '...' : '';
        env_display =
          `dm_env(kind=${kind_label} payload_len=${payload_bytes.length}` +
          ` payload_b64_prefix=${payload_prefix}${payload_suffix})`;
      }
    }
    entry.textContent = `${parts.join(' ')} env=${env_display}`;
    event_log.prepend(entry);
  };

  const open_db = () =>
    new Promise((resolve, reject) => {
      const request = indexedDB.open(db_name, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(store_name)) {
          db.createObjectStore(store_name, { keyPath: 'key' });
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
        render_event(body);
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

  subscribe_btn.addEventListener('click', async () => {
    const conv_id = conv_id_input.value.trim();
    if (from_seq_input.value === '') {
      const stored_next_seq = (await read_cursor(conv_id)) ?? 1;
      client.subscribe(conv_id, stored_next_seq);
      return;
    }
    const from_seq_value = Number(from_seq_input.value);
    client.subscribe(conv_id, from_seq_value);
  });

  ack_btn.addEventListener('click', () => {
    const seq_value = Number(seq_input.value);
    client.ack(conv_id_input.value.trim(), seq_value);
  });

  send_btn.addEventListener('click', async () => {
    const conv_id = conv_id_input.value.trim();
    const ciphertext = ciphertext_input.value.trim();
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
  });

  clear_log_btn.addEventListener('click', () => {
    debug_log.value = '';
    event_log.innerHTML = '';
  });

  conv_id_input.addEventListener('change', () => {
    prefill_from_seq().catch((err) => append_log(`failed to prefill from_seq: ${err.message}`));
  });

  conv_id_input.addEventListener('blur', () => {
    prefill_from_seq().catch((err) => append_log(`failed to prefill from_seq: ${err.message}`));
  });

  hydrate_inputs();
})();
