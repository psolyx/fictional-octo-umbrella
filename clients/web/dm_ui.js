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
let transcript_file_input = null;
let transcript_textarea = null;
let transcript_status_line = null;

const seed_alice = 1001;
const seed_bob = 2002;
const seed_init = 3003;

const db_name = 'mls_dm_state';
const store_name = 'records';
const cli_block_keys = [
'welcome_env_b64',
'commit_env_b64',
'app_env_b64',
'expected_plaintext',
];

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

const log_output = (message) => {
if (!dm_output) {
return;
}
dm_output.textContent = message;
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
expected_plaintext = expected_plaintext_input ? expected_plaintext_input.value : expected_plaintext;
const entries = [
['alice', alice_participant_b64],
['bob', bob_participant_b64],
['alice_keypackage', alice_keypackage_b64],
['bob_keypackage', bob_keypackage_b64],
['group_id', group_id_b64],
['welcome', welcome_b64],
['commit', commit_b64],
['expected_plaintext', expected_plaintext],
['parsed_app_env_b64', parsed_app_env_b64],
];
for (const [key, value] of entries) {
if (value) {
await db_set(key, value);
} else {
await db_delete(key);
}
}
};

const load_state = async () => {
alice_participant_b64 = await db_get('alice');
bob_participant_b64 = await db_get('bob');
alice_keypackage_b64 = await db_get('alice_keypackage');
bob_keypackage_b64 = await db_get('bob_keypackage');
group_id_b64 = await db_get('group_id');
welcome_b64 = await db_get('welcome');
commit_b64 = await db_get('commit');
expected_plaintext = await db_get('expected_plaintext');
parsed_app_env_b64 = await db_get('parsed_app_env_b64');
set_group_id_input();
set_expected_plaintext_input();
if (incoming_env_input && parsed_app_env_b64 && !incoming_env_input.value.trim()) {
incoming_env_input.value = parsed_app_env_b64;
}
set_status('loaded');
log_output('loaded state from IndexedDB');
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
set_group_id_input();
set_ciphertext_output('');
set_decrypted_output('');
set_expected_plaintext_input();
set_incoming_env_input('');
await db_clear();
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
set_status('commit loaded');
log_output('commit env loaded; pending apply');
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
await save_state();
set_status('saved');
log_output('state saved to IndexedDB');
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

const dm_fieldset = dm_status ? dm_status.closest('fieldset') : null;
let incoming_env_input = null;
let expected_plaintext_input = null;
let cli_block_input = null;
if (dm_fieldset) {
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

if (dm_output && dm_output.parentNode) {
dm_output.parentNode.insertBefore(import_container, dm_output);
} else {
dm_fieldset.appendChild(import_container);
}
}

set_status('idle');
set_group_id_input();
