import { verify_vectors_from_url } from './mls_vectors_loader.js';

const run_vectors_btn = document.getElementById('run_vectors');
const vector_status = document.getElementById('vector_status');
const vector_output = document.getElementById('vector_output');
const vector_path = 'vectors/dm_smoke_v1.json';
const room_vector_path = 'vectors/room_seeded_bootstrap_v1.json';

const bytes_to_base64 = (bytes) => {
let binary = '';
for (const value of bytes) {
binary += String.fromCharCode(value);
}
return btoa(binary);
};

const base64_to_bytes = (payload_b64) => {
if (typeof payload_b64 !== 'string') {
return null;
}
if (payload_b64 === '') {
return new Uint8Array(0);
}
try {
const binary = atob(payload_b64);
const bytes = new Uint8Array(binary.length);
for (let index = 0; index < binary.length; index += 1) {
bytes[index] = binary.charCodeAt(index);
}
return bytes;
} catch (error) {
return null;
}
};

const pack_env_b64 = (kind_byte, payload_b64) => {
const payload_bytes = base64_to_bytes(payload_b64);
if (!payload_bytes) {
return '';
}
const env_bytes = new Uint8Array(payload_bytes.length + 1);
env_bytes[0] = kind_byte;
env_bytes.set(payload_bytes, 1);
return bytes_to_base64(env_bytes);
};

const unpack_env_b64 = (env_b64) => {
const env_bytes = base64_to_bytes(env_b64);
if (!env_bytes || env_bytes.length < 1) {
return null;
}
const kind_byte = env_bytes[0];
const payload_bytes = env_bytes.slice(1);
return { kind_byte, payload_b64: bytes_to_base64(payload_bytes) };
};

const read_room_vector = async () => {
const response = await fetch(room_vector_path);
if (!response.ok) {
throw new Error(`room vectors fetch failed: ${response.status}`);
}
return response.json();
};

const get_event_by_seq = (events, seq) => {
for (const event of events) {
if (event && event.seq === seq) {
return event;
}
}
return null;
};

const require_ok = (result, label) => {
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
throw new Error(`${label} failed: ${error_text}`);
}
return result;
};

const compare_env = (event, expected_env_b64, label) => {
if (!event || typeof event.env !== 'string') {
throw new Error(`${label} env missing`);
}
if (event.env !== expected_env_b64) {
throw new Error(`${label} env mismatch`);
}
};

const check_event_kind = (event, expected_kind, label) => {
if (!event || typeof event.env !== 'string') {
throw new Error(`${label} env missing`);
}
const unpacked = unpack_env_b64(event.env);
if (!unpacked) {
throw new Error(`${label} env invalid`);
}
if (unpacked.kind_byte !== expected_kind) {
throw new Error(`${label} env kind mismatch`);
}
return unpacked;
};

const run_room_replay = async () => {
const dm_create_participant = window.dmCreateParticipant;
const dm_join = window.dmJoin;
const dm_commit_apply = window.dmCommitApply;
const dm_decrypt = window.dmDecrypt;
const group_init = window.groupInit;
const group_add = window.groupAdd;
if (
typeof dm_create_participant !== 'function' ||
typeof dm_join !== 'function' ||
typeof dm_commit_apply !== 'function' ||
typeof dm_decrypt !== 'function' ||
typeof group_init !== 'function' ||
typeof group_add !== 'function'
) {
return { ok: false, error: 'wasm exports missing' };
}

let room_vector = null;
try {
room_vector = await read_room_vector();
} catch (error) {
return { ok: false, error: error.message };
}

if (!room_vector || !Array.isArray(room_vector.events)) {
return { ok: false, error: 'room vector missing events' };
}
const seeds = room_vector.seeds || {};
const group_id_b64 = room_vector.group_id_b64;
if (!group_id_b64 || typeof group_id_b64 !== 'string') {
return { ok: false, error: 'room vector missing group_id_b64' };
}
const owner = require_ok(
dm_create_participant('owner', seeds.owner_keypackage_seed),
'owner keypackage'
);
const peer_one = require_ok(
dm_create_participant('peer_one', seeds.peer_one_keypackage_seed),
'peer_one keypackage'
);
const peer_two = require_ok(
dm_create_participant('peer_two', seeds.peer_two_keypackage_seed),
'peer_two keypackage'
);

const init_result = require_ok(
group_init(
owner.participant_b64,
[peer_one.keypackage_b64, peer_two.keypackage_b64],
group_id_b64,
seeds.group_init_seed
),
'group init'
);

const init_welcome_env_b64 = pack_env_b64(1, init_result.welcome_b64);
const init_commit_env_b64 = pack_env_b64(2, init_result.commit_b64);
compare_env(get_event_by_seq(room_vector.events, 1), init_welcome_env_b64, 'init welcome');
compare_env(get_event_by_seq(room_vector.events, 2), init_commit_env_b64, 'init commit');

const peer_one_join = require_ok(
dm_join(peer_one.participant_b64, init_result.welcome_b64),
'peer_one join'
);
const peer_two_join = require_ok(
dm_join(peer_two.participant_b64, init_result.welcome_b64),
'peer_two join'
);

const owner_commit = require_ok(
dm_commit_apply(init_result.participant_b64, init_result.commit_b64),
'owner commit apply'
);
const peer_one_commit = require_ok(
dm_commit_apply(peer_one_join.participant_b64, init_result.commit_b64),
'peer_one commit apply'
);
const peer_two_commit = require_ok(
dm_commit_apply(peer_two_join.participant_b64, init_result.commit_b64),
'peer_two commit apply'
);

const app_event = check_event_kind(get_event_by_seq(room_vector.events, 3), 3, 'app');
const app_decrypt = require_ok(
dm_decrypt(owner_commit.participant_b64, app_event.payload_b64),
'app decrypt'
);
if (app_decrypt.plaintext !== room_vector.app_plaintext) {
return { ok: false, error: 'app plaintext mismatch' };
}

const peer_two_rotate = require_ok(
dm_create_participant(peer_two_commit.participant_b64, 'peer_two', seeds.peer_two_add_keypackage_seed),
'peer_two rotate'
);

const add_result = require_ok(
group_add(owner_commit.participant_b64, [peer_two_rotate.keypackage_b64], seeds.group_add_seed),
'group add'
);

const add_welcome_event = get_event_by_seq(room_vector.events, 4);
const add_commit_event = get_event_by_seq(room_vector.events, 5);
check_event_kind(add_welcome_event, 1, 'add welcome');
check_event_kind(add_commit_event, 2, 'add commit');
const add_welcome_env_b64 = pack_env_b64(1, add_result.welcome_b64);
const add_commit_env_b64 = pack_env_b64(2, add_result.commit_b64);
compare_env(add_welcome_event, add_welcome_env_b64, 'add welcome');
compare_env(add_commit_event, add_commit_env_b64, 'add commit');

return { ok: true };
};

const render_result = (result) => {
if (!result) {
vector_status.textContent = 'failed';
vector_output.textContent = 'error=empty result';
return;
}
if (result.ok) {
vector_status.textContent = 'ok';
vector_output.textContent = result.summary || `digest=${result.digest}`;
return;
}
const error_text = result.error || 'unknown error';
vector_status.textContent = 'failed';
vector_output.textContent = result.summary || `digest=${result.digest || ''} error=${error_text}`;
};

const handle_run_vectors = async () => {
vector_status.textContent = 'running...';
vector_output.textContent = '';
try {
const dm_result = await verify_vectors_from_url(vector_path);
const room_result = await run_room_replay();
const dm_status = dm_result && dm_result.ok ? 'ok' : 'failed';
const room_status = room_result && room_result.ok ? 'ok' : 'failed';
const summary_lines = [];
const digest_value = dm_result && dm_result.digest ? dm_result.digest : '';
summary_lines.push(`dm_smoke=${dm_status} digest=${digest_value}`);
if (dm_result && dm_result.error) {
summary_lines.push(`dm_smoke_error=${dm_result.error}`);
}
summary_lines.push(`room_replay=${room_status}`);
if (room_result && room_result.error) {
summary_lines.push(`room_replay_error=${room_result.error}`);
}
const combined_ok = Boolean(dm_result && dm_result.ok && room_result && room_result.ok);
render_result({
ok: combined_ok,
digest: digest_value,
summary: summary_lines.join(' ')
});
} catch (err) {
vector_status.textContent = 'failed';
const message = err && err.message ? err.message : String(err);
vector_output.textContent = `error=${message}`;
}
};

if (run_vectors_btn) {
run_vectors_btn.addEventListener('click', handle_run_vectors);
}
