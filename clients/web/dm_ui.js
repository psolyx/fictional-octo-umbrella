import {
dm_commit_apply,
dm_create_participant,
dm_decrypt,
dm_encrypt,
dm_init,
dm_join,
} from './mls_vectors_loader.js';

const dm_status = document.getElementById('dm_status');
const dm_output = document.getElementById('dm_output');
const group_id_input = document.getElementById('dm_group_id');
const alice_plaintext_input = document.getElementById('dm_alice_plaintext');
const bob_plaintext_input = document.getElementById('dm_bob_plaintext');
const ciphertext_output = document.getElementById('dm_ciphertext');
const decrypted_output = document.getElementById('dm_decrypted');

const create_alice_btn = document.getElementById('dm_create_alice');
const create_bob_btn = document.getElementById('dm_create_bob');
const init_btn = document.getElementById('dm_init');
const join_btn = document.getElementById('dm_join');
const commit_apply_btn = document.getElementById('dm_commit_apply');
const encrypt_alice_btn = document.getElementById('dm_encrypt_alice');
const encrypt_bob_btn = document.getElementById('dm_encrypt_bob');
const save_state_btn = document.getElementById('dm_save_state');
const load_state_btn = document.getElementById('dm_load_state');
const reset_state_btn = document.getElementById('dm_reset_state');

let alice_participant_b64 = '';
let bob_participant_b64 = '';
let alice_keypackage_b64 = '';
let bob_keypackage_b64 = '';
let group_id_b64 = '';
let welcome_b64 = '';
let commit_b64 = '';
let expected_plaintext = '';
let parsed_welcome_env_b64 = '';
let parsed_commit_env_b64 = '';
let parsed_app_env_b64 = '';
let outbox_welcome_env_b64 = '';
let outbox_commit_env_b64 = '';
let outbox_app_env_b64 = '';
let last_local_commit_env_b64 = '';
let commit_echo_state = 'idle';
let commit_echo_seq = null;
let commit_echo_status_line = null;
let transcript_file_input = null;
let transcript_textarea = null;
let transcript_status_line = null;
let outbox_welcome_textarea = null;
let outbox_commit_textarea = null;
let outbox_app_textarea = null;
let outbox_copy_btn = null;
let live_inbox_by_seq = new Map();
let live_inbox_expected_seq = 1;
let live_inbox_last_ingested_seq = null;
let live_inbox_enabled_input = null;
let live_inbox_auto_input = null;
let live_inbox_expected_input = null;
let live_inbox_ingest_btn = null;
let live_inbox_status_line = null;
let dm_conv_status_line = null;
let active_conv_id = '(none)';
const conv_state_by_id = new Map();

const seed_alice = 1001;
const seed_bob = 2002;
const seed_init = 3003;

const db_name = 'mls_dm_state';
const store_name = 'records';
const sealed_state_key = 'sealed_state_v1';
const pbkdf2_iterations = 200000;
const pbkdf2_salt_len = 16;
const aes_gcm_iv_len = 12;
const legacy_state_keys = [
'alice',
'bob',
'alice_keypackage',
'bob_keypackage',
'group_id',
'welcome',
'commit',
'expected_plaintext',
'parsed_app_env_b64',
];
const cli_block_keys = [
'welcome_env_b64',
'commit_env_b64',
'app_env_b64',
'expected_plaintext',
];

const normalize_conv_id = (value) => {
if (typeof value !== 'string') {
return '(none)';
}
const trimmed = value.trim();
return trimmed ? trimmed : '(none)';
};

const build_conv_state = () => ({
inbox_by_seq: new Map(),
expected_seq: 1,
last_ingested_seq: null,
outbox_welcome_env_b64: '',
outbox_commit_env_b64: '',
outbox_app_env_b64: '',
last_local_commit_env_b64: '',
commit_echo_status: 'idle',
echoed_seq: null,
staged_incoming_env_b64: '',
expected_plaintext: '',
parsed_welcome_env_b64: '',
parsed_commit_env_b64: '',
parsed_app_env_b64: '',
live_inbox_enabled: false,
live_inbox_auto: false,
});

const get_conv_state = (conv_id) => {
const normalized = normalize_conv_id(conv_id);
if (!conv_state_by_id.has(normalized)) {
conv_state_by_id.set(normalized, build_conv_state());
}
return conv_state_by_id.get(normalized);
};

const update_conv_status_label = () => {
if (!dm_conv_status_line) {
return;
}
dm_conv_status_line.textContent = `DM UI bound to conv_id: ${active_conv_id}`;
};

const set_status = (message) => {
if (dm_status) {
dm_status.textContent = message;
}
};

const set_transcript_status = (message) => {
if (transcript_status_line) {
transcript_status_line.textContent = message;
}
};

const set_storage_status = (message) => {
if (storage_status_line) {
storage_status_line.textContent = message;
}
};

const update_commit_echo_status_line = () => {
if (!commit_echo_status_line) {
return;
}
if (commit_echo_state === 'waiting') {
commit_echo_status_line.textContent =
'commit echo: waiting (send commit to gateway, then wait for conv.event)';
return;
}
if (commit_echo_state === 'received') {
const suffix = commit_echo_seq === null ? '' : ` (seq=${commit_echo_seq})`;
commit_echo_status_line.textContent = `commit echo: received${suffix}`;
return;
}
commit_echo_status_line.textContent = 'commit echo: idle';
};

const update_commit_apply_state = () => {
if (!commit_apply_btn) {
return;
}
const has_commit = Boolean(commit_b64);
if (!has_commit) {
commit_apply_btn.disabled = true;
return;
}
if (commit_echo_state === 'waiting') {
commit_apply_btn.disabled = true;
return;
}
commit_apply_btn.disabled = false;
};

const set_commit_echo_state = (state, seq) => {
commit_echo_state = state;
commit_echo_seq = typeof seq === 'number' ? seq : null;
update_commit_echo_status_line();
update_commit_apply_state();
};

const save_active_conv_state = () => {
const state = get_conv_state(active_conv_id);
state.inbox_by_seq = new Map(live_inbox_by_seq);
state.expected_seq = live_inbox_expected_seq;
state.last_ingested_seq = live_inbox_last_ingested_seq;
state.outbox_welcome_env_b64 = outbox_welcome_env_b64 || '';
state.outbox_commit_env_b64 = outbox_commit_env_b64 || '';
state.outbox_app_env_b64 = outbox_app_env_b64 || '';
state.last_local_commit_env_b64 = last_local_commit_env_b64 || '';
state.commit_echo_status = commit_echo_state;
state.echoed_seq = commit_echo_seq;
state.staged_incoming_env_b64 = incoming_env_input ? incoming_env_input.value.trim() : '';
state.expected_plaintext = expected_plaintext_input ? expected_plaintext_input.value : expected_plaintext;
state.parsed_welcome_env_b64 = parsed_welcome_env_b64 || '';
state.parsed_commit_env_b64 = parsed_commit_env_b64 || '';
state.parsed_app_env_b64 = parsed_app_env_b64 || '';
state.live_inbox_enabled = Boolean(live_inbox_enabled_input && live_inbox_enabled_input.checked);
state.live_inbox_auto = Boolean(live_inbox_auto_input && live_inbox_auto_input.checked);
};

const apply_conv_state = (state) => {
const normalized_state = state || build_conv_state();
live_inbox_by_seq = new Map(normalized_state.inbox_by_seq || []);
live_inbox_last_ingested_seq =
Number.isInteger(normalized_state.last_ingested_seq) ? normalized_state.last_ingested_seq : null;
set_live_inbox_expected_seq(normalized_state.expected_seq);
if (live_inbox_enabled_input) {
live_inbox_enabled_input.checked = Boolean(normalized_state.live_inbox_enabled);
}
if (live_inbox_auto_input) {
live_inbox_auto_input.checked = Boolean(normalized_state.live_inbox_auto);
}
update_live_inbox_controls();
update_live_inbox_status();
set_outbox_envs({
welcome_env_b64: normalized_state.outbox_welcome_env_b64 || '',
commit_env_b64: normalized_state.outbox_commit_env_b64 || '',
app_env_b64: normalized_state.outbox_app_env_b64 || '',
});
last_local_commit_env_b64 = normalized_state.last_local_commit_env_b64 || '';
set_commit_echo_state(normalized_state.commit_echo_status || 'idle', normalized_state.echoed_seq);
parsed_welcome_env_b64 = normalize_state_value(normalized_state.parsed_welcome_env_b64);
parsed_commit_env_b64 = normalize_state_value(normalized_state.parsed_commit_env_b64);
parsed_app_env_b64 = normalize_state_value(normalized_state.parsed_app_env_b64);
expected_plaintext = normalize_state_value(normalized_state.expected_plaintext);
set_expected_plaintext_input();
set_incoming_env_input(normalized_state.staged_incoming_env_b64 || '');
};

const get_live_inbox_enabled = () =>
Boolean(live_inbox_enabled_input && live_inbox_enabled_input.checked);

const normalize_live_inbox_expected_seq = (value) => {
const parsed = Number.parseInt(value, 10);
if (!Number.isInteger(parsed) || parsed < 1) {
return 1;
}
return parsed;
};

const set_live_inbox_expected_seq = (value) => {
live_inbox_expected_seq = normalize_live_inbox_expected_seq(value);
if (live_inbox_expected_input) {
live_inbox_expected_input.value = String(live_inbox_expected_seq);
}
update_live_inbox_status();
};

const update_live_inbox_status = (note) => {
if (!live_inbox_status_line) {
return;
}
const queued_count = live_inbox_by_seq.size;
const last_seq_text =
live_inbox_last_ingested_seq === null ? 'none' : String(live_inbox_last_ingested_seq);
const parts = [
`queued=${queued_count}`,
`expected_seq=${live_inbox_expected_seq}`,
`last_ingested_seq=${last_seq_text}`,
];
if (note) {
parts.push(note);
}
live_inbox_status_line.textContent = parts.join(' | ');
};

const log_output = (message) => {
if (!dm_output) {
return;
}
dm_output.textContent = message;
};

const update_outbox_ui = () => {
if (outbox_welcome_textarea) {
outbox_welcome_textarea.value = outbox_welcome_env_b64;
}
if (outbox_commit_textarea) {
outbox_commit_textarea.value = outbox_commit_env_b64;
}
if (outbox_app_textarea) {
outbox_app_textarea.value = outbox_app_env_b64;
}
};

const dispatch_outbox_update = () => {
window.dispatchEvent(
new CustomEvent('dm.outbox.updated', {
detail: {
welcome_env_b64: outbox_welcome_env_b64 || '',
commit_env_b64: outbox_commit_env_b64 || '',
app_env_b64: outbox_app_env_b64 || '',
},
})
);
};

const set_outbox_envs = (updates) => {
let updated = false;
if (Object.prototype.hasOwnProperty.call(updates, 'welcome_env_b64')) {
const next_value = updates.welcome_env_b64 || '';
if (next_value !== outbox_welcome_env_b64) {
outbox_welcome_env_b64 = next_value;
updated = true;
}
}
if (Object.prototype.hasOwnProperty.call(updates, 'commit_env_b64')) {
const next_value = updates.commit_env_b64 || '';
if (next_value !== outbox_commit_env_b64) {
outbox_commit_env_b64 = next_value;
updated = true;
}
}
if (Object.prototype.hasOwnProperty.call(updates, 'app_env_b64')) {
const next_value = updates.app_env_b64 || '';
if (next_value !== outbox_app_env_b64) {
outbox_app_env_b64 = next_value;
updated = true;
}
}
if (updated) {
update_outbox_ui();
dispatch_outbox_update();
}
};

const build_outbox_block = () => {
const lines = [];
if (outbox_welcome_env_b64) {
lines.push(`welcome_env_b64=${outbox_welcome_env_b64}`);
}
if (outbox_commit_env_b64) {
lines.push(`commit_env_b64=${outbox_commit_env_b64}`);
}
if (outbox_app_env_b64) {
lines.push(`app_env_b64=${outbox_app_env_b64}`);
}
return lines.join('\n');
};

const copy_outbox_block = async () => {
const block_text = build_outbox_block();
if (!block_text) {
set_status('error');
log_output('outbox empty');
return;
}
if (!navigator.clipboard || !navigator.clipboard.writeText) {
set_status('error');
log_output('clipboard unavailable');
return;
}
try {
await navigator.clipboard.writeText(block_text);
set_status('outbox copied');
log_output('outbox copied to clipboard');
} catch (error) {
set_status('error');
log_output('outbox copy failed');
}
};

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

const pack_dm_env = (kind_byte, payload_b64) => {
const payload_bytes = base64_to_bytes(payload_b64);
if (!payload_bytes) {
return '';
}
const env_bytes = new Uint8Array(payload_bytes.length + 1);
env_bytes[0] = kind_byte;
env_bytes.set(payload_bytes, 1);
return bytes_to_base64(env_bytes);
};

const unpack_dm_env = (env_b64) => {
const env_bytes = base64_to_bytes(env_b64);
if (!env_bytes || env_bytes.length < 1) {
set_status('error');
log_output('invalid env base64');
return null;
}
const kind = env_bytes[0];
if (kind !== 1 && kind !== 2 && kind !== 3) {
set_status('error');
log_output(`invalid env kind: ${kind}`);
return null;
}
const payload_bytes = env_bytes.slice(1);
const payload_b64 = bytes_to_base64(payload_bytes);
return { kind, payload_b64 };
};

const generate_group_id = () => {
const bytes = new Uint8Array(32);
crypto.getRandomValues(bytes);
return bytes_to_base64(bytes);
};

const open_db = () => new Promise((resolve, reject) => {
const request = indexedDB.open(db_name, 1);
request.onupgradeneeded = (event) => {
const db = event.target.result;
if (!db.objectStoreNames.contains(store_name)) {
db.createObjectStore(store_name);
}
};
request.onsuccess = () => resolve(request.result);
request.onerror = () => reject(request.error);
});

const db_get = async (key) => {
const db = await open_db();
return new Promise((resolve, reject) => {
const tx = db.transaction(store_name, 'readonly');
const store = tx.objectStore(store_name);
const request = store.get(key);
request.onsuccess = () => resolve(request.result || '');
request.onerror = () => reject(request.error);
});
};

const db_set = async (key, value) => {
const db = await open_db();
return new Promise((resolve, reject) => {
const tx = db.transaction(store_name, 'readwrite');
const store = tx.objectStore(store_name);
const request = store.put(value, key);
request.onsuccess = () => resolve();
request.onerror = () => reject(request.error);
});
};

const db_delete = async (key) => {
const db = await open_db();
return new Promise((resolve, reject) => {
const tx = db.transaction(store_name, 'readwrite');
const store = tx.objectStore(store_name);
const request = store.delete(key);
request.onsuccess = () => resolve();
request.onerror = () => reject(request.error);
});
};

const db_clear = async () => {
const db = await open_db();
return new Promise((resolve, reject) => {
const tx = db.transaction(store_name, 'readwrite');
const store = tx.objectStore(store_name);
const request = store.clear();
request.onsuccess = () => resolve();
request.onerror = () => reject(request.error);
});
};

const get_passphrase = () => (storage_passphrase_input ? storage_passphrase_input.value : '');

const update_encrypt_checkbox_default = () => {
if (!storage_encrypt_checkbox || !storage_passphrase_input) {
return;
}
const passphrase = storage_passphrase_input.value;
if (!passphrase) {
storage_encrypt_checkbox.checked = false;
encrypt_checkbox_touched = false;
return;
}
if (!encrypt_checkbox_touched) {
storage_encrypt_checkbox.checked = true;
}
};

const normalize_state_value = (value) => (typeof value === 'string' ? value : '');

const build_state_snapshot = () => {
expected_plaintext = expected_plaintext_input ? expected_plaintext_input.value : expected_plaintext;
const state = {
alice: alice_participant_b64,
bob: bob_participant_b64,
alice_keypackage: alice_keypackage_b64,
bob_keypackage: bob_keypackage_b64,
group_id: group_id_b64,
welcome: welcome_b64,
commit: commit_b64,
expected_plaintext,
parsed_app_env_b64,
};
if (parsed_welcome_env_b64) {
state.parsed_welcome_env_b64 = parsed_welcome_env_b64;
}
if (parsed_commit_env_b64) {
state.parsed_commit_env_b64 = parsed_commit_env_b64;
}
return state;
};

const apply_state_snapshot = (state) => {
alice_participant_b64 = normalize_state_value(state.alice);
bob_participant_b64 = normalize_state_value(state.bob);
alice_keypackage_b64 = normalize_state_value(state.alice_keypackage);
bob_keypackage_b64 = normalize_state_value(state.bob_keypackage);
group_id_b64 = normalize_state_value(state.group_id);
welcome_b64 = normalize_state_value(state.welcome);
commit_b64 = normalize_state_value(state.commit);
expected_plaintext = normalize_state_value(state.expected_plaintext);
parsed_app_env_b64 = normalize_state_value(state.parsed_app_env_b64);
parsed_welcome_env_b64 = normalize_state_value(state.parsed_welcome_env_b64);
parsed_commit_env_b64 = normalize_state_value(state.parsed_commit_env_b64);
set_group_id_input();
set_expected_plaintext_input();
if (incoming_env_input && parsed_app_env_b64 && !incoming_env_input.value.trim()) {
incoming_env_input.value = parsed_app_env_b64;
}
update_commit_apply_state();
};

const derive_storage_key = async (passphrase, salt_bytes) => {
const encoder = new TextEncoder();
const passphrase_bytes = encoder.encode(passphrase);
const key_material = await crypto.subtle.importKey('raw', passphrase_bytes, 'PBKDF2', false, ['deriveKey']);
return crypto.subtle.deriveKey(
{
name: 'PBKDF2',
salt: salt_bytes,
iterations: pbkdf2_iterations,
hash: 'SHA-256',
},
key_material,
{ name: 'AES-GCM', length: 256 },
false,
['encrypt', 'decrypt'],
);
};

const seal_state = async (state, passphrase) => {
const encoder = new TextEncoder();
const payload_bytes = encoder.encode(JSON.stringify(state));
const salt_bytes = new Uint8Array(pbkdf2_salt_len);
const iv_bytes = new Uint8Array(aes_gcm_iv_len);
crypto.getRandomValues(salt_bytes);
crypto.getRandomValues(iv_bytes);
const key = await derive_storage_key(passphrase, salt_bytes);
const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv_bytes }, key, payload_bytes);
const ct_bytes = new Uint8Array(ciphertext);
return {
v: 1,
salt_b64: bytes_to_base64(salt_bytes),
iv_b64: bytes_to_base64(iv_bytes),
ct_b64: bytes_to_base64(ct_bytes),
};
};

const decode_sealed_state = (sealed_state) => {
if (!sealed_state || typeof sealed_state !== 'object') {
return { ok: false, error: 'sealed state missing' };
}
if (sealed_state.v !== 1) {
return { ok: false, error: 'sealed state version unsupported' };
}
const salt_bytes = base64_to_bytes(sealed_state.salt_b64);
if (!salt_bytes || salt_bytes.length !== pbkdf2_salt_len) {
return { ok: false, error: 'sealed state salt invalid' };
}
const iv_bytes = base64_to_bytes(sealed_state.iv_b64);
if (!iv_bytes || iv_bytes.length !== aes_gcm_iv_len) {
return { ok: false, error: 'sealed state iv invalid' };
}
const ct_bytes = base64_to_bytes(sealed_state.ct_b64);
if (!ct_bytes || ct_bytes.length < 1) {
return { ok: false, error: 'sealed state ciphertext invalid' };
}
return { ok: true, salt_bytes, iv_bytes, ct_bytes };
};

const unseal_state = async (sealed_state, passphrase) => {
const decoded = decode_sealed_state(sealed_state);
if (!decoded.ok) {
return decoded;
}
let plaintext_bytes = null;
try {
const key = await derive_storage_key(passphrase, decoded.salt_bytes);
const plaintext = await crypto.subtle.decrypt(
{ name: 'AES-GCM', iv: decoded.iv_bytes },
key,
decoded.ct_bytes,
);
plaintext_bytes = new Uint8Array(plaintext);
} catch (error) {
return { ok: false, error: 'passphrase incorrect or data corrupted' };
}
let parsed = null;
try {
const decoder = new TextDecoder();
const payload_text = decoder.decode(plaintext_bytes);
parsed = JSON.parse(payload_text);
} catch (error) {
return { ok: false, error: 'sealed state json invalid' };
}
if (!parsed || typeof parsed !== 'object') {
return { ok: false, error: 'sealed state payload invalid' };
}
return { ok: true, state: parsed };
};

const load_legacy_state = async () => {
alice_participant_b64 = await db_get('alice');
bob_participant_b64 = await db_get('bob');
alice_keypackage_b64 = await db_get('alice_keypackage');
bob_keypackage_b64 = await db_get('bob_keypackage');
group_id_b64 = await db_get('group_id');
welcome_b64 = await db_get('welcome');
commit_b64 = await db_get('commit');
expected_plaintext = await db_get('expected_plaintext');
parsed_app_env_b64 = await db_get('parsed_app_env_b64');
parsed_welcome_env_b64 = '';
parsed_commit_env_b64 = '';
set_group_id_input();
set_expected_plaintext_input();
if (incoming_env_input && parsed_app_env_b64 && !incoming_env_input.value.trim()) {
incoming_env_input.value = parsed_app_env_b64;
}
update_commit_apply_state();
};

const set_group_id_input = () => {
if (group_id_input) {
group_id_input.value = group_id_b64 || '';
}
};

const set_ciphertext_output = (ciphertext) => {
if (ciphertext_output) {
ciphertext_output.value = ciphertext || '';
}
};

const set_decrypted_output = (plaintext) => {
if (decrypted_output) {
decrypted_output.value = plaintext || '';
}
};

const set_expected_plaintext_input = () => {
if (expected_plaintext_input) {
expected_plaintext_input.value = expected_plaintext || '';
}
};

const set_incoming_env_input = (payload_b64) => {
if (incoming_env_input) {
incoming_env_input.value = payload_b64 || '';
}
};

const save_state = async () => {
const passphrase = get_passphrase();
const encrypt_enabled = storage_encrypt_checkbox ? storage_encrypt_checkbox.checked : false;
if (encrypt_enabled) {
if (!passphrase) {
set_status('error');
set_storage_status('passphrase required to encrypt state');
log_output('passphrase required to encrypt state');
return { ok: false };
}
const snapshot = build_state_snapshot();
const sealed_state = await seal_state(snapshot, passphrase);
await db_set(sealed_state_key, sealed_state);
for (const key of legacy_state_keys) {
await db_delete(key);
}
set_storage_status('saved encrypted state (legacy cleared)');
return { ok: true, mode: 'encrypted' };
}
const entries = [
['alice', alice_participant_b64],
['bob', bob_participant_b64],
['alice_keypackage', alice_keypackage_b64],
['bob_keypackage', bob_keypackage_b64],
['group_id', group_id_b64],
['welcome', welcome_b64],
['commit', commit_b64],
['expected_plaintext', expected_plaintext_input ? expected_plaintext_input.value : expected_plaintext],
['parsed_app_env_b64', parsed_app_env_b64],
];
for (const [key, value] of entries) {
if (value) {
await db_set(key, value);
} else {
await db_delete(key);
}
}
await db_delete(sealed_state_key);
set_storage_status('saved legacy plaintext state');
return { ok: true, mode: 'legacy' };
};

const load_state = async () => {
const sealed_state = await db_get(sealed_state_key);
if (sealed_state) {
const passphrase = get_passphrase();
if (!passphrase) {
set_status('error');
set_storage_status('passphrase required to load encrypted state');
log_output('passphrase required to load encrypted state');
return;
}
const unsealed = await unseal_state(sealed_state, passphrase);
if (!unsealed.ok) {
set_status('error');
set_storage_status(`decrypt failed: ${unsealed.error}`);
log_output(`decrypt failed: ${unsealed.error}`);
return;
}
apply_state_snapshot(unsealed.state);
set_status('loaded');
set_storage_status('loaded encrypted state');
log_output('loaded encrypted state from IndexedDB');
return;
}
await load_legacy_state();
set_status('loaded');
set_storage_status('loaded legacy plaintext state');
log_output('loaded legacy plaintext state from IndexedDB');
};

const reset_state = async () => {
alice_participant_b64 = '';
bob_participant_b64 = '';
alice_keypackage_b64 = '';
bob_keypackage_b64 = '';
group_id_b64 = '';
welcome_b64 = '';
commit_b64 = '';
expected_plaintext = '';
parsed_welcome_env_b64 = '';
parsed_commit_env_b64 = '';
parsed_app_env_b64 = '';
set_outbox_envs({ welcome_env_b64: '', commit_env_b64: '', app_env_b64: '' });
last_local_commit_env_b64 = '';
set_commit_echo_state('idle', null);
live_inbox_by_seq = new Map();
live_inbox_last_ingested_seq = null;
set_live_inbox_expected_seq(1);
set_group_id_input();
set_ciphertext_output('');
set_decrypted_output('');
set_expected_plaintext_input();
set_incoming_env_input('');
await db_clear();
set_storage_status('cleared stored state');
set_status('reset');
log_output('cleared local state');
};

const handle_create_alice = async () => {
set_status('creating alice...');
log_output('');
const result = await dm_create_participant('alice', seed_alice);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_status('error');
log_output(`create alice failed: ${error_text}`);
return;
}
alice_participant_b64 = result.participant_b64;
alice_keypackage_b64 = result.keypackage_b64;
set_status('alice ready');
log_output('alice participant created');
};

const handle_create_bob = async () => {
set_status('creating bob...');
log_output('');
const result = await dm_create_participant('bob', seed_bob);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_status('error');
log_output(`create bob failed: ${error_text}`);
return;
}
bob_participant_b64 = result.participant_b64;
bob_keypackage_b64 = result.keypackage_b64;
set_status('bob ready');
log_output('bob participant created');
};

const handle_init = async () => {
if (!alice_participant_b64 || !bob_keypackage_b64) {
set_status('error');
log_output('need alice participant and bob keypackage');
return;
}
if (!group_id_b64) {
group_id_b64 = generate_group_id();
set_group_id_input();
}
set_status('init...');
log_output('');
const result = await dm_init(alice_participant_b64, bob_keypackage_b64, group_id_b64, seed_init);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_status('error');
log_output(`init failed: ${error_text}`);
return;
}
alice_participant_b64 = result.participant_b64;
welcome_b64 = result.welcome_b64;
commit_b64 = result.commit_b64;
set_status('init ok');
const welcome_env_b64 = pack_dm_env(1, welcome_b64);
const commit_env_b64 = pack_dm_env(2, commit_b64);
set_outbox_envs({ welcome_env_b64, commit_env_b64 });
last_local_commit_env_b64 = commit_env_b64;
set_commit_echo_state('waiting', null);
log_output(`welcome_env_b64: ${welcome_env_b64}\ncommit_env_b64: ${commit_env_b64}`);
};

const handle_join = async () => {
if (!bob_participant_b64 || !welcome_b64) {
set_status('error');
log_output('need bob participant and welcome');
return;
}
set_status('joining...');
log_output('');
const result = await dm_join(bob_participant_b64, welcome_b64);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_status('error');
log_output(`join failed: ${error_text}`);
return;
}
bob_participant_b64 = result.participant_b64;
set_status('bob joined');
log_output('bob applied welcome');
};

const handle_commit_apply = async () => {
if (!alice_participant_b64 || !commit_b64) {
set_status('error');
log_output('need alice participant and commit');
return;
}
set_status('applying commit...');
log_output('');
const result = await dm_commit_apply(alice_participant_b64, commit_b64);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_status('error');
log_output(`commit apply failed: ${error_text}`);
return;
}
alice_participant_b64 = result.participant_b64;
const suffix = result.noop ? ' (noop)' : '';
set_status(`commit applied${suffix}`);
log_output(`alice commit applied${suffix}`);
};

const handle_import_welcome_env = () => {
const env_b64 = incoming_env_input ? incoming_env_input.value.trim() : '';
const unpacked = unpack_dm_env(env_b64);
if (!unpacked) {
return;
}
if (unpacked.kind !== 1) {
set_status('error');
log_output('expected welcome env (kind=1)');
return;
}
welcome_b64 = unpacked.payload_b64;
set_status('welcome loaded');
log_output('welcome env loaded from gateway/cli');
};

const handle_import_commit_env = () => {
const env_b64 = incoming_env_input ? incoming_env_input.value.trim() : '';
const unpacked = unpack_dm_env(env_b64);
if (!unpacked) {
return;
}
if (unpacked.kind !== 2) {
set_status('error');
log_output('expected commit env (kind=2)');
return;
}
commit_b64 = unpacked.payload_b64;
last_local_commit_env_b64 = '';
set_commit_echo_state('idle', null);
set_status('commit loaded');
log_output('commit env loaded; pending apply');
};

const parse_live_inbox_env = (env_b64) => {
const env_bytes = base64_to_bytes(env_b64);
if (!env_bytes || env_bytes.length < 1) {
return null;
}
const kind = env_bytes[0];
if (kind !== 1 && kind !== 2 && kind !== 3) {
return null;
}
return { kind };
};

const update_live_inbox_controls = () => {
const enabled = get_live_inbox_enabled();
if (live_inbox_ingest_btn) {
live_inbox_ingest_btn.disabled = !enabled;
}
if (live_inbox_auto_input) {
live_inbox_auto_input.disabled = !enabled;
}
};

const ingest_live_inbox_seq = (seq) => {
if (!get_live_inbox_enabled()) {
update_live_inbox_status('live inbox disabled');
return false;
}
if (!live_inbox_by_seq.has(seq)) {
update_live_inbox_status(`missing seq=${seq}`);
return false;
}
const env_b64 = live_inbox_by_seq.get(seq);
const env_meta = parse_live_inbox_env(env_b64);
if (!env_meta) {
update_live_inbox_status(`invalid env at seq=${seq}`);
return false;
}
set_incoming_env_input(env_b64);
if (env_meta.kind === 1) {
handle_import_welcome_env();
} else if (env_meta.kind === 2) {
if (env_b64 === last_local_commit_env_b64 && last_local_commit_env_b64) {
set_commit_echo_state('received', seq);
set_status(`commit echo received (seq=${seq})`);
log_output(`commit echo received at seq=${seq}`);
} else {
handle_import_commit_env();
}
} else {
set_status(`app env staged (seq=${seq})`);
log_output(`app env staged from inbox (seq=${seq})`);
}
live_inbox_by_seq.delete(seq);
live_inbox_last_ingested_seq = seq;
set_live_inbox_expected_seq(seq + 1);
update_live_inbox_status();
return true;
};

const run_live_inbox_auto_ingest = () => {
if (!get_live_inbox_enabled()) {
return;
}
if (!live_inbox_auto_input || !live_inbox_auto_input.checked) {
return;
}
let steps = 0;
while (steps < 50) {
const seq = live_inbox_expected_seq;
if (!live_inbox_by_seq.has(seq)) {
break;
}
const ok = ingest_live_inbox_seq(seq);
if (!ok) {
break;
}
steps += 1;
}
if (steps >= 50) {
update_live_inbox_status('auto-ingest cap reached');
}
};

const handle_decrypt_app_env = async (participant_label) => {
const env_b64 = incoming_env_input ? incoming_env_input.value.trim() : '';
const unpacked = unpack_dm_env(env_b64);
if (!unpacked) {
return;
}
if (unpacked.kind !== 3) {
set_status('error');
log_output('expected app env (kind=3)');
return;
}
if (participant_label === 'bob' && !bob_participant_b64) {
set_status('error');
log_output('need bob participant');
return;
}
if (participant_label === 'alice' && !alice_participant_b64) {
set_status('error');
log_output('need alice participant');
return;
}
set_status(`decrypting as ${participant_label}...`);
log_output('');
const participant_b64 = participant_label === 'bob' ? bob_participant_b64 : alice_participant_b64;
const dec_result = await dm_decrypt(participant_b64, unpacked.payload_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
set_status('error');
log_output(`decrypt failed: ${error_text}`);
return;
}
if (participant_label === 'bob') {
bob_participant_b64 = dec_result.participant_b64;
} else {
alice_participant_b64 = dec_result.participant_b64;
}
set_ciphertext_output(unpacked.payload_b64);
set_decrypted_output(dec_result.plaintext);
set_status(`app env decrypted as ${participant_label}`);
log_output(`app env decrypted as ${participant_label}`);
};

const handle_encrypt_alice = async () => {
if (!alice_participant_b64 || !bob_participant_b64) {
set_status('error');
log_output('need alice + bob participants');
return;
}
const plaintext = alice_plaintext_input ? alice_plaintext_input.value : '';
set_status('encrypting...');
log_output('');
const enc_result = await dm_encrypt(alice_participant_b64, plaintext);
if (!enc_result || !enc_result.ok) {
const error_text = enc_result && enc_result.error ? enc_result.error : 'unknown error';
set_status('error');
log_output(`encrypt failed: ${error_text}`);
return;
}
alice_participant_b64 = enc_result.participant_b64;
set_ciphertext_output(enc_result.ciphertext_b64);
const app_env_b64 = pack_dm_env(3, enc_result.ciphertext_b64);
set_outbox_envs({ app_env_b64 });
const dec_result = await dm_decrypt(bob_participant_b64, enc_result.ciphertext_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
set_status('error');
log_output(`decrypt failed: ${error_text}`);
return;
}
bob_participant_b64 = dec_result.participant_b64;
set_decrypted_output(dec_result.plaintext);
set_status('alice -> bob ok');
log_output(`app_env_b64: ${app_env_b64}`);
};

const handle_encrypt_bob = async () => {
if (!alice_participant_b64 || !bob_participant_b64) {
set_status('error');
log_output('need alice + bob participants');
return;
}
const plaintext = bob_plaintext_input ? bob_plaintext_input.value : '';
set_status('encrypting...');
log_output('');
const enc_result = await dm_encrypt(bob_participant_b64, plaintext);
if (!enc_result || !enc_result.ok) {
const error_text = enc_result && enc_result.error ? enc_result.error : 'unknown error';
set_status('error');
log_output(`encrypt failed: ${error_text}`);
return;
}
bob_participant_b64 = enc_result.participant_b64;
set_ciphertext_output(enc_result.ciphertext_b64);
const app_env_b64 = pack_dm_env(3, enc_result.ciphertext_b64);
set_outbox_envs({ app_env_b64 });
const dec_result = await dm_decrypt(alice_participant_b64, enc_result.ciphertext_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
set_status('error');
log_output(`decrypt failed: ${error_text}`);
return;
}
alice_participant_b64 = dec_result.participant_b64;
set_decrypted_output(dec_result.plaintext);
set_status('bob -> alice ok');
log_output(`app_env_b64: ${app_env_b64}`);
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

const truncate_text = (value, max_len) => {
if (value.length <= max_len) {
return value;
}
return `${value.slice(0, max_len)}…`;
};

const bytes_to_base64url = (bytes) => {
const base64 = bytes_to_base64(bytes);
return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
};

const normalize_msg_id = (value) => {
if (value === null || value === undefined) {
return null;
}
return String(value);
};

const canonicalize_transcript = (transcript) => {
const events_sorted = [...transcript.events].sort((left, right) => left.seq - right.seq);
const canonical_events = events_sorted.map((event) => ({
seq: event.seq,
msg_id: normalize_msg_id(event.msg_id),
env: event.env,
}));
return {
schema_version: transcript.schema_version,
conv_id: transcript.conv_id,
from_seq: transcript.from_seq,
next_seq: transcript.next_seq,
events: canonical_events,
};
};

const compute_transcript_digest = async (transcript) => {
const canonical = canonicalize_transcript(transcript);
const payload = JSON.stringify(canonical);
const text_encoder = new TextEncoder();
const payload_bytes = text_encoder.encode(payload);
const digest_bytes = await crypto.subtle.digest('SHA-256', payload_bytes);
return bytes_to_base64url(new Uint8Array(digest_bytes));
};

const parse_transcript_json = (payload_text) => {
if (!payload_text || !payload_text.trim()) {
return { ok: false, error: 'transcript input is empty' };
}
try {
const parsed = JSON.parse(payload_text);
return { ok: true, transcript: parsed };
} catch (error) {
return { ok: false, error: 'invalid transcript json' };
}
};

const validate_transcript = (transcript) => {
if (!transcript || typeof transcript !== 'object') {
return { ok: false, error: 'transcript must be an object' };
}
const conv_id = typeof transcript.conv_id === 'string' ? transcript.conv_id : '';
if (!conv_id) {
return { ok: false, error: 'conv_id must be a string' };
}
const events = Array.isArray(transcript.events) ? transcript.events : null;
if (!events) {
return { ok: false, error: 'events must be an array' };
}
const seen_seq = new Set();
for (const event of events) {
const seq = event ? event.seq : null;
if (!Number.isInteger(seq) || seq < 1) {
return { ok: false, error: 'event seq must be int >= 1' };
}
if (seen_seq.has(seq)) {
return { ok: false, error: `duplicate seq: ${seq}` };
}
seen_seq.add(seq);
if (!event || typeof event.env !== 'string') {
return { ok: false, error: `event env missing for seq ${seq}` };
}
}
return {
ok: true,
transcript: {
schema_version: transcript.schema_version,
conv_id: transcript.conv_id,
from_seq: transcript.from_seq,
next_seq: transcript.next_seq,
events,
digest_sha256_b64: transcript.digest_sha256_b64,
},
};
};

const extract_transcript_envs = (events) => {
let welcome_env_b64 = '';
let welcome_seq = null;
let commit_env_b64 = '';
let commit_seq = null;
let app_env_b64 = '';
let app_seq = null;
let app_count = 0;
for (const event of events) {
const seq = event.seq;
const env_bytes = base64_to_bytes(event.env);
if (!env_bytes || env_bytes.length < 1) {
continue;
}
const kind = env_bytes[0];
if (kind === 1) {
if (welcome_seq === null || seq < welcome_seq) {
welcome_seq = seq;
welcome_env_b64 = event.env;
}
} else if (kind === 2) {
if (commit_seq === null || seq < commit_seq) {
commit_seq = seq;
commit_env_b64 = event.env;
}
} else if (kind === 3) {
app_count += 1;
if (app_seq === null || seq > app_seq) {
app_seq = seq;
app_env_b64 = event.env;
}
}
}
return {
welcome_env_b64,
welcome_seq,
commit_env_b64,
commit_seq,
app_env_b64,
app_seq,
app_count,
};
};

const handle_parse_cli_block = () => {
const block_text = cli_block_input ? cli_block_input.value : '';
if (!block_text || !block_text.trim()) {
set_status('error');
log_output('paste CLI output block');
return;
}
const { parsed, found_keys } = parse_cli_block(block_text);
if (!found_keys.length) {
set_status('error');
log_output('no import fields found in block');
return;
}
if (parsed.welcome_env_b64) {
parsed_welcome_env_b64 = parsed.welcome_env_b64;
set_incoming_env_input(parsed.welcome_env_b64);
}
if (parsed.commit_env_b64) {
parsed_commit_env_b64 = parsed.commit_env_b64;
}
if (parsed.app_env_b64) {
parsed_app_env_b64 = parsed.app_env_b64;
}
if (parsed.expected_plaintext !== '') {
expected_plaintext = parsed.expected_plaintext;
set_expected_plaintext_input();
}
const missing_keys = cli_block_keys.filter((key) => !parsed[key]);
const missing_summary = missing_keys.length ? `; missing: ${missing_keys.join(', ')}` : '';
set_status('parsed block');
log_output(`parsed block: ${found_keys.join(', ')}${missing_summary}`);
};

const handle_verify_expected = () => {
const expected = expected_plaintext_input ? expected_plaintext_input.value : '';
const actual = decrypted_output ? decrypted_output.value : '';
if (!expected) {
set_status('error');
log_output('expected_plaintext is empty');
return;
}
if (actual === expected) {
set_status('verify ok');
log_output('verify ok');
return;
}
const expected_short = truncate_text(expected, 120);
const actual_short = truncate_text(actual, 120);
set_status('verify failed');
log_output(`verify failed: expected="${expected_short}" actual="${actual_short}"`);
};

const handle_import_transcript = async () => {
const pasted_text = transcript_textarea ? transcript_textarea.value.trim() : '';
let transcript_text = pasted_text;
if (!transcript_text) {
const file = transcript_file_input && transcript_file_input.files ? transcript_file_input.files[0] : null;
if (!file) {
set_transcript_status('no transcript input');
set_status('error');
return;
}
try {
transcript_text = await file.text();
} catch (error) {
set_transcript_status('failed reading transcript file');
set_status('error');
return;
}
}
const parsed = parse_transcript_json(transcript_text);
if (!parsed.ok) {
set_transcript_status(parsed.error);
set_status('error');
return;
}
const validated = validate_transcript(parsed.transcript);
if (!validated.ok) {
set_transcript_status(validated.error);
set_status('error');
return;
}
const transcript = validated.transcript;
let digest_note = 'no digest';
if (transcript.digest_sha256_b64) {
const computed_digest = await compute_transcript_digest(transcript);
if (computed_digest === transcript.digest_sha256_b64) {
digest_note = 'digest ok';
} else {
digest_note = 'digest mismatch';
}
}
const extracted = extract_transcript_envs(transcript.events);
parsed_welcome_env_b64 = extracted.welcome_env_b64;
parsed_commit_env_b64 = extracted.commit_env_b64;
parsed_app_env_b64 = extracted.app_env_b64;
const outbox_update = {};
if (extracted.welcome_env_b64) {
outbox_update.welcome_env_b64 = extracted.welcome_env_b64;
}
if (extracted.commit_env_b64) {
outbox_update.commit_env_b64 = extracted.commit_env_b64;
}
if (extracted.app_env_b64) {
outbox_update.app_env_b64 = extracted.app_env_b64;
}
if (Object.keys(outbox_update).length > 0) {
set_outbox_envs(outbox_update);
}
if (parsed_welcome_env_b64) {
set_incoming_env_input(parsed_welcome_env_b64);
}
const env_status = [];
if (extracted.welcome_seq !== null) {
env_status.push(`welcome seq=${extracted.welcome_seq}`);
}
if (extracted.commit_seq !== null) {
env_status.push(`commit seq=${extracted.commit_seq}`);
}
if (extracted.app_seq !== null) {
const app_note = extracted.app_count > 1 ? `app seq=${extracted.app_seq} (highest of ${extracted.app_count})` : `app seq=${extracted.app_seq}`;
env_status.push(app_note);
}
const env_summary = env_status.length ? `; ${env_status.join(', ')}` : '';
set_transcript_status(`imported; ${digest_note}${env_summary}`);
set_status('transcript imported');
};

const handle_save_state = async () => {
const result = await save_state();
if (!result || !result.ok) {
return;
}
set_status('saved');
if (result.mode === 'encrypted') {
log_output('encrypted state saved to IndexedDB');
} else {
log_output('legacy state saved to IndexedDB');
}
};

const handle_load_state = async () => {
await load_state();
};

if (create_alice_btn) {
create_alice_btn.addEventListener('click', () => {
handle_create_alice();
});
}

if (create_bob_btn) {
create_bob_btn.addEventListener('click', () => {
handle_create_bob();
});
}

if (init_btn) {
init_btn.addEventListener('click', () => {
handle_init();
});
}

if (join_btn) {
join_btn.addEventListener('click', () => {
handle_join();
});
}

if (commit_apply_btn) {
commit_apply_btn.addEventListener('click', () => {
handle_commit_apply();
});
}

if (encrypt_alice_btn) {
encrypt_alice_btn.addEventListener('click', () => {
handle_encrypt_alice();
});
}

if (encrypt_bob_btn) {
encrypt_bob_btn.addEventListener('click', () => {
handle_encrypt_bob();
});
}

if (save_state_btn) {
save_state_btn.addEventListener('click', () => {
handle_save_state();
});
}

if (load_state_btn) {
load_state_btn.addEventListener('click', () => {
handle_load_state();
});
}

if (reset_state_btn) {
reset_state_btn.addEventListener('click', () => {
reset_state();
});
}

window.addEventListener('dm.commit.echoed', (event) => {
const detail = event && event.detail ? event.detail : null;
if (!detail || typeof detail.env_b64 !== 'string') {
return;
}
const conv_id = typeof detail.conv_id === 'string' ? detail.conv_id : '';
if (normalize_conv_id(conv_id) !== active_conv_id) {
return;
}
if (!last_local_commit_env_b64) {
return;
}
if (detail.env_b64 !== last_local_commit_env_b64) {
return;
}
set_commit_echo_state('received', detail.seq);
});

window.addEventListener('conv.event.received', (event) => {
const detail = event && event.detail ? event.detail : null;
if (!detail || typeof detail.env !== 'string') {
return;
}
const conv_id = typeof detail.conv_id === 'string' ? detail.conv_id : '';
if (normalize_conv_id(conv_id) !== active_conv_id) {
return;
}
const seq_value =
typeof detail.seq === 'number' ? detail.seq : Number.parseInt(detail.seq, 10);
if (!Number.isInteger(seq_value) || seq_value < 1) {
return;
}
const env_meta = parse_live_inbox_env(detail.env);
if (!env_meta) {
return;
}
if (!live_inbox_by_seq.has(seq_value)) {
live_inbox_by_seq.set(seq_value, detail.env);
}
update_live_inbox_status();
if (!get_live_inbox_enabled()) {
return;
}
run_live_inbox_auto_ingest();
});

const dm_fieldset = dm_status ? dm_status.closest('fieldset') : null;
let incoming_env_input = null;
let expected_plaintext_input = null;
let cli_block_input = null;
let storage_passphrase_input = null;
let storage_encrypt_checkbox = null;
let storage_status_line = null;
let encrypt_checkbox_touched = false;
if (dm_fieldset) {
if (dm_status && dm_status.parentNode) {
dm_conv_status_line = document.createElement('div');
dm_conv_status_line.className = 'dm_conv_status';
dm_conv_status_line.textContent = `DM UI bound to conv_id: ${active_conv_id}`;
if (dm_status.nextSibling) {
dm_status.parentNode.insertBefore(dm_conv_status_line, dm_status.nextSibling);
} else {
dm_status.parentNode.appendChild(dm_conv_status_line);
}
}
const storage_container = document.createElement('div');
storage_container.className = 'dm_storage';

const storage_title = document.createElement('div');
storage_title.textContent = 'Storage';
storage_container.appendChild(storage_title);

const passphrase_label = document.createElement('label');
passphrase_label.textContent = 'storage_passphrase';
storage_passphrase_input = document.createElement('input');
storage_passphrase_input.type = 'password';
storage_passphrase_input.size = 32;
storage_passphrase_input.addEventListener('input', () => {
update_encrypt_checkbox_default();
});
passphrase_label.appendChild(storage_passphrase_input);
storage_container.appendChild(passphrase_label);

const encrypt_label = document.createElement('label');
storage_encrypt_checkbox = document.createElement('input');
storage_encrypt_checkbox.type = 'checkbox';
storage_encrypt_checkbox.addEventListener('change', () => {
encrypt_checkbox_touched = true;
});
encrypt_label.appendChild(storage_encrypt_checkbox);
encrypt_label.appendChild(document.createTextNode(' Encrypt saved state'));
storage_container.appendChild(encrypt_label);

storage_status_line = document.createElement('div');
storage_status_line.className = 'dm_storage_status';
storage_status_line.textContent = 'storage idle';
storage_container.appendChild(storage_status_line);

update_encrypt_checkbox_default();

const storage_anchor = save_state_btn ? save_state_btn.closest('div') : null;
if (storage_anchor && storage_anchor.parentNode) {
if (storage_anchor.nextSibling) {
storage_anchor.parentNode.insertBefore(storage_container, storage_anchor.nextSibling);
} else {
storage_anchor.parentNode.appendChild(storage_container);
}
} else {
dm_fieldset.appendChild(storage_container);
}

const outbox_container = document.createElement('div');
outbox_container.className = 'dm_outbox';

const outbox_title = document.createElement('div');
outbox_title.textContent = 'DM Outbox';
outbox_container.appendChild(outbox_title);

const outbox_welcome_label = document.createElement('label');
outbox_welcome_label.textContent = 'outbox_welcome_env_b64';
outbox_welcome_textarea = document.createElement('textarea');
outbox_welcome_textarea.rows = 3;
outbox_welcome_textarea.cols = 64;
outbox_welcome_textarea.readOnly = true;
outbox_welcome_label.appendChild(outbox_welcome_textarea);
outbox_container.appendChild(outbox_welcome_label);

const outbox_commit_label = document.createElement('label');
outbox_commit_label.textContent = 'outbox_commit_env_b64';
outbox_commit_textarea = document.createElement('textarea');
outbox_commit_textarea.rows = 3;
outbox_commit_textarea.cols = 64;
outbox_commit_textarea.readOnly = true;
outbox_commit_label.appendChild(outbox_commit_textarea);
outbox_container.appendChild(outbox_commit_label);

const outbox_app_label = document.createElement('label');
outbox_app_label.textContent = 'outbox_app_env_b64';
outbox_app_textarea = document.createElement('textarea');
outbox_app_textarea.rows = 3;
outbox_app_textarea.cols = 64;
outbox_app_textarea.readOnly = true;
outbox_app_label.appendChild(outbox_app_textarea);
outbox_container.appendChild(outbox_app_label);

const outbox_buttons = document.createElement('div');
outbox_buttons.className = 'button-row';
outbox_copy_btn = document.createElement('button');
outbox_copy_btn.type = 'button';
outbox_copy_btn.textContent = 'Copy outbox as key=value block';
outbox_copy_btn.addEventListener('click', () => {
copy_outbox_block();
});
outbox_buttons.appendChild(outbox_copy_btn);
outbox_container.appendChild(outbox_buttons);

if (storage_container.parentNode) {
if (storage_container.nextSibling) {
storage_container.parentNode.insertBefore(outbox_container, storage_container.nextSibling);
} else {
storage_container.parentNode.appendChild(outbox_container);
}
} else {
dm_fieldset.appendChild(outbox_container);
}
update_outbox_ui();

const import_container = document.createElement('div');
import_container.className = 'dm_import_env';

const transcript_group = document.createElement('div');
transcript_group.className = 'dm_transcript_import';

const transcript_file_label = document.createElement('label');
transcript_file_label.textContent = 'transcript_file';
transcript_file_input = document.createElement('input');
transcript_file_input.type = 'file';
transcript_file_input.accept = '.json';
transcript_file_label.appendChild(transcript_file_input);
transcript_group.appendChild(transcript_file_label);

const transcript_paste_label = document.createElement('label');
transcript_paste_label.textContent = 'transcript_json';
transcript_textarea = document.createElement('textarea');
transcript_textarea.rows = 6;
transcript_textarea.cols = 64;
transcript_paste_label.appendChild(transcript_textarea);
transcript_group.appendChild(transcript_paste_label);

const transcript_buttons = document.createElement('div');
transcript_buttons.className = 'button-row';
const transcript_import_btn = document.createElement('button');
transcript_import_btn.type = 'button';
transcript_import_btn.textContent = 'Import transcript';
transcript_import_btn.addEventListener('click', () => {
handle_import_transcript();
});
transcript_buttons.appendChild(transcript_import_btn);
transcript_group.appendChild(transcript_buttons);

transcript_status_line = document.createElement('div');
transcript_status_line.className = 'dm_transcript_status';
transcript_status_line.textContent = 'transcript idle';
transcript_group.appendChild(transcript_status_line);

import_container.appendChild(transcript_group);

const cli_block_label = document.createElement('label');
cli_block_label.textContent = 'cli_output_block';
cli_block_input = document.createElement('textarea');
cli_block_input.rows = 6;
cli_block_input.cols = 64;
cli_block_label.appendChild(cli_block_input);
import_container.appendChild(cli_block_label);

const parse_buttons = document.createElement('div');
parse_buttons.className = 'button-row';
const parse_block_btn = document.createElement('button');
parse_block_btn.type = 'button';
parse_block_btn.textContent = 'Parse block';
parse_block_btn.addEventListener('click', () => {
handle_parse_cli_block();
});
parse_buttons.appendChild(parse_block_btn);
import_container.appendChild(parse_buttons);

const import_label = document.createElement('label');
import_label.textContent = 'incoming_env_b64';
incoming_env_input = document.createElement('textarea');
incoming_env_input.rows = 3;
incoming_env_input.cols = 64;
import_label.appendChild(incoming_env_input);
import_container.appendChild(import_label);

const expected_label = document.createElement('label');
expected_label.textContent = 'expected_plaintext';
expected_plaintext_input = document.createElement('input');
expected_plaintext_input.type = 'text';
expected_plaintext_input.size = 64;
expected_label.appendChild(expected_plaintext_input);
import_container.appendChild(expected_label);

const import_buttons = document.createElement('div');
import_buttons.className = 'button-row';

const load_welcome_btn = document.createElement('button');
load_welcome_btn.type = 'button';
load_welcome_btn.textContent = 'Load welcome env';
load_welcome_btn.addEventListener('click', () => {
handle_import_welcome_env();
});

const load_commit_btn = document.createElement('button');
load_commit_btn.type = 'button';
load_commit_btn.textContent = 'Load commit env';
load_commit_btn.addEventListener('click', () => {
handle_import_commit_env();
});

const decrypt_bob_btn = document.createElement('button');
decrypt_bob_btn.type = 'button';
decrypt_bob_btn.textContent = 'Decrypt app env as Bob';
decrypt_bob_btn.addEventListener('click', () => {
handle_decrypt_app_env('bob');
});

const decrypt_alice_btn = document.createElement('button');
decrypt_alice_btn.type = 'button';
decrypt_alice_btn.textContent = 'Decrypt app env as Alice';
decrypt_alice_btn.addEventListener('click', () => {
handle_decrypt_app_env('alice');
});

const verify_expected_btn = document.createElement('button');
verify_expected_btn.type = 'button';
verify_expected_btn.textContent = 'Verify decrypted == expected';
verify_expected_btn.addEventListener('click', () => {
handle_verify_expected();
});

import_buttons.appendChild(load_welcome_btn);
import_buttons.appendChild(load_commit_btn);
import_buttons.appendChild(decrypt_bob_btn);
import_buttons.appendChild(decrypt_alice_btn);
import_buttons.appendChild(verify_expected_btn);
import_container.appendChild(import_buttons);

const live_inbox_container = document.createElement('div');
live_inbox_container.className = 'dm_live_inbox';

const live_inbox_title = document.createElement('div');
live_inbox_title.textContent = 'Live inbox';
live_inbox_container.appendChild(live_inbox_title);

const live_inbox_enable_label = document.createElement('label');
live_inbox_enabled_input = document.createElement('input');
live_inbox_enabled_input.type = 'checkbox';
live_inbox_enabled_input.addEventListener('change', () => {
update_live_inbox_controls();
update_live_inbox_status();
if (get_live_inbox_enabled()) {
run_live_inbox_auto_ingest();
}
});
live_inbox_enable_label.appendChild(live_inbox_enabled_input);
live_inbox_enable_label.appendChild(document.createTextNode(' Enable live inbox'));
live_inbox_container.appendChild(live_inbox_enable_label);

const live_inbox_auto_label = document.createElement('label');
live_inbox_auto_input = document.createElement('input');
live_inbox_auto_input.type = 'checkbox';
live_inbox_auto_input.addEventListener('change', () => {
update_live_inbox_controls();
update_live_inbox_status();
if (get_live_inbox_enabled()) {
run_live_inbox_auto_ingest();
}
});
live_inbox_auto_label.appendChild(live_inbox_auto_input);
live_inbox_auto_label.appendChild(document.createTextNode(' Auto-ingest in order'));
live_inbox_container.appendChild(live_inbox_auto_label);

const live_inbox_expected_label = document.createElement('label');
live_inbox_expected_label.textContent = 'expected_seq';
live_inbox_expected_input = document.createElement('input');
live_inbox_expected_input.type = 'number';
live_inbox_expected_input.min = '1';
live_inbox_expected_input.value = String(live_inbox_expected_seq);
live_inbox_expected_input.addEventListener('change', () => {
set_live_inbox_expected_seq(live_inbox_expected_input.value);
if (get_live_inbox_enabled()) {
run_live_inbox_auto_ingest();
}
});
live_inbox_expected_label.appendChild(live_inbox_expected_input);
live_inbox_container.appendChild(live_inbox_expected_label);

const live_inbox_buttons = document.createElement('div');
live_inbox_buttons.className = 'button-row';
live_inbox_ingest_btn = document.createElement('button');
live_inbox_ingest_btn.type = 'button';
live_inbox_ingest_btn.textContent = 'Ingest next';
live_inbox_ingest_btn.addEventListener('click', () => {
ingest_live_inbox_seq(live_inbox_expected_seq);
});
live_inbox_buttons.appendChild(live_inbox_ingest_btn);
live_inbox_container.appendChild(live_inbox_buttons);

live_inbox_status_line = document.createElement('div');
live_inbox_status_line.className = 'dm_live_inbox_status';
live_inbox_container.appendChild(live_inbox_status_line);
update_live_inbox_controls();
update_live_inbox_status();

import_container.appendChild(live_inbox_container);

if (dm_output && dm_output.parentNode) {
dm_output.parentNode.insertBefore(import_container, dm_output);
} else {
dm_fieldset.appendChild(import_container);
}
}

if (commit_apply_btn) {
const commit_anchor = commit_apply_btn.closest('div') || commit_apply_btn.parentNode;
commit_echo_status_line = document.createElement('div');
commit_echo_status_line.className = 'dm_commit_echo_status';
commit_echo_status_line.textContent = 'commit echo: idle';
if (commit_anchor && commit_anchor.parentNode) {
if (commit_anchor.nextSibling) {
commit_anchor.parentNode.insertBefore(commit_echo_status_line, commit_anchor.nextSibling);
} else {
commit_anchor.parentNode.appendChild(commit_echo_status_line);
}
}
}

set_status('idle');
set_group_id_input();
update_commit_apply_state();
update_commit_echo_status_line();
update_conv_status_label();

window.addEventListener('conv.selected', (event) => {
const detail = event && event.detail ? event.detail : null;
const next_conv_id = normalize_conv_id(detail && typeof detail.conv_id === 'string' ? detail.conv_id : '');
if (next_conv_id === active_conv_id) {
return;
}
save_active_conv_state();
active_conv_id = next_conv_id;
apply_conv_state(get_conv_state(active_conv_id));
update_conv_status_label();
});
