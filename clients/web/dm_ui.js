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

const seed_alice = 1001;
const seed_bob = 2002;
const seed_init = 3003;

const db_name = 'mls_dm_state';
const store_name = 'records';

const set_status = (message) => {
if (dm_status) {
dm_status.textContent = message;
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

const save_state = async () => {
const entries = [
['alice', alice_participant_b64],
['bob', bob_participant_b64],
['alice_keypackage', alice_keypackage_b64],
['bob_keypackage', bob_keypackage_b64],
['group_id', group_id_b64],
['welcome', welcome_b64],
['commit', commit_b64],
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
set_group_id_input();
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
set_group_id_input();
set_ciphertext_output('');
set_decrypted_output('');
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
if (dm_fieldset) {
const import_container = document.createElement('div');
import_container.className = 'dm_import_env';

const import_label = document.createElement('label');
import_label.textContent = 'incoming_env_b64';
incoming_env_input = document.createElement('textarea');
incoming_env_input.rows = 3;
incoming_env_input.cols = 64;
import_label.appendChild(incoming_env_input);
import_container.appendChild(import_label);

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

import_buttons.appendChild(load_welcome_btn);
import_buttons.appendChild(load_commit_btn);
import_buttons.appendChild(decrypt_bob_btn);
import_buttons.appendChild(decrypt_alice_btn);
import_container.appendChild(import_buttons);

if (dm_output && dm_output.parentNode) {
dm_output.parentNode.insertBefore(import_container, dm_output);
} else {
dm_fieldset.appendChild(import_container);
}
}

set_status('idle');
set_group_id_input();
