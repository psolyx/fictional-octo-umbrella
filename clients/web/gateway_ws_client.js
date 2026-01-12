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
  let dm_bridge_status = null;
  let dm_bridge_expected_plaintext_pre = null;
  let dm_import_env_input = null;
  let dm_expected_plaintext_input = null;

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
  const cli_block_keys = ['welcome_env_b64', 'commit_env_b64', 'app_env_b64', 'expected_plaintext'];
  let last_conv_env_b64 = '';
  let parsed_app_env_b64 = '';

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
        }
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

    const status = document.createElement('p');
    status.textContent = 'status: idle';
    fieldset.appendChild(status);

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
    dm_bridge_status = status;
    dm_bridge_expected_plaintext_pre = expected_plaintext_pre;
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
    await send_ciphertext_with_deterministic_id(conv_id, ciphertext);
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

  build_dm_bridge_panel();
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
        dm_bridge_status.textContent = 'status: error (paste CLI block)';
        return;
      }
      const { parsed, found_keys } = parse_cli_block(block_text);
      if (!found_keys.length) {
        dm_bridge_status.textContent = 'status: error (no CLI fields found)';
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
      dm_bridge_status.textContent = `status: parsed (${found_keys.join(', ')})${missing_summary}`;
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

  build_social_panel();
  if (social_fetch_btn) {
    social_fetch_btn.addEventListener('click', () => {
      fetch_social_events().catch((err) => render_social_error(err.message || 'fetch failed'));
    });
  }
  hydrate_inputs();
})();
