/* Minimal gateway v1 WebSocket client (ciphertext only). */
(() => {
  const connection_status = document.getElementById('connection_status');
  const debug_log = document.getElementById('debug_log');
  const event_log = document.getElementById('event_log');
  const replay_window_banner = document.getElementById('replay_window_banner');
  const replay_window_text = document.getElementById('replay_window_text');
  const replay_window_resubscribe_btn = document.getElementById('replay_window_resubscribe_btn');
  const live_status = document.getElementById('live_status');

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
  const conv_id_error = document.getElementById('conv_id_error');
  const compose_error = document.getElementById('compose_error');
  let social_user_id_input = null;
  let social_limit_input = null;
  let social_after_hash_input = null;
  let social_fetch_btn = null;
  let social_log_pre = null;
  let social_list = null;
  let rooms_conv_id_input = null;
  let rooms_members_input = null;
  let rooms_create_btn = null;
  let rooms_invite_btn = null;
  let rooms_remove_btn = null;
  let rooms_promote_btn = null;
  let rooms_demote_btn = null;
  let rooms_generate_room_id_btn = null;
  let rooms_status_line = null;
  let rooms_conv_id_error = null;
  let rooms_members_error = null;
  let rooms_refresh_roster_btn = null;
  let rooms_copy_selected_btn = null;
  let rooms_roster_list = null;
  let rooms_session_token = '';
  let rooms_http_base_url = '';
  let conversations_refresh_btn = null;
  let conversations_list = null;
  let conversations_status = null;
  let conversations_session_token = '';
  let conversations_http_base_url = '';
  let conversations_user_id = '';
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
  conversations_refresh_btn = document.getElementById('conversations_refresh_btn');
  conversations_list = document.getElementById('conversations_list');
  conversations_status = document.getElementById('conversations_status');
  if (conversations_status) {
    conversations_status.textContent = 'status: idle';
  }

  const db_name = 'gateway_web_demo';
  const db_version = 2;
  const store_name = 'settings';
  const transcripts_store_name = 'transcripts';
  const transcript_max_records = 200;
  const conv_meta_key = 'conv_meta_v1';
  const conv_outbox_key = 'conv_outbox_v1';
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
  const conv_meta_by_id = {};
  const conv_outbox_by_id = {};
  const pending_entry_by_msg_id = {};
  let last_selected_conv_id = null;
  let last_selected_conv_index = 0;
  let last_selected_message_entry = null;
  let replay_window_conv_id = null;
  let replay_window_earliest_seq = null;

  const announce_status = (message) => {
    if (!live_status) {
      return;
    }
    live_status.textContent = '';
    window.setTimeout(() => {
      live_status.textContent = message;
    }, 0);
  };

  const set_inline_error = (field, error_node, message) => {
    if (!field || !error_node) {
      return;
    }
    if (!message) {
      field.removeAttribute('aria-invalid');
      error_node.hidden = true;
      error_node.textContent = '';
      return;
    }
    field.setAttribute('aria-invalid', 'true');
    error_node.hidden = false;
    error_node.textContent = message;
  };

  const parse_replay_window_details = (body) => {
    if (!body || typeof body !== 'object') {
      return null;
    }
    let earliest_seq = Number.isInteger(body.earliest_seq) ? body.earliest_seq : null;
    let latest_seq = Number.isInteger(body.latest_seq) ? body.latest_seq : null;
    let requested_from_seq = Number.isInteger(body.requested_from_seq) ? body.requested_from_seq : null;
    if (earliest_seq !== null && latest_seq !== null) {
      return { earliest_seq, latest_seq, requested_from_seq };
    }
    const message_text = typeof body.message === 'string' ? body.message : '';
    const pairs = message_text.match(/(requested_from_seq|earliest_seq|latest_seq)=\d+/g) || [];
    for (const pair of pairs) {
      const split = pair.split('=');
      if (split.length !== 2) {
        continue;
      }
      const key = split[0];
      const value = Number(split[1]);
      if (!Number.isInteger(value)) {
        continue;
      }
      if (key === 'earliest_seq') earliest_seq = value;
      if (key === 'latest_seq') latest_seq = value;
      if (key === 'requested_from_seq') requested_from_seq = value;
    }
    if (earliest_seq === null || latest_seq === null) {
      return null;
    }
    return { earliest_seq, latest_seq, requested_from_seq };
  };

  const show_replay_window_banner = (conv_id, details) => {
    if (!replay_window_banner || !replay_window_text || !details) {
      return;
    }
    replay_window_conv_id = conv_id;
    replay_window_earliest_seq = details.earliest_seq;
    const requested_text = Number.isInteger(details.requested_from_seq)
      ? ` Requested from_seq was ${details.requested_from_seq}.`
      : '';
    replay_window_text.textContent = `History pruned. Earliest available seq: ${details.earliest_seq}.${requested_text}`;
    replay_window_banner.hidden = false;
    announce_status(replay_window_text.textContent);
  };

  const hide_replay_window_banner = () => {
    if (!replay_window_banner) {
      return;
    }
    replay_window_banner.hidden = true;
    replay_window_conv_id = null;
    replay_window_earliest_seq = null;
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

  const derive_http_base_url = (ws_url) => {
    if (typeof ws_url !== 'string' || !ws_url) {
      return '';
    }
    try {
      const parsed_url = new URL(ws_url);
      if (parsed_url.protocol === 'ws:') {
        return `http://${parsed_url.host}`;
      }
      if (parsed_url.protocol === 'wss:') {
        return `https://${parsed_url.host}`;
      }
    } catch (err) {
      return '';
    }
    return '';
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

  const sensitive_log_keys = new Set([
    'auth_token',
    'bootstrap_token',
    'device_credential',
    'session_token',
    'resume_token',
  ]);

  const redact_key = (key) => {
    if (typeof key !== 'string') {
      return false;
    }
    return sensitive_log_keys.has(key.toLowerCase());
  };

  const redact_object = (value) => {
    if (Array.isArray(value)) {
      return value.map((entry) => redact_object(entry));
    }
    if (!value || typeof value !== 'object') {
      return value;
    }
    const output = {};
    Object.keys(value).forEach((key) => {
      if (redact_key(key)) {
        output[key] = '[REDACTED]';
      } else {
        output[key] = redact_object(value[key]);
      }
    });
    return output;
  };

  const redact_url = (url) => {
    if (typeof url !== 'string' || !url) {
      return '';
    }
    try {
      const parsed = new URL(url);
      ['auth_token', 'resume_token', 'token', 'credential'].forEach((key) => {
        if (parsed.searchParams.has(key)) {
          parsed.searchParams.set(key, '[REDACTED]');
        }
      });
      return parsed.toString();
    } catch (err) {
      return url
        .replace(/([?&](?:auth_token|resume_token|token|credential)=)([^&#\s]+)/gi, '$1[REDACTED]')
        .replace(/(Bearer\s+)([^\s]+)/gi, '$1[REDACTED]');
    }
  };

  const redact_line = (text) => {
    const normalized = typeof text === 'string' ? text : String(text);
    return normalized
      .replace(/(Bearer\s+)([^\s]+)/gi, '$1[REDACTED]')
      .replace(/(["']?(?:auth_token|bootstrap_token|device_credential|session_token|resume_token|token|credential)["']?\s*[:=]\s*["']?)([^"'\s,}]+)/gi, '$1[REDACTED]')
      .replace(/([?&](?:auth_token|resume_token|token|credential)=)([^&#\s]+)/gi, '$1[REDACTED]');
  };

  const append_log = (line) => {
    const now = new Date().toISOString();
    debug_log.value += `[${now}] ${redact_line(line)}\n`;
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

  const set_conversations_status = (value) => {
    if (conversations_status) {
      conversations_status.textContent = value;
    }
    announce_status(`conversations ${value}`);
  };

  const short_id = (value, prefix = 8, suffix = 4) => {
    if (typeof value !== 'string') {
      return '';
    }
    const trimmed = value.trim();
    if (trimmed.length <= prefix + suffix + 1) {
      return trimmed;
    }
    return `${trimmed.slice(0, prefix)}…${trimmed.slice(-suffix)}`;
  };

  const to_optional_int = (value) => {
    if (!Number.isInteger(value)) {
      return null;
    }
    return value;
  };

  const render_conversations = async (items) => {
    if (!conversations_list) {
      return;
    }
    conversations_list.innerHTML = '';
    if (!Array.isArray(items) || items.length === 0) {
      const empty_item = document.createElement('li');
      empty_item.textContent = 'no conversations';
      conversations_list.appendChild(empty_item);
      return;
    }
    const computed_items = [];
    for (const item of items) {
      if (!item || typeof item !== 'object' || typeof item.conv_id !== 'string') {
        continue;
      }
      const cursor_next_seq = (await read_cursor(item.conv_id)) ?? 1;
      const acked_seq = cursor_next_seq - 1;
      const latest_seq = to_optional_int(item.latest_seq);
      const earliest_seq = to_optional_int(item.earliest_seq);
      const latest_ts_ms = to_optional_int(item.latest_ts_ms);
      const unread_count = latest_seq === null ? 0 : Math.max(0, latest_seq - acked_seq);
      const pruned = earliest_seq !== null && cursor_next_seq < earliest_seq;
      computed_items.push({ ...item, unread_count, pruned, cursor_next_seq, earliest_seq, latest_ts_ms });
    }

    computed_items.sort((left, right) => {
      if (left.latest_ts_ms === null && right.latest_ts_ms !== null) {
        return 1;
      }
      if (left.latest_ts_ms !== null && right.latest_ts_ms === null) {
        return -1;
      }
      if (left.latest_ts_ms !== right.latest_ts_ms) {
        return (right.latest_ts_ms || 0) - (left.latest_ts_ms || 0);
      }
      if (left.unread_count !== right.unread_count) {
        return right.unread_count - left.unread_count;
      }
      return String(left.conv_id).localeCompare(String(right.conv_id));
    });

    const activate_conversation = (item, members) => {
      conv_id_input.value = item.conv_id;
      const desired_from_seq = Math.max(item.cursor_next_seq, item.earliest_seq || 1);
      from_seq_input.value = String(desired_from_seq);
      maybe_dispatch_conv_selected(item.conv_id);
      window.dispatchEvent(
        new CustomEvent('conv.selected', {
          detail: {
            conv_id: item.conv_id,
            members,
          },
        })
      );
      subscribe_btn.click();
    };

    computed_items.forEach((item, index) => {
      const list_item = document.createElement('li');
      const conversation_btn = document.createElement('button');
      conversation_btn.type = 'button';
      conversation_btn.setAttribute('role', 'option');
      conversation_btn.dataset.roving_tabindex = 'true';
      const member_count = Number.isInteger(item.member_count) ? item.member_count : 0;
      const role = typeof item.role === 'string' ? item.role : 'member';
      const members = Array.isArray(item.members) ? item.members.filter((member) => typeof member === 'string') : [];
      let peer_label = '';
      let default_label = `room ${short_id(item.conv_id, 10, 4)}`;
      if (member_count === 2 && members.length > 0) {
        const other_member = members.find((member) => member !== conversations_user_id) || members[0];
        if (other_member) {
          peer_label = ` peer ${short_id(other_member, 10, 4)}`;
          default_label = `dm ${short_id(other_member, 10, 4)}`;
        }
      }
      const meta = ensure_conv_meta(item.conv_id);
      if (meta && !meta.label) {
        meta.label = default_label;
      }
      const status_markers = [];
      if (item.unread_count > 0) {
        status_markers.push(`unread=${item.unread_count}`);
      }
      if (item.pruned) {
        status_markers.push('pruned');
      }
      const status_suffix = status_markers.length ? ` ${status_markers.join(' ')}` : '';
      conversation_btn.textContent = `${(meta && meta.label) || default_label} role=${role} members=${member_count}${peer_label}${status_suffix}`;
      const preview_line = document.createElement('div');
      preview_line.dataset.test = 'conv-preview';
      const preview_value = meta && meta.last_preview ? meta.last_preview : '(no messages yet)';
      const ts_value = to_timestamp_label(meta && Number.isInteger(meta.last_ts_ms) ? meta.last_ts_ms : item.latest_ts_ms);
      preview_line.textContent = `${preview_value}${ts_value ? ` • ${ts_value}` : ''}`;
      list_item.dataset.conv_id = item.conv_id;
      const is_selected = item.conv_id === last_selected_conv_id || (!last_selected_conv_id && index === 0);
      conversation_btn.setAttribute('aria-selected', is_selected ? 'true' : 'false');
      conversation_btn.setAttribute('aria-current', is_selected ? 'true' : 'false');
      conversation_btn.setAttribute('tabindex', is_selected ? '0' : '-1');
      if (is_selected) {
        last_selected_conv_id = item.conv_id;
        last_selected_conv_index = index;
      }
      conversation_btn.addEventListener('click', () => {
        activate_conversation(item, members);
      });
      conversation_btn.addEventListener('keydown', (event) => {
        if (!conversations_list) {
          return;
        }
        const options = Array.from(conversations_list.querySelectorAll('button[data-roving-tabindex="true"]'));
        if (!options.length) {
          return;
        }
        const current_index = options.indexOf(conversation_btn);
        const move_to = (next_index) => {
          const safe_index = Math.max(0, Math.min(next_index, options.length - 1));
          options.forEach((option, option_index) => {
            const selected = option_index === safe_index;
            option.setAttribute('tabindex', selected ? '0' : '-1');
            option.setAttribute('aria-selected', selected ? 'true' : 'false');
            option.setAttribute('aria-current', selected ? 'true' : 'false');
          });
          const next_btn = options[safe_index];
          next_btn.focus();
          last_selected_conv_index = safe_index;
          const parent = next_btn.closest('li');
          last_selected_conv_id = parent ? parent.dataset.conv_id || null : null;
        };
        if (event.key === 'ArrowDown') {
          event.preventDefault();
          move_to(current_index + 1);
          return;
        }
        if (event.key === 'ArrowUp') {
          event.preventDefault();
          move_to(current_index - 1);
          return;
        }
        if (event.key === 'Enter') {
          event.preventDefault();
          activate_conversation(item, members);
        }
      });
      list_item.appendChild(conversation_btn);
      list_item.appendChild(preview_line);
      conversations_list.appendChild(list_item);
    });
    persist_conv_meta().catch((err) => append_log(`failed to persist conv metadata: ${err.message}`));
  };

  const refresh_conversations = async () => {
    if (!conversations_http_base_url || !conversations_session_token) {
      set_conversations_status('status: session required');
      return;
    }
    set_conversations_status('status: loading');
    try {
      const response = await fetch(`${conversations_http_base_url}/v1/conversations`, {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${conversations_session_token}`,
        },
      });
      if (!response.ok) {
        throw new Error(`http ${response.status}`);
      }
      const payload = await response.json();
      const items = payload && Array.isArray(payload.items) ? payload.items : [];
      await render_conversations(items);
      set_conversations_status(`status: loaded ${items.length}`);
    } catch (err) {
      set_conversations_status(`status: error (${err.message || 'fetch failed'})`);
    }
  };

  const parse_members_input = (value) => {
    if (typeof value !== 'string') {
      return [];
    }
    return value
      .split(',')
      .map((entry) => entry.trim())
      .filter((entry) => entry);
  };

  const generate_room_id = () => {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return `conv_${window.crypto.randomUUID().replace(/-/g, '')}`;
    }
    if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
      const bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      const hex = Array.from(bytes)
        .map((value) => value.toString(16).padStart(2, '0'))
        .join('');
      return `conv_${hex}`;
    }
    return `conv_${Date.now().toString(16)}${Math.floor(Math.random() * 1e9).toString(16)}`;
  };

  const set_rooms_status = (message) => {
    if (rooms_status_line) {
      rooms_status_line.textContent = message;
    }
    announce_status(`rooms ${message}`);
  };

  const set_rooms_response_status = (response, payload_text) => {
    const forbidden_text = response && response.status === 403 ? ' forbidden' : '';
    const status_label = response ? `${response.status} ${response.statusText}${forbidden_text}`.trim() : 'unknown';
    const compact_payload = payload_text ? payload_text : '{}';
    set_rooms_status(`status: ${status_label} ${compact_payload}`);
  };

  const selected_roster_member_ids = () => {
    if (!rooms_roster_list) {
      return [];
    }
    const selected = [];
    const checkboxes = rooms_roster_list.querySelectorAll('input[type="checkbox"][data-user_id]');
    checkboxes.forEach((checkbox) => {
      if (checkbox.checked) {
        const user_id = checkbox.getAttribute('data-user_id');
        if (user_id) {
          selected.push(user_id);
        }
      }
    });
    selected.sort();
    return selected;
  };

  const copy_selected_roster_members = () => {
    if (!rooms_members_input) {
      return;
    }
    const selected = selected_roster_member_ids();
    if (!selected.length) {
      set_rooms_status('status: no roster members selected');
      return;
    }
    rooms_members_input.value = selected.join(', ');
    set_inline_error(rooms_members_input, rooms_members_error, '');
    set_rooms_status(`status: selected ${selected.length} member(s)`);
  };

  const render_rooms_roster = (members) => {
    if (!rooms_roster_list) {
      return;
    }
    rooms_roster_list.textContent = '';
    members.forEach((member) => {
      const row = document.createElement('li');
      row.className = 'rooms-roster-row';
      row.setAttribute('data-test', 'rooms-roster-row');
      // rooms-roster-row marker
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.setAttribute('data-user_id', member.user_id);
      const label = document.createElement('label');
      label.appendChild(checkbox);
      label.append(` ${member.role} ${member.user_id}`);
      row.appendChild(label);
      rooms_roster_list.appendChild(row);
    });
  };

  const refresh_rooms_roster = async () => {
    if (!rooms_conv_id_input) {
      return;
    }
    const conv_id = rooms_conv_id_input.value.trim();
    if (!conv_id) {
      set_rooms_status('status: error (roster: conv_id required)');
      set_inline_error(rooms_conv_id_input, rooms_conv_id_error, 'conv_id is required');
      rooms_conv_id_input.focus();
      return;
    }
    set_inline_error(rooms_conv_id_input, rooms_conv_id_error, '');
    if (!rooms_session_token) {
      set_rooms_status('status: error (roster: session_token required)');
      return;
    }
    const fallback_base_url = derive_http_base_url(gateway_url_input.value.trim());
    const base_url = rooms_http_base_url || fallback_base_url;
    if (!base_url) {
      set_rooms_status('status: error (roster: gateway_url must be ws:// or wss://)');
      return;
    }
    try {
      const request_url = new URL('/v1/rooms/members', base_url);
      request_url.searchParams.set('conv_id', conv_id);
      const response = await fetch(request_url.toString(), {
        method: 'GET',
        headers: {
          Authorization: `Bearer ${rooms_session_token}`,
        },
      });
      let payload = {};
      try {
        payload = await response.json();
      } catch (err) {
        payload = {};
      }
      if (!response.ok) {
        set_rooms_response_status(response, JSON.stringify(payload || {}));
        return;
      }
      const members = payload && Array.isArray(payload.members) ? payload.members : [];
      render_rooms_roster(members);
      set_rooms_status(`status: roster loaded ${members.length}`);
    } catch (err) {
      set_rooms_status(`status: error (roster: ${err.message || 'request failed'})`);
    }
  };

  const request_rooms_action = async (endpoint, action_label) => {
    if (!rooms_conv_id_input || !rooms_members_input) {
      return;
    }
    let conv_id = rooms_conv_id_input.value.trim();
    if (!conv_id && endpoint === '/v1/rooms/create') {
      conv_id = generate_room_id();
      rooms_conv_id_input.value = conv_id;
    }
    if (!conv_id) {
      set_rooms_status(`status: error (${action_label}: conv_id required)`);
      set_inline_error(rooms_conv_id_input, rooms_conv_id_error, 'conv_id is required');
      rooms_conv_id_input.focus();
      return;
    }
    set_inline_error(rooms_conv_id_input, rooms_conv_id_error, '');
    const selected_members = selected_roster_member_ids();
    const members = selected_members.length ? selected_members : parse_members_input(rooms_members_input.value);
    if (!members.length) {
      set_rooms_status(`status: error (${action_label}: members required)`);
      set_inline_error(rooms_members_input, rooms_members_error, 'at least one member user_id is required');
      rooms_members_input.focus();
      return;
    }
    set_inline_error(rooms_members_input, rooms_members_error, '');
    if (!rooms_session_token) {
      set_rooms_status(`status: error (${action_label}: session_token required)`);
      return;
    }
    const fallback_base_url = derive_http_base_url(gateway_url_input.value.trim());
    const base_url = rooms_http_base_url || fallback_base_url;
    if (!base_url) {
      set_rooms_status(`status: error (${action_label}: gateway_url must be ws:// or wss://)`);
      return;
    }
    const request_url = new URL(endpoint, base_url);
    const payload = { conv_id, members };
    try {
      const response = await fetch(request_url.toString(), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${rooms_session_token}`,
        },
        body: JSON.stringify(payload),
      });
      let response_payload = null;
      let response_text = '';
      try {
        response_payload = await response.json();
      } catch (err) {
        response_text = await response.text();
      }
      let payload_text = '{}';
      if (response_payload) {
        payload_text = JSON.stringify(response_payload);
      } else if (response_text) {
        payload_text = JSON.stringify({ message: response_text });
      }
      set_rooms_response_status(response, payload_text);
      if (response.ok && endpoint === '/v1/rooms/create') {
        conv_id_input.value = conv_id;
        maybe_dispatch_conv_selected(conv_id);
        prefill_from_seq().catch((err) => append_log(`failed to prefill from_seq: ${err.message}`));
      }
      if (response.ok) {
        await refresh_conversations();
      }
    } catch (err) {
      set_rooms_status(`status: error (${action_label}: ${err.message || 'request failed'})`);
    }
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

  const parse_optional_seq = (value, label) => {
    if (value === null || value === undefined || value === '') {
      return { value: null };
    }
    const number_value = typeof value === 'number' ? value : Number(value);
    if (typeof number_value !== 'number' || Number.isNaN(number_value) || !Number.isInteger(number_value)) {
      return { error: `${label} must be an integer` };
    }
    if (number_value < 1) {
      return { error: `${label} must be >= 1` };
    }
    return { value: number_value };
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
    const from_seq_result = parse_optional_seq(payload ? payload.from_seq : null, 'from_seq');
    if (from_seq_result.error) {
      return { error: from_seq_result.error };
    }
    const next_seq_result = parse_optional_seq(payload ? payload.next_seq : null, 'next_seq');
    if (next_seq_result.error) {
      return { error: next_seq_result.error };
    }
    const from_seq_value = from_seq_result.value;
    const next_seq_value = next_seq_result.value;
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

  const send_ciphertext_with_deterministic_id = async (conv_id, ciphertext, existing_msg_id = '') => {
    if (!conv_id) {
      append_log('missing conv_id');
      announce_status('send failed missing conv_id');
      return;
    }
    if (!ciphertext) {
      append_log('missing ciphertext');
      announce_status('send failed missing ciphertext');
      return;
    }
    let msg_id = existing_msg_id || msg_id_input.value.trim();
    if (!msg_id) {
      const env_bytes = base64_to_bytes(ciphertext);
      if (!env_bytes) {
        append_log('invalid base64 ciphertext');
        announce_status('send failed invalid base64 ciphertext');
        return;
      }
      msg_id = await sha256_hex(env_bytes);
      msg_id_input.value = msg_id;
    }
    const preview = normalize_preview(ciphertext);
    const pending_item = set_outbox_item(conv_id, msg_id, {
      env: ciphertext,
      status: 'pending',
      ts_ms: now_ms(),
      preview,
      failed_reason: '',
    });
    if (pending_item) {
      render_local_outbound_event(pending_item);
    }
    update_conv_preview(conv_id, preview);
    const send_status = client.send_ciphertext(conv_id, msg_id, ciphertext);
    if (send_status === 'failed') {
      const failed_item = set_outbox_item(conv_id, msg_id, { status: 'failed', failed_reason: 'websocket not connected' });
      if (failed_item) {
        render_local_outbound_event(failed_item);
      }
      announce_status(`send failed for msg_id ${msg_id}`);
    }
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
      this.gateway_url = '';
    }

    connect(url) {
      if (this.ws) {
        this.ws.close();
      }
      this.gateway_url = url;
      this.pending_frames = [];
      append_log(`connecting to ${redact_url(url)}`);
      this.ws = new WebSocket(url);
      this.ws.addEventListener('open', () => {
        connection_status.textContent = 'connected';
        announce_status('connection connected');
        append_log('websocket open');
        this.flush_pending();
      });
      this.ws.addEventListener('close', (evt) => {
        connection_status.textContent = 'disconnected';
        announce_status(`connection disconnected code ${evt.code}`);
        append_log(`websocket closed (code=${evt.code})`);
        mark_all_pending_failed();
        hydrate_local_outbox_rows();
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
        return 'sent';
      }
      if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
        this.pending_frames.push(envelope);
        append_log(`queued ${type} until open`);
        return 'queued';
      }
      append_log('websocket not connected');
      return 'failed';
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
      hide_replay_window_banner();
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
      return this.send_frame('conv.send', { conv_id, msg_id, env: ciphertext });
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
        append_log('session ready');
        const session_token = typeof body.session_token === 'string' ? body.session_token : '';
        const user_id = typeof body.user_id === 'string' ? body.user_id : '';
        const http_base_url = derive_http_base_url(this.gateway_url);
        const resume_token = typeof body.resume_token === 'string' ? body.resume_token : '';
        window.dispatchEvent(
          new CustomEvent('gateway.session.ready', { detail: { session_token, user_id, http_base_url, resume_token, gateway_url: this.gateway_url } })
        );
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
        maybe_mark_delivered_from_echo(body);
        if (typeof body.env === 'string') {
          update_conv_preview(body.conv_id, normalize_preview(body.env), typeof body.ts === 'number' ? body.ts : now_ms());
        }
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
        append_log(`conv.acked ${JSON.stringify(redact_object(body))}`);
        advance_cursor(body.conv_id, body.seq).catch((err) =>
          append_log(`failed to persist conv.acked cursor: ${err.message}`)
        );
        return;
      }
      if (message.t === 'error') {
        if (body.code === 'replay_window_exceeded') {
          const details = parse_replay_window_details(body);
          const active_conv_id = conv_id_input && conv_id_input.value ? conv_id_input.value.trim() : '';
          if (details && active_conv_id) {
            last_from_seq_by_conv_id[active_conv_id] = details.earliest_seq;
            from_seq_input.value = String(details.earliest_seq);
            write_cursor(active_conv_id, details.earliest_seq).catch((err) =>
              append_log(`failed to persist replay_window_exceeded cursor: ${err.message}`)
            );
            show_replay_window_banner(active_conv_id, details);
          }
        }
        append_log(`error ${JSON.stringify(redact_object(body))}`);
        return;
      }
      append_log(`received ${message.t || 'unknown'}: ${JSON.stringify(redact_object(body))}`);
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

  const build_rooms_panel = () => {
    const fieldset = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = 'Rooms v1';
    fieldset.appendChild(legend);

    const conv_row = document.createElement('div');
    conv_row.className = 'button-row';
    const conv_label = document.createElement('label');
    conv_label.textContent = 'conv_id';
    const conv_input = document.createElement('input');
    conv_input.type = 'text';
    conv_input.id = 'rooms_conv_id';
    conv_input.size = 32;
    conv_label.appendChild(conv_input);
    conv_row.appendChild(conv_label);
    const generate_room_id_btn = document.createElement('button');
    generate_room_id_btn.type = 'button';
    generate_room_id_btn.textContent = 'Generate room id';
    conv_row.appendChild(generate_room_id_btn);
    fieldset.appendChild(conv_row);
    const conv_error = document.createElement('p');
    conv_error.className = 'field-error';
    conv_error.hidden = true;
    fieldset.appendChild(conv_error);

    const members_label = document.createElement('label');
    members_label.textContent = 'members (comma-separated user_ids)';
    const members_input = document.createElement('input');
    members_input.type = 'text';
    members_input.id = 'rooms_members';
    members_input.size = 48;
    members_label.appendChild(members_input);
    fieldset.appendChild(members_label);
    const members_error = document.createElement('p');
    members_error.className = 'field-error';
    members_error.hidden = true;
    fieldset.appendChild(members_error);

    const button_row = document.createElement('div');
    button_row.className = 'button-row';
    const create_btn = document.createElement('button');
    create_btn.type = 'button';
    create_btn.textContent = 'Create room';
    const invite_btn = document.createElement('button');
    invite_btn.type = 'button';
    invite_btn.textContent = 'Invite members';
    const remove_btn = document.createElement('button');
    remove_btn.type = 'button';
    remove_btn.textContent = 'Remove members';
    const promote_btn = document.createElement('button');
    promote_btn.type = 'button';
    promote_btn.textContent = 'Promote admins';
    const demote_btn = document.createElement('button');
    demote_btn.type = 'button';
    demote_btn.textContent = 'Demote admins';
    button_row.appendChild(create_btn);
    button_row.appendChild(invite_btn);
    button_row.appendChild(remove_btn);
    button_row.appendChild(promote_btn);
    button_row.appendChild(demote_btn);
    fieldset.appendChild(button_row);

    const roster_actions = document.createElement('div');
    roster_actions.className = 'button-row';
    const refresh_roster_btn = document.createElement('button');
    refresh_roster_btn.type = 'button';
    refresh_roster_btn.textContent = 'Refresh roster';
    const copy_selected_btn = document.createElement('button');
    copy_selected_btn.type = 'button';
    copy_selected_btn.textContent = 'Copy selected to members input';
    roster_actions.appendChild(refresh_roster_btn);
    roster_actions.appendChild(copy_selected_btn);
    fieldset.appendChild(roster_actions);

    const roster_list = document.createElement('ul');
    roster_list.id = 'rooms_roster_list';
    roster_list.setAttribute('data-test', 'rooms-roster-list');
    fieldset.appendChild(roster_list);

    const status_line = document.createElement('p');
    status_line.id = 'rooms_status_line';
    status_line.setAttribute('aria-live', 'polite');
    status_line.textContent = 'status: idle';
    fieldset.appendChild(status_line);

    const event_fieldset = event_log.closest('fieldset');
    if (event_fieldset && event_fieldset.parentNode) {
      event_fieldset.parentNode.insertBefore(fieldset, event_fieldset);
    } else {
      document.body.appendChild(fieldset);
    }

    rooms_conv_id_input = conv_input;
    rooms_members_input = members_input;
    rooms_create_btn = create_btn;
    rooms_invite_btn = invite_btn;
    rooms_remove_btn = remove_btn;
    rooms_promote_btn = promote_btn;
    rooms_demote_btn = demote_btn;
    rooms_generate_room_id_btn = generate_room_id_btn;
    rooms_status_line = status_line;
    rooms_conv_id_error = conv_error;
    rooms_members_error = members_error;
    rooms_refresh_roster_btn = refresh_roster_btn;
    rooms_copy_selected_btn = copy_selected_btn;
    rooms_roster_list = roster_list;
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
      const saved_conv_meta = await read_setting(conv_meta_key);
      if (saved_conv_meta && typeof saved_conv_meta === 'object') {
        Object.assign(conv_meta_by_id, saved_conv_meta);
      }
      const saved_outbox = await read_setting(conv_outbox_key);
      if (saved_outbox && typeof saved_outbox === 'object') {
        Object.assign(conv_outbox_by_id, saved_outbox);
        hydrate_local_outbox_rows();
      }
    } catch (err) {
      append_log(`failed to hydrate inputs: ${err.message}`);
    }
  };

  window.addEventListener('conv.preview.updated', (event) => {
    const detail = event && event.detail ? event.detail : null;
    if (!detail || typeof detail !== 'object') {
      return;
    }
    const conv_id = normalize_conv_id(detail.conv_id);
    const preview = typeof detail.preview === 'string' ? detail.preview : '';
    const ts_ms = Number.isInteger(detail.ts_ms) ? detail.ts_ms : now_ms();
    if (!conv_id || !preview) {
      return;
    }
    update_conv_preview(conv_id, preview, ts_ms);
    refresh_conversations().catch(() => {});
  });

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

  const validate_conv_id_field = (value, field = conv_id_input, error_node = conv_id_error, label = 'conversation id') => {
    const normalized = normalize_conv_id(value);
    if (!normalized) {
      set_inline_error(field, error_node, `${label} is required`);
      return { ok: false, value: '', error: `${label} is required` };
    }
    set_inline_error(field, error_node, '');
    return { ok: true, value: normalized, error: '' };
  };

  const focus_conversations_list = () => {
    if (!conversations_list) {
      return;
    }
    const options = Array.from(conversations_list.querySelectorAll('button[data-roving-tabindex="true"]'));
    if (!options.length) {
      return;
    }
    const next_index = Math.max(0, Math.min(last_selected_conv_index, options.length - 1));
    options.forEach((option, option_index) => {
      const selected = option_index === next_index;
      option.setAttribute('tabindex', selected ? '0' : '-1');
      option.setAttribute('aria-selected', selected ? 'true' : 'false');
      option.setAttribute('aria-current', selected ? 'true' : 'false');
    });
    options[next_index].focus();
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

  window.addEventListener('conv.selected', (event) => {
    const detail = event && event.detail ? event.detail : null;
    if (!detail || typeof detail !== 'object') {
      return;
    }
    if (rooms_conv_id_input && typeof detail.conv_id === 'string') {
      rooms_conv_id_input.value = detail.conv_id;
    }
    const selected_members = Array.isArray(detail.members)
      ? detail.members.filter((member) => typeof member === 'string')
      : [];
    if (rooms_members_input && selected_members.length > 0 && selected_members.length <= 20) {
      const prefill_members = selected_members
        .filter((member) => member !== conversations_user_id)
        .join(',');
      if (prefill_members) {
        rooms_members_input.value = prefill_members;
      }
    }
  });

  const handle_gateway_subscribe = (event) => {
    const detail = event && event.detail ? event.detail : null;
    if (!detail || typeof detail !== 'object') {
      return;
    }
    const conv_id = normalize_conv_id(detail.conv_id);
    if (!conv_id) {
      append_log('gateway.subscribe missing conv_id');
      return;
    }
    maybe_dispatch_conv_selected(conv_id);
    const from_seq_value = detail.from_seq;
    if (typeof from_seq_value === 'number' && !Number.isNaN(from_seq_value)) {
      last_from_seq_by_conv_id[conv_id] = from_seq_value;
      client.subscribe(conv_id, from_seq_value);
      return;
    }
    read_cursor(conv_id)
      .then((stored_next_seq) => {
        const resolved_from_seq = stored_next_seq ?? 1;
        last_from_seq_by_conv_id[conv_id] = resolved_from_seq;
        client.subscribe(conv_id, resolved_from_seq);
      })
      .catch((err) => append_log(`gateway.subscribe cursor read failed: ${err.message}`));
  };

  if (conversations_refresh_btn) {
    conversations_refresh_btn.addEventListener('click', () => {
      refresh_conversations().catch((err) =>
        set_conversations_status(`status: error (${err.message || 'fetch failed'})`)
      );
    });
  }

  subscribe_btn.addEventListener('click', async () => {
    const conv_validation = validate_conv_id_field(conv_id_input.value);
    if (!conv_validation.ok) {
      conv_id_input.focus();
      announce_status(`error ${conv_validation.error}`);
      return;
    }
    const conv_id = conv_validation.value;
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
    const conv_validation = validate_conv_id_field(conv_id_input.value);
    if (!conv_validation.ok) {
      conv_id_input.focus();
      announce_status(`error ${conv_validation.error}`);
      return;
    }
    const seq_value = Number(seq_input.value);
    client.ack(conv_validation.value, seq_value);
  });

  send_btn.addEventListener('click', async () => {
    const conv_validation = validate_conv_id_field(conv_id_input.value);
    if (!conv_validation.ok) {
      conv_id_input.focus();
      announce_status(`error ${conv_validation.error}`);
      return;
    }
    const conv_id = conv_validation.value;
    const ciphertext = ciphertext_input.value.trim();
    if (!ciphertext) {
      set_inline_error(ciphertext_input, compose_error, 'ciphertext payload is required');
      ciphertext_input.focus();
      announce_status('error ciphertext payload is required');
      return;
    }
    set_inline_error(ciphertext_input, compose_error, '');
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
    set_inline_error(conv_id_input, conv_id_error, '');
    maybe_dispatch_conv_selected(conv_id_input.value);
  });
  ciphertext_input.addEventListener('input', () => {
    set_inline_error(ciphertext_input, compose_error, '');
  });

  [ciphertext_input, msg_id_input].forEach((input) => {
    if (!input) {
      return;
    }
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        focus_conversations_list();
      }
    });
  });

  conv_id_input.addEventListener('blur', () => {
    prefill_from_seq().catch((err) => append_log(`failed to prefill from_seq: ${err.message}`));
    maybe_dispatch_conv_selected(conv_id_input.value);
  });

  const initial_conv_id = normalize_conv_id(conv_id_input ? conv_id_input.value : '');
  if (initial_conv_id) {
    maybe_dispatch_conv_selected(initial_conv_id);
  }

  window.addEventListener('gateway.subscribe', handle_gateway_subscribe);

  if (replay_window_resubscribe_btn) {
    replay_window_resubscribe_btn.addEventListener('click', () => {
      if (!replay_window_conv_id || !Number.isInteger(replay_window_earliest_seq)) {
        append_log('replay-window resubscribe unavailable: missing conv_id or earliest_seq');
        return;
      }
      conv_id_input.value = replay_window_conv_id;
      from_seq_input.value = String(replay_window_earliest_seq);
      last_from_seq_by_conv_id[replay_window_conv_id] = replay_window_earliest_seq;
      client.subscribe(replay_window_conv_id, replay_window_earliest_seq);
    });
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

  window.addEventListener('gateway.session.ready', (event) => {
    const detail = event && event.detail ? event.detail : {};
    rooms_session_token = typeof detail.session_token === 'string' ? detail.session_token : '';
    rooms_http_base_url = typeof detail.http_base_url === 'string' ? detail.http_base_url : '';
    if (!rooms_session_token) {
      set_rooms_status('status: session_token missing');
    } else if (rooms_http_base_url) {
      set_rooms_status(`status: ready (${rooms_http_base_url})`);
    } else {
      set_rooms_status('status: ready');
    }

    conversations_session_token = rooms_session_token;
    conversations_http_base_url = rooms_http_base_url;
    conversations_user_id = typeof detail.user_id === 'string' ? detail.user_id : '';
    refresh_conversations().catch((err) =>
      set_conversations_status(`status: error (${err.message || 'fetch failed'})`)
    );
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

  build_rooms_panel();
  if (rooms_create_btn) {
    rooms_create_btn.addEventListener('click', () => {
      request_rooms_action('/v1/rooms/create', 'create').catch((err) =>
        set_rooms_status(`status: error (create: ${err.message || 'request failed'})`)
      );
    });
  }
  if (rooms_invite_btn) {
    rooms_invite_btn.addEventListener('click', () => {
      request_rooms_action('/v1/rooms/invite', 'invite').catch((err) =>
        set_rooms_status(`status: error (invite: ${err.message || 'request failed'})`)
      );
    });
  }
  if (rooms_remove_btn) {
    rooms_remove_btn.addEventListener('click', () => {
      request_rooms_action('/v1/rooms/remove', 'remove').catch((err) =>
        set_rooms_status(`status: error (remove: ${err.message || 'request failed'})`)
      );
    });
  }
  if (rooms_promote_btn) {
    rooms_promote_btn.addEventListener('click', () => {
      request_rooms_action('/v1/rooms/promote', 'promote').catch((err) =>
        set_rooms_status(`status: error (promote: ${err.message || 'request failed'})`)
      );
    });
  }
  if (rooms_demote_btn) {
    rooms_demote_btn.addEventListener('click', () => {
      request_rooms_action('/v1/rooms/demote', 'demote').catch((err) =>
        set_rooms_status(`status: error (demote: ${err.message || 'request failed'})`)
      );
    });
  }
  if (rooms_generate_room_id_btn) {
    rooms_generate_room_id_btn.addEventListener('click', () => {
      if (rooms_conv_id_input) {
        rooms_conv_id_input.value = generate_room_id();
      }
    });
  }
  if (rooms_refresh_roster_btn) {
    rooms_refresh_roster_btn.addEventListener('click', () => {
      refresh_rooms_roster().catch((err) =>
        set_rooms_status(`status: error (roster: ${err.message || 'request failed'})`)
      );
    });
  }
  if (rooms_copy_selected_btn) {
    rooms_copy_selected_btn.addEventListener('click', () => {
      copy_selected_roster_members();
    });
  }
  if (rooms_conv_id_input) {
    rooms_conv_id_input.addEventListener('input', () => {
      set_inline_error(rooms_conv_id_input, rooms_conv_id_error, '');
    });
  }
  if (rooms_members_input) {
    rooms_members_input.addEventListener('input', () => {
      set_inline_error(rooms_members_input, rooms_members_error, '');
    });
  }

  build_social_panel();
  if (social_fetch_btn) {
    social_fetch_btn.addEventListener('click', () => {
      fetch_social_events().catch((err) => render_social_error(err.message || 'fetch failed'));
    });
  }
  hydrate_inputs();
  const now_ms = () => Date.now();

  const to_timestamp_label = (ts_ms) => {
    if (!Number.isInteger(ts_ms) || ts_ms <= 0) {
      return '';
    }
    return new Date(ts_ms).toLocaleTimeString();
  };

  const normalize_preview = (value) => {
    if (typeof value !== 'string') {
      return '';
    }
    const single_line = value.replace(/\s+/g, ' ').trim();
    if (!single_line) {
      return '';
    }
    return single_line.length > 80 ? `${single_line.slice(0, 80)}…` : single_line;
  };

  const ensure_conv_meta = (conv_id) => {
    if (!conv_id) {
      return null;
    }
    if (!conv_meta_by_id[conv_id]) {
      conv_meta_by_id[conv_id] = { label: '', last_preview: '', last_ts_ms: 0 };
    }
    return conv_meta_by_id[conv_id];
  };

  const persist_conv_meta = async () => {
    await write_setting(conv_meta_key, conv_meta_by_id);
  };

  const persist_conv_outbox = async () => {
    await write_setting(conv_outbox_key, conv_outbox_by_id);
  };

  const update_conv_preview = (conv_id, preview, ts_ms = now_ms()) => {
    const normalized_conv_id = normalize_conv_id(conv_id);
    if (!normalized_conv_id) {
      return;
    }
    const meta = ensure_conv_meta(normalized_conv_id);
    if (!meta) {
      return;
    }
    const normalized_preview = normalize_preview(preview);
    if (normalized_preview) {
      meta.last_preview = normalized_preview;
    }
    meta.last_ts_ms = Number.isInteger(ts_ms) ? ts_ms : now_ms();
    persist_conv_meta().catch((err) => append_log(`failed to persist conv metadata: ${err.message}`));
  };

  const set_outbox_item = (conv_id, msg_id, patch) => {
    const normalized_conv_id = normalize_conv_id(conv_id);
    if (!normalized_conv_id || !msg_id) {
      return null;
    }
    if (!conv_outbox_by_id[normalized_conv_id]) {
      conv_outbox_by_id[normalized_conv_id] = {};
    }
    const existing = conv_outbox_by_id[normalized_conv_id][msg_id] || { msg_id, conv_id: normalized_conv_id };
    const next = { ...existing, ...patch, msg_id, conv_id: normalized_conv_id };
    conv_outbox_by_id[normalized_conv_id][msg_id] = next;
    persist_conv_outbox().catch((err) => append_log(`failed to persist outbox state: ${err.message}`));
    return next;
  };

  const mark_all_pending_failed = () => {
    Object.keys(conv_outbox_by_id).forEach((conv_id) => {
      const entries = conv_outbox_by_id[conv_id] || {};
      Object.keys(entries).forEach((msg_id) => {
        if (entries[msg_id] && entries[msg_id].status === 'pending') {
          set_outbox_item(conv_id, msg_id, { status: 'failed', failed_reason: 'connection closed' });
        }
      });
    });
  };

  const render_local_outbound_event = (item) => {
    if (!item || !item.msg_id || !item.conv_id) {
      return;
    }
    let entry = pending_entry_by_msg_id[item.msg_id] || null;
    if (!entry) {
      entry = document.createElement('div');
      entry.dataset.msg_id = item.msg_id;
      entry.dataset.conv_id = item.conv_id;
      event_log.prepend(entry);
      pending_entry_by_msg_id[item.msg_id] = entry;
    }
    const status = item.status || 'pending';
    const status_label = status === 'delivered' ? 'delivered' : status === 'failed' ? 'failed' : 'pending';
    entry.dataset.test = status === 'pending' ? 'msg-pending' : status === 'failed' ? 'msg-failed' : 'msg-delivered';
    const parts = [`conv_id=${item.conv_id}`, `msg_id=${item.msg_id}`, `status=${status_label}`];
    if (Number.isInteger(item.seq)) {
      parts.push(`seq=${item.seq}`);
    }
    const preview = item.preview || '';
    entry.textContent = `${parts.join(' ')} preview=${preview}`;
    if (status === 'failed') {
      const retry_btn = document.createElement('button');
      retry_btn.type = 'button';
      retry_btn.dataset.test = 'msg-retry';
      retry_btn.textContent = 'Retry send';
      retry_btn.setAttribute('aria-label', `Retry send for msg_id ${item.msg_id} preview ${preview || 'none'}`);
      retry_btn.addEventListener('click', async () => {
        msg_id_input.value = item.msg_id;
        ciphertext_input.value = item.env || '';
        conv_id_input.value = item.conv_id;
        await send_ciphertext_with_deterministic_id(item.conv_id, item.env || '', item.msg_id);
        last_selected_message_entry = entry;
        window.setTimeout(() => {
          if (last_selected_message_entry) {
            last_selected_message_entry.setAttribute('tabindex', '-1');
            last_selected_message_entry.focus();
          }
        }, 0);
        announce_status(`retry queued for msg_id ${item.msg_id}`);
      });
      entry.append(' ');
      entry.appendChild(retry_btn);
    }
  };

  const hydrate_local_outbox_rows = () => {
    Object.keys(conv_outbox_by_id).forEach((conv_id) => {
      const entries = conv_outbox_by_id[conv_id] || {};
      Object.keys(entries)
        .sort()
        .forEach((msg_id) => render_local_outbound_event(entries[msg_id]));
    });
  };

  const maybe_mark_delivered_from_echo = (body) => {
    if (!body || typeof body !== 'object') {
      return;
    }
    const conv_id = normalize_conv_id(body.conv_id);
    const msg_id = typeof body.msg_id === 'string' ? body.msg_id : '';
    if (!conv_id || !msg_id) {
      return;
    }
    const existing = conv_outbox_by_id[conv_id] && conv_outbox_by_id[conv_id][msg_id];
    if (!existing) {
      return;
    }
    const seq = Number.isInteger(body.seq) ? body.seq : null;
    const delivered = set_outbox_item(conv_id, msg_id, { status: 'delivered', seq: seq || undefined });
    if (delivered) {
      render_local_outbound_event(delivered);
    }
  };
})();
