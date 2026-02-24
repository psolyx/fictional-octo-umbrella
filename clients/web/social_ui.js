import { read_identity } from './identity.js';
import { sign_social_event } from './social_sign.js';

const social_user_id_input = document.getElementById('social_user_id');
const social_limit_input = document.getElementById('social_limit');
const social_fetch_btn = document.getElementById('social_fetch_btn');
const social_status = document.getElementById('social_status');
const social_etag_input = document.getElementById('social_etag');
const social_event_list = document.getElementById('social_event_list');
const profile_refresh_btn = document.getElementById('profile_refresh_btn');
const feed_refresh_btn = document.getElementById('feed_refresh_btn');
const follow_toggle_btn = document.getElementById('follow_toggle_btn');
const profile_message_btn = document.getElementById('profile_message_btn');

const social_prev_hash_input = document.getElementById('social_prev_hash');
const social_kind_input = document.getElementById('social_kind');
const social_ts_ms_input = document.getElementById('social_ts_ms');
const social_payload_json_input = document.getElementById('social_payload_json');
const social_sig_b64_input = document.getElementById('social_sig_b64');
const social_publish_btn = document.getElementById('social_publish_btn');

const profile_banner = document.getElementById('profile_banner');
const profile_avatar = document.getElementById('profile_avatar');
const profile_username = document.getElementById('profile_username');
const profile_about_text = document.getElementById('profile_about_text');
const profile_interests_text = document.getElementById('profile_interests_text');
const profile_friends_list = document.getElementById('profile_friends_list');
const profile_bulletins_list = document.getElementById('profile_bulletins_list');
const home_feed = document.getElementById('home_feed');

const bulletin_text_input = document.getElementById('bulletin_text');
const bulletin_post_btn = document.getElementById('bulletin_post_btn');
const profile_update_btn = document.getElementById('profile_update_btn');
const profile_username_input = document.getElementById('profile_username_input');
const profile_description_input = document.getElementById('profile_description_input');
const profile_avatar_input = document.getElementById('profile_avatar_input');
const profile_banner_input = document.getElementById('profile_banner_input');
const profile_interests_input = document.getElementById('profile_interests_input');

let social_session_token = '';
let social_http_base_url = '';
let local_user_id = '';
let viewed_user_id = '';
let latest_profile_view = null;
const prefer_client_generated_dm_conv_id = false;

const set_social_status = (text) => {
  if (social_status) {
    social_status.textContent = text;
  }
};

const get_social_api_base = () => {
  if (!social_http_base_url) {
    return '';
  }
  return social_http_base_url.endsWith('/') ? social_http_base_url.slice(0, -1) : social_http_base_url;
};

const read_social_limit = () => {
  const parsed = Number.parseInt(social_limit_input ? social_limit_input.value : '20', 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 20;
};

const clear_children = (node) => {
  if (node) {
    node.textContent = '';
  }
};

const payload_preview = (payload) => {
  if (payload === null || payload === undefined) {
    return 'null';
  }
  if (typeof payload === 'string') {
    return payload;
  }
  return JSON.stringify(payload);
};

const append_event_row = (user_id, social_event) => {
  if (!social_event_list) {
    return;
  }
  const row = document.createElement('pre');
  row.textContent = `user_id: ${user_id}\nkind: ${social_event.kind}\nts_ms: ${social_event.ts_ms}\npayload: ${payload_preview(social_event.payload)}`;
  social_event_list.appendChild(row);
};

const fetch_social_events = async () => {
  const user_id = social_user_id_input ? social_user_id_input.value.trim() : '';
  if (!user_id) {
    set_social_status('enter social_user_id');
    return;
  }
  viewed_user_id = user_id;
  const params = new URLSearchParams({ user_id, limit: String(read_social_limit()) });
  const response = await fetch(`${get_social_api_base()}/v1/social/events?${params.toString()}`);
  if (social_etag_input) {
    social_etag_input.value = response.headers.get('etag') || '';
  }
  clear_children(social_event_list);
  if (!response.ok) {
    set_social_status(`fetch failed (${response.status})`);
    return;
  }
  const body = await response.json();
  const social_events = Array.isArray(body.events) ? body.events : [];
  social_events.forEach((social_event) => append_event_row(user_id, social_event));
  set_social_status(`rendered ${social_events.length} event(s)`);
};

const publish_social_event = async (kind, payload, prev_hash = '') => {
  if (!social_session_token) {
    set_social_status('publish requires gateway session token');
    return null;
  }
  const ts_ms = Date.now();
  let sig_b64 = social_sig_b64_input ? social_sig_b64_input.value.trim() : '';
  if (!sig_b64) {
    const identity = read_identity();
    if (!identity) {
      set_social_status('missing identity; generate or import in Account section');
      return null;
    }
    try {
      const signed = await sign_social_event({
        social_private_key_b64: identity.social_private_key_b64,
        user_id: identity.social_public_key_b64,
        prev_hash,
        ts_ms,
        kind,
        payload,
      });
      sig_b64 = signed.sig_b64;
      if (social_sig_b64_input) {
        social_sig_b64_input.value = sig_b64;
      }
    } catch (error) {
      set_social_status(`WebCrypto Ed25519 unavailable (${error.message}); use advanced sig_b64 field`);
      return null;
    }
  }
  const body = { kind, payload, ts_ms, sig_b64 };
  if (prev_hash) {
    body.prev_hash = prev_hash;
  }
  const response = await fetch(`${get_social_api_base()}/v1/social/events`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${social_session_token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    set_social_status(`publish failed (${response.status})`);
    return null;
  }
  const result = await response.json();
  if (social_prev_hash_input) {
    social_prev_hash_input.value = result.event_hash || '';
  }
  return result;
};

const render_profile = (profile_body) => {
  latest_profile_view = profile_body;
  if (profile_username) {
    profile_username.textContent = profile_body.username || profile_body.user_id || 'unknown';
  }
  if (profile_about_text) {
    profile_about_text.textContent = profile_body.description || '—';
  }
  if (profile_interests_text) {
    profile_interests_text.textContent = profile_body.interests || '—';
  }
  if (profile_avatar) {
    const avatar = profile_body.avatar || '';
    profile_avatar.src = avatar || 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
  }
  if (profile_banner) {
    const banner = profile_body.banner || '';
    profile_banner.style.backgroundImage = banner ? `url(${banner})` : '';
  }

  clear_children(profile_friends_list);
  const friends = Array.isArray(profile_body.friends) ? profile_body.friends : [];
  friends.forEach((friend_user_id) => {
    const item = document.createElement('li');
    item.className = 'profile_friend_row';
    const view_btn = document.createElement('button');
    view_btn.type = 'button';
    view_btn.textContent = friend_user_id;
    view_btn.addEventListener('click', () => {
      if (social_user_id_input) {
        social_user_id_input.value = friend_user_id;
      }
      viewed_user_id = friend_user_id;
      window.dispatchEvent(new CustomEvent('social.peer.selected', { detail: { user_id: friend_user_id } }));
      void fetch_profile_view();
    });
    const message_btn = document.createElement('button');
    message_btn.type = 'button';
    message_btn.dataset.test = 'friends-start-dm';
    message_btn.textContent = 'Message';
    message_btn.addEventListener('click', () => {
      void start_dm_with_peer(friend_user_id, friend_user_id);
    });
    item.appendChild(view_btn);
    item.appendChild(message_btn);
    profile_friends_list.appendChild(item);
  });

  clear_children(profile_bulletins_list);
  const posts = Array.isArray(profile_body.latest_posts) ? profile_body.latest_posts : [];
  posts.forEach((post) => {
    const item = document.createElement('li');
    const payload = post && post.payload ? post.payload : {};
    item.textContent = payload.value || payload.text || JSON.stringify(payload);
    profile_bulletins_list.appendChild(item);
  });

  if (follow_toggle_btn) {
    follow_toggle_btn.textContent = 'Add Friend';
  }
  if (profile_message_btn) {
    const is_peer_profile = !!viewed_user_id && viewed_user_id !== local_user_id;
    profile_message_btn.disabled = !(is_peer_profile && !!social_session_token);
    profile_message_btn.style.display = is_peer_profile ? '' : 'none';
  }
};

const generate_dm_conv_id_fallback = () => {
  const random_bytes = new Uint8Array(9);
  crypto.getRandomValues(random_bytes);
  const token = btoa(String.fromCharCode(...random_bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  return `dm_${token}`;
};

const start_dm_with_peer = async (peer_user_id, peer_display_name = '') => {
  if (!social_session_token || !social_http_base_url) {
    set_social_status('message requires gateway session');
    return;
  }
  if (!peer_user_id || peer_user_id === local_user_id) {
    set_social_status('select another profile to message');
    return;
  }
  const payload = { peer_user_id };
  if (prefer_client_generated_dm_conv_id) {
    payload.conv_id = generate_dm_conv_id_fallback();
  }
  const response = await fetch(`${get_social_api_base()}/v1/dms/create`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${social_session_token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    set_social_status(`message failed (${response.status})`);
    return;
  }
  const body = await response.json();
  const conv_id = typeof body.conv_id === 'string' ? body.conv_id : '';
  if (!conv_id) {
    set_social_status('message failed (missing conv_id)');
    return;
  }
  window.dispatchEvent(
    new CustomEvent('social.dm.created', {
      detail: {
        conv_id,
        peer_user_id,
        peer_display_name,
      },
    })
  );
  set_social_status(`DM ready with ${peer_display_name || peer_user_id}`);
};

const fetch_profile_view = async () => {
  const user_id = viewed_user_id || (social_user_id_input ? social_user_id_input.value.trim() : '');
  if (!user_id) {
    return;
  }
  const params = new URLSearchParams({ user_id, limit: String(read_social_limit()) });
  const response = await fetch(`${get_social_api_base()}/v1/social/profile?${params.toString()}`);
  if (!response.ok) {
    set_social_status(`profile fetch failed (${response.status})`);
    return;
  }
  const body = await response.json();
  render_profile(body);
};

const render_home_feed = (feed_body) => {
  clear_children(home_feed);
  const items = Array.isArray(feed_body.items) ? feed_body.items : [];
  items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'feed_entry';
    const controls = document.createElement('div');
    controls.className = 'feed_entry_controls';
    const author_btn = document.createElement('button');
    author_btn.type = 'button';
    author_btn.textContent = item.user_id;
    author_btn.addEventListener('click', () => {
      if (social_user_id_input) {
        social_user_id_input.value = item.user_id;
      }
      viewed_user_id = item.user_id;
      void fetch_profile_view();
    });
    const message_btn = document.createElement('button');
    message_btn.type = 'button';
    message_btn.dataset.test = 'feed-start-dm';
    message_btn.textContent = 'Message';
    message_btn.disabled = !item.user_id || item.user_id === local_user_id;
    message_btn.addEventListener('click', () => {
      void start_dm_with_peer(item.user_id, item.username || item.user_id);
    });
    controls.appendChild(author_btn);
    controls.appendChild(message_btn);
    row.appendChild(controls);
    const body = document.createElement('pre');
    const text = item && item.payload ? item.payload.value || item.payload.text || JSON.stringify(item.payload) : '';
    body.textContent = `${item.user_id} • ${item.ts_ms}\n${text}`;
    row.appendChild(body);
    home_feed.appendChild(row);
  });
};

const fetch_home_feed = async () => {
  if (!local_user_id) {
    return;
  }
  const params = new URLSearchParams({ user_id: local_user_id, limit: String(read_social_limit()) });
  const response = await fetch(`${get_social_api_base()}/v1/social/feed?${params.toString()}`);
  if (!response.ok) {
    set_social_status(`feed fetch failed (${response.status})`);
    return;
  }
  render_home_feed(await response.json());
};

const submit_profile_updates = async () => {
  const updates = [
    ['username', profile_username_input ? profile_username_input.value.trim() : ''],
    ['description', profile_description_input ? profile_description_input.value.trim() : ''],
    ['avatar', profile_avatar_input ? profile_avatar_input.value.trim() : ''],
    ['banner', profile_banner_input ? profile_banner_input.value.trim() : ''],
    ['interests', profile_interests_input ? profile_interests_input.value.trim() : ''],
  ];
  for (const [kind, value] of updates) {
    if (!value) {
      continue;
    }
    await publish_social_event(kind, { value });
  }
  set_social_status('profile update attempted');
  void fetch_profile_view();
};

const post_bulletin = async () => {
  const value = bulletin_text_input ? bulletin_text_input.value.trim() : '';
  if (!value) {
    set_social_status('enter bulletin text');
    return;
  }
  await publish_social_event('post', { value });
  set_social_status('bulletin publish attempted');
  void fetch_profile_view();
  void fetch_home_feed();
};

const toggle_follow = async () => {
  if (!viewed_user_id || viewed_user_id === local_user_id) {
    set_social_status('select another profile to follow/unfollow');
    return;
  }
  let currently_following = false;
  const local_params = new URLSearchParams({ user_id: local_user_id, limit: '100' });
  const local_profile_resp = await fetch(`${get_social_api_base()}/v1/social/profile?${local_params.toString()}`);
  if (local_profile_resp.ok) {
    const local_profile = await local_profile_resp.json();
    currently_following = Array.isArray(local_profile.friends) && local_profile.friends.includes(viewed_user_id);
  }
  const following = !currently_following;
  await publish_social_event('follow', { target_user_id: viewed_user_id, following });
  set_social_status(following ? 'follow requested' : 'unfollow requested');
  if (follow_toggle_btn) {
    follow_toggle_btn.textContent = following ? 'Remove Friend' : 'Add Friend';
  }
  void fetch_profile_view();
  void fetch_home_feed();
};

const publish_from_debug_form = async () => {
  const kind = social_kind_input ? social_kind_input.value.trim() : '';
  const prev_hash = social_prev_hash_input ? social_prev_hash_input.value.trim() : '';
  const payload_text = social_payload_json_input ? social_payload_json_input.value.trim() : '{}';
  let payload;
  try {
    payload = payload_text ? JSON.parse(payload_text) : {};
  } catch (_error) {
    set_social_status('invalid payload_json');
    return;
  }
  await publish_social_event(kind, payload, prev_hash);
};

window.addEventListener('gateway.session.ready', (event) => {
  const detail = event && event.detail ? event.detail : {};
  social_session_token = typeof detail.session_token === 'string' ? detail.session_token : '';
  social_http_base_url = typeof detail.http_base_url === 'string' ? detail.http_base_url : '';
  local_user_id = typeof detail.user_id === 'string' ? detail.user_id : '';
  viewed_user_id = local_user_id;
  if (social_user_id_input && !social_user_id_input.value) {
    social_user_id_input.value = local_user_id;
  }
});

if (social_fetch_btn) social_fetch_btn.addEventListener('click', () => void fetch_social_events());
if (profile_refresh_btn) profile_refresh_btn.addEventListener('click', () => void fetch_profile_view());
if (feed_refresh_btn) feed_refresh_btn.addEventListener('click', () => void fetch_home_feed());
if (social_publish_btn) social_publish_btn.addEventListener('click', () => void publish_from_debug_form());
if (profile_update_btn) profile_update_btn.addEventListener('click', () => void submit_profile_updates());
if (bulletin_post_btn) bulletin_post_btn.addEventListener('click', () => void post_bulletin());
if (follow_toggle_btn) follow_toggle_btn.addEventListener('click', () => void toggle_follow());
if (profile_message_btn) {
  profile_message_btn.addEventListener('click', () => {
    void start_dm_with_peer(viewed_user_id, (latest_profile_view && latest_profile_view.username) || viewed_user_id);
  });
}
