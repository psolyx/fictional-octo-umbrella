const social_user_id_input = document.getElementById('social_user_id');
const social_limit_input = document.getElementById('social_limit');
const social_fetch_btn = document.getElementById('social_fetch_btn');
const social_status = document.getElementById('social_status');
const social_etag_input = document.getElementById('social_etag');
const social_event_list = document.getElementById('social_event_list');

const social_prev_hash_input = document.getElementById('social_prev_hash');
const social_kind_input = document.getElementById('social_kind');
const social_ts_ms_input = document.getElementById('social_ts_ms');
const social_payload_json_input = document.getElementById('social_payload_json');
const social_sig_b64_input = document.getElementById('social_sig_b64');
const social_publish_btn = document.getElementById('social_publish_btn');

let social_session_token = '';
let social_http_base_url = '';

const set_social_status = (text) => {
  if (social_status) {
    social_status.textContent = text;
  }
};

const format_ts_ms = (value) => {
  const ts_ms = Number(value);
  if (!Number.isFinite(ts_ms) || ts_ms <= 0) {
    return 'n/a';
  }
  const iso = new Date(ts_ms).toISOString();
  return `${ts_ms} (${iso})`;
};

const payload_preview = (payload) => {
  if (payload === null || payload === undefined) {
    return 'null';
  }
  if (typeof payload === 'string') {
    return payload.length > 160 ? `${payload.slice(0, 160)}…` : payload;
  }
  const json_text = JSON.stringify(payload);
  if (!json_text) {
    return String(payload);
  }
  return json_text.length > 160 ? `${json_text.slice(0, 160)}…` : json_text;
};

const clear_social_event_list = () => {
  if (!social_event_list) {
    return;
  }
  social_event_list.textContent = '';
};

const add_social_event_row = (user_id, social_event) => {
  if (!social_event_list) {
    return;
  }
  const row = document.createElement('div');
  row.className = 'social_event_row';

  const content = document.createElement('pre');
  const ts_value = format_ts_ms(social_event && social_event.ts_ms);
  const kind_value = social_event && social_event.kind ? String(social_event.kind) : '';
  const hash_value = social_event && social_event.event_hash ? String(social_event.event_hash) : '';
  const prev_hash_value = social_event && social_event.prev_hash ? String(social_event.prev_hash) : '';
  content.textContent = [
    `user_id: ${user_id}`,
    `ts_ms: ${ts_value}`,
    `kind: ${kind_value || 'n/a'}`,
    `payload: ${payload_preview(social_event && social_event.payload)}`,
    `event_hash: ${hash_value || 'n/a'}`,
    `prev_hash: ${prev_hash_value || 'n/a'}`,
  ].join('\n');
  row.appendChild(content);

  const use_peer_btn = document.createElement('button');
  use_peer_btn.type = 'button';
  use_peer_btn.textContent = 'Use as DM peer';
  use_peer_btn.addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('social.peer.selected', { detail: { user_id } }));
    set_social_status(`peer selected: ${user_id}`);
  });
  row.appendChild(use_peer_btn);

  social_event_list.appendChild(row);
};

const get_social_api_base = () => {
  if (!social_http_base_url) {
    return '';
  }
  return social_http_base_url.endsWith('/')
    ? social_http_base_url.slice(0, social_http_base_url.length - 1)
    : social_http_base_url;
};

const read_social_limit = () => {
  const raw = social_limit_input ? social_limit_input.value : '20';
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return 20;
  }
  return parsed;
};

const fetch_social_events = async () => {
  const user_id = social_user_id_input ? social_user_id_input.value.trim() : '';
  if (!user_id) {
    set_social_status('enter social_user_id');
    return;
  }
  const limit = read_social_limit();
  const query = new URLSearchParams({ user_id, limit: String(limit) });
  const request_url = `${get_social_api_base()}/v1/social/events?${query.toString()}`;
  set_social_status('fetching…');
  clear_social_event_list();
  if (social_etag_input) {
    social_etag_input.value = '';
  }
  try {
    const response = await fetch(request_url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    });
    const response_etag = response.headers.get('etag') || '';
    if (social_etag_input) {
      social_etag_input.value = response_etag;
    }
    if (!response.ok) {
      set_social_status(`fetch failed (${response.status})`);
      return;
    }
    const body = await response.json();
    const social_events = Array.isArray(body && body.events) ? body.events : [];
    if (social_events.length === 0) {
      set_social_status('no events');
      return;
    }
    social_events.forEach((social_event) => {
      add_social_event_row(user_id, social_event);
    });
    set_social_status(`rendered ${social_events.length} event(s)`);
  } catch (error) {
    set_social_status(`fetch error (${String(error)})`);
  }
};

const publish_social_event = async () => {
  if (!social_session_token) {
    set_social_status('publish requires gateway session token');
    return;
  }
  const kind = social_kind_input ? social_kind_input.value.trim() : '';
  if (!kind) {
    set_social_status('publish requires kind');
    return;
  }
  const ts_ms_raw = social_ts_ms_input ? social_ts_ms_input.value.trim() : '';
  const ts_ms = ts_ms_raw ? Number.parseInt(ts_ms_raw, 10) : Date.now();
  if (!Number.isInteger(ts_ms) || ts_ms < 0) {
    set_social_status('invalid ts_ms');
    return;
  }

  let payload = {};
  const payload_text = social_payload_json_input ? social_payload_json_input.value.trim() : '{}';
  try {
    payload = payload_text ? JSON.parse(payload_text) : {};
  } catch (_error) {
    set_social_status('invalid payload_json');
    return;
  }

  const prev_hash = social_prev_hash_input ? social_prev_hash_input.value.trim() : '';
  const sig_b64 = social_sig_b64_input ? social_sig_b64_input.value.trim() : '';

  const body = { kind, payload, ts_ms, sig_b64 };
  if (prev_hash) {
    body.prev_hash = prev_hash;
  }

  set_social_status('publishing…');
  try {
    const response = await fetch(`${get_social_api_base()}/v1/social/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Authorization: `Bearer ${social_session_token}`,
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      set_social_status(`publish failed (${response.status})`);
      return;
    }
    set_social_status('publish ok');
  } catch (error) {
    set_social_status(`publish error (${String(error)})`);
  }
};

window.addEventListener('gateway.session.ready', (event) => {
  const detail = event && event.detail ? event.detail : null;
  social_session_token = detail && typeof detail.session_token === 'string' ? detail.session_token : '';
  social_http_base_url = detail && typeof detail.http_base_url === 'string' ? detail.http_base_url : '';
  if (social_ts_ms_input) {
    social_ts_ms_input.value = String(Date.now());
  }
  if (social_user_id_input && !social_user_id_input.value && detail && typeof detail.user_id === 'string') {
    social_user_id_input.value = detail.user_id;
  }
});

if (social_fetch_btn) {
  social_fetch_btn.addEventListener('click', () => {
    void fetch_social_events();
  });
}

if (social_publish_btn) {
  social_publish_btn.addEventListener('click', () => {
    void publish_social_event();
  });
}
