import {
dm_commit_apply,
dm_create_participant,
dm_decrypt,
dm_encrypt,
dm_init,
dm_join,
ensure_wasm_ready,
} from './mls_vectors_loader.js';

const dm_status = document.getElementById('dm_status');
const dm_output = document.getElementById('dm_output');
const group_id_input = document.getElementById('dm_group_id');
const alice_plaintext_input = document.getElementById('dm_alice_plaintext');
const bob_plaintext_input = document.getElementById('dm_bob_plaintext');
const ciphertext_output = document.getElementById('dm_ciphertext');
const decrypted_output = document.getElementById('dm_decrypted');
const device_id_input = document.getElementById('device_id');

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
let last_imported_transcript = null;
let last_imported_digest_note = 'digest missing';
let last_imported_coexist_bundle = null;
let outbox_welcome_textarea = null;
let outbox_commit_textarea = null;
let outbox_app_textarea = null;
let outbox_copy_btn = null;
let outbox_send_init_btn = null;
let outbox_send_app_btn = null;
let outbox_status_line = null;
let live_inbox_by_seq = new Map();
let live_inbox_handshake_buffer_by_seq = new Map();
let live_inbox_handshake_attempts_by_seq = new Map();
let live_inbox_expected_seq = 1;
let live_inbox_last_ingested_seq = null;
let live_inbox_enabled_input = null;
let live_inbox_auto_input = null;
let auto_join_on_welcome_input = null;
let auto_apply_commit_input = null;
let auto_decrypt_app_env_input = null;
let live_inbox_expected_input = null;
let live_inbox_ingest_btn = null;
let run_next_step_btn = null;
let live_inbox_status_line = null;
let run_next_step_status_line = null;
let dm_conv_status_line = null;
let active_conv_id = '(none)';
const conv_state_by_id = new Map();
let commit_apply_in_flight = false;
let run_next_step_in_flight = false;
let dm_phase5_proof_in_flight = false;
let room_phase5_proof_in_flight = false;
let coexist_phase5_proof_in_flight = false;
let bob_has_joined = false;
let last_welcome_seq = null;
let last_commit_seq = null;
let last_app_seq = null;
let gateway_session_token = '';
let gateway_user_id = '';
let gateway_http_base_url = '';
let dm_bootstrap_peer_input = null;
let dm_bootstrap_count_input = null;
let dm_bootstrap_fetch_btn = null;
let dm_bootstrap_publish_btn = null;
let dm_bootstrap_status_line = null;
let room_conv_id = '(none)';
let room_conv_status_line = null;
let room_gateway_invite_input = null;
let room_gateway_remove_input = null;
let room_gateway_create_btn = null;
let room_gateway_invite_btn = null;
let room_gateway_remove_btn = null;
let room_peer_fetch_input = null;
let room_peer_fetch_count_input = null;
let room_peer_fetch_btn = null;
let room_add_user_id_input = null;
let room_add_fetch_btn = null;
let room_welcome_auto_join_input = null;
let room_keypackages_input = null;
let room_add_keypackage_input = null;
let room_welcome_env_input = null;
let room_join_btn = null;
let room_participant_select = null;
let room_send_plaintext_input = null;
let room_send_btn = null;
let room_decrypt_btn = null;
let room_decrypt_msg_id_output = null;
let room_decrypt_plaintext_output = null;
let room_status_line = null;
let room_phase5_proof_run_btn = null;
let room_phase5_proof_auto_reply_input = null;
let room_phase5_proof_reply_input = null;
let room_phase5_peer_wait_input = null;
let room_phase5_peer_expected_input = null;
let room_phase5_peer_timeout_input = null;
let room_phase5_proof_timeline = null;
let room_phase5_proof_report = null;
let coexist_phase5_proof_run_btn = null;
let coexist_phase5_proof_cli_input = null;
let coexist_phase5_bundle_file_input = null;
let coexist_phase5_bundle_import_btn = null;
let coexist_phase5_bundle_status_line = null;
let coexist_phase5_bundle_auto_run_input = null;
let coexist_phase5_proof_auto_reply_input = null;
let coexist_phase5_proof_reply_input = null;
let coexist_phase5_peer_wait_input = null;
let coexist_phase5_peer_expected_input = null;
let coexist_phase5_peer_timeout_input = null;
let coexist_phase5_proof_timeline = null;
let coexist_phase5_proof_report = null;
let dm_phase5_proof_run_btn = null;
let dm_phase5_proof_auto_reply_input = null;
let dm_phase5_proof_reply_input = null;
let dm_phase5_peer_wait_input = null;
let dm_phase5_peer_expected_input = null;
let dm_phase5_peer_timeout_input = null;
let dm_phase5_proof_timeline = null;
let dm_phase5_proof_report = null;

const seed_alice = 1001;
const seed_bob = 2002;
const seed_init = 3003;
const seed_room_init = 4004;
const seed_room_add = 5005;
const keypackage_fetch_path = '/v1/keypackages/fetch';
const keypackage_publish_path = '/v1/keypackages';
const room_create_path = '/v1/rooms/create';
const room_invite_path = '/v1/rooms/invite';
const room_remove_path = '/v1/rooms/remove';
const phase5_peer_wait_default_plaintext = 'phase5-peer-app';
const phase5_peer_wait_default_timeout_ms = 10000;
const gateway_transcript_db_name = 'gateway_web_demo';
const gateway_transcript_db_version = 2;
const gateway_transcript_store_name = 'transcripts';
const gateway_transcript_index_name = 'by_conv_id';
const phase5_mls_state_by_conv_id = new Map();

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
'conv_id',
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
handshake_buffer_by_seq: new Map(),
handshake_attempts_by_seq: new Map(),
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
auto_apply_commit_after_echo: false,
auto_decrypt_app_env: false,
auto_join_on_welcome: false,
bob_has_joined: false,
last_welcome_seq: null,
last_commit_seq: null,
last_app_seq: null,
});

const get_conv_state = (conv_id) => {
const normalized = normalize_conv_id(conv_id);
if (!conv_state_by_id.has(normalized)) {
conv_state_by_id.set(normalized, build_conv_state());
}
return conv_state_by_id.get(normalized);
};

const build_phase5_mls_state = () => ({
bob_participant_b64: '',
bob_has_joined: false,
last_welcome_seq: null,
last_commit_seq: null,
last_app_seq: null,
handshake_buffer_by_seq: new Map(),
handshake_attempts_by_seq: new Map(),
expected_seq: 1,
last_ingested_seq: null,
});

const get_phase5_mls_state = (conv_id) => {
const normalized = normalize_conv_id(conv_id);
if (!phase5_mls_state_by_conv_id.has(normalized)) {
phase5_mls_state_by_conv_id.set(normalized, build_phase5_mls_state());
}
return phase5_mls_state_by_conv_id.get(normalized);
};

const update_conv_status_label = () => {
if (!dm_conv_status_line) {
return;
}
dm_conv_status_line.textContent = `DM UI bound to conv_id: ${active_conv_id}`;
};

const update_room_conv_status = () => {
if (!room_conv_status_line) {
return;
}
room_conv_status_line.textContent = `room conv_id: ${room_conv_id}`;
};

const set_status = (message) => {
if (dm_status) {
dm_status.textContent = message;
}
};

const set_room_status = (message) => {
if (room_status_line) {
room_status_line.textContent = message;
}
};

const set_dm_bootstrap_status = (message) => {
if (dm_bootstrap_status_line) {
dm_bootstrap_status_line.textContent = message;
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

const build_auto_commit_suffix = (seq) => {
if (typeof seq === 'number') {
return ` (seq=${seq})`;
}
return '';
};

const maybe_auto_apply_commit = async (seq, context_note) => {
if (!get_auto_apply_commit_enabled()) {
return false;
}
if (!commit_apply_btn || commit_apply_btn.disabled) {
return false;
}
const ok = await handle_commit_apply();
if (!ok) {
return false;
}
const suffix = build_auto_commit_suffix(seq);
const message = context_note ? `${context_note}${suffix}` : `auto-applied commit after echo${suffix}`;
set_status(message);
log_output(message);
return true;
};

const is_uninitialized_commit_error = (error_text) => {
if (!error_text) {
return false;
}
const lowered = String(error_text).toLowerCase();
return lowered.includes('participant state not initialized') || lowered.includes('state not initialized');
};

const is_missing_proposal_error = (error_text) => {
if (!error_text) {
return false;
}
const lowered = String(error_text).toLowerCase();
const matches = [
'missing proposal',
'unknown proposal',
'proposal not found',
'missing referenced proposal',
'no proposal found',
];
if (matches.some((phrase) => lowered.includes(phrase))) {
return true;
}
const dependency_matches = [
'out of order',
'unknown epoch',
'epoch mismatch',
'epoch not found',
];
return dependency_matches.some((phrase) => lowered.includes(phrase));
};

const select_handshake_participant = () => {
if (alice_participant_b64) {
return { label: 'alice', participant_b64: alice_participant_b64 };
}
if (bob_participant_b64) {
return { label: 'bob', participant_b64: bob_participant_b64 };
}
return null;
};

const select_handshake_participant_by_label = (participant_label) => {
if (participant_label === 'alice') {
return alice_participant_b64
? { label: 'alice', participant_b64: alice_participant_b64 }
: null;
}
if (participant_label === 'bob') {
return bob_participant_b64
? { label: 'bob', participant_b64: bob_participant_b64 }
: null;
}
return null;
};

const set_handshake_participant = (label, participant_b64) => {
if (label === 'alice') {
alice_participant_b64 = participant_b64;
return;
}
if (label === 'bob') {
bob_participant_b64 = participant_b64;
}
};

const enqueue_handshake_buffer = (seq, env_b64, reason) => {
if (Number.isInteger(seq)) {
live_inbox_handshake_buffer_by_seq.set(seq, env_b64);
}
const seq_suffix = Number.isInteger(seq) ? ` (seq=${seq})` : '';
const reason_suffix = reason ? `; ${reason}` : '';
set_status(`handshake buffered${seq_suffix}`);
log_output(`handshake buffered${seq_suffix}${reason_suffix}`);
};

const apply_handshake_env = async (seq, env_b64, options) => {
const normalized_options = options || {};
const context_label = normalized_options.context_label || 'handshake';
const from_buffer = Boolean(normalized_options.from_buffer);
const participant_label =
normalized_options.participant_label === 'alice' || normalized_options.participant_label === 'bob'
? normalized_options.participant_label
: '';
const seq_suffix = Number.isInteger(seq) ? ` (seq=${seq})` : '';
const unpacked = unpack_dm_env(env_b64);
if (!unpacked || unpacked.kind !== 2) {
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: invalid handshake env`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant_label || 'unknown',
noop: false,
error: 'invalid handshake env',
};
}
const participant = participant_label
? select_handshake_participant_by_label(participant_label)
: select_handshake_participant();
if (!participant) {
const reason = participant_label
? `missing ${participant_label} participant`
: 'no participant available';
if (Number.isInteger(seq)) {
enqueue_handshake_buffer(seq, env_b64, reason);
return {
ok: false,
buffered: true,
buffered_reason: 'missing participant',
participant_label_used: participant_label || 'unknown',
noop: false,
error: reason,
};
}
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: ${reason}`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant_label || 'unknown',
noop: false,
error: reason,
};
}
await ensure_wasm_ready();
let result = null;
try {
result = await dm_commit_apply(participant.participant_b64, unpacked.payload_b64);
} catch (error) {
const error_text = String(error);
if (is_uninitialized_commit_error(error_text)) {
const note = from_buffer
? 'participant state not initialized (buffer retained)'
: 'participant state not initialized';
if (Number.isInteger(seq)) {
enqueue_handshake_buffer(seq, env_b64, note);
return {
ok: false,
buffered: true,
buffered_reason: 'uninitialized',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: ${note}`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
if (is_missing_proposal_error(error_text)) {
const note = from_buffer
? 'missing proposal dependency (buffer retained)'
: 'missing proposal dependency';
if (Number.isInteger(seq)) {
enqueue_handshake_buffer(seq, env_b64, note);
return {
ok: false,
buffered: true,
buffered_reason: 'missing proposal',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: ${note}`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: ${error_text}`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant.label,
noop: false,
error: error_text,
};
}
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
if (is_uninitialized_commit_error(error_text)) {
const note = from_buffer
? 'participant state not initialized (buffer retained)'
: 'participant state not initialized';
if (Number.isInteger(seq)) {
enqueue_handshake_buffer(seq, env_b64, note);
return {
ok: false,
buffered: true,
buffered_reason: 'uninitialized',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: ${note}`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
if (is_missing_proposal_error(error_text)) {
const note = from_buffer
? 'missing proposal dependency (buffer retained)'
: 'missing proposal dependency';
if (Number.isInteger(seq)) {
enqueue_handshake_buffer(seq, env_b64, note);
return {
ok: false,
buffered: true,
buffered_reason: 'missing proposal',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: ${note}`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant.label,
noop: false,
error: note,
};
}
set_status('error');
log_output(`${context_label} apply failed${seq_suffix}: ${error_text}`);
return {
ok: false,
buffered: false,
buffered_reason: '',
participant_label_used: participant.label,
noop: false,
error: error_text,
};
}
set_handshake_participant(participant.label, result.participant_b64);
const noop_suffix = result.noop ? ' (noop)' : '';
set_status(`${context_label} applied${noop_suffix}${seq_suffix}`);
log_output(`${context_label} applied as ${participant.label}${noop_suffix}${seq_suffix}`);
return {
ok: true,
buffered: false,
buffered_reason: '',
participant_label_used: participant.label,
noop: Boolean(result.noop),
error: '',
};
};

const drain_handshake_buffer = async (context_label, options) => {
if (!live_inbox_handshake_buffer_by_seq.size) {
return {
ok: true,
stalled_reason: '',
stalled_seq: null,
retry_exhausted: false,
error: '',
};
}
const normalized_options = options || {};
const participant_label =
normalized_options.participant_label === 'alice' || normalized_options.participant_label === 'bob'
? normalized_options.participant_label
: '';
const max_attempts = Number.isInteger(normalized_options.max_attempts)
? normalized_options.max_attempts
: 3;
const sorted_seqs = Array.from(live_inbox_handshake_buffer_by_seq.keys()).sort((a, b) => a - b);
for (const seq of sorted_seqs) {
const env_b64 = live_inbox_handshake_buffer_by_seq.get(seq);
const attempt_count = Number.isInteger(live_inbox_handshake_attempts_by_seq.get(seq))
? live_inbox_handshake_attempts_by_seq.get(seq)
: 0;
if (attempt_count >= max_attempts) {
return {
ok: false,
stalled_reason: 'dependency missing',
stalled_seq: seq,
retry_exhausted: true,
error: 'missing proposal dependency retry limit reached',
};
}
const result = await apply_handshake_env(seq, env_b64, {
context_label: context_label || 'handshake',
from_buffer: true,
participant_label,
});
if (result.ok) {
live_inbox_handshake_buffer_by_seq.delete(seq);
live_inbox_handshake_attempts_by_seq.delete(seq);
continue;
}
if (result.buffered) {
if (result.buffered_reason === 'missing proposal' && Number.isInteger(seq)) {
const next_attempt = attempt_count + 1;
live_inbox_handshake_attempts_by_seq.set(seq, next_attempt);
return {
ok: false,
stalled_reason: 'dependency missing',
stalled_seq: seq,
retry_exhausted: next_attempt >= max_attempts,
error: result.error || 'missing proposal dependency',
};
}
break;
}
return {
ok: false,
stalled_reason: 'apply failed',
stalled_seq: seq,
retry_exhausted: false,
error: result.error || 'handshake apply failed',
};
}
return {
ok: live_inbox_handshake_buffer_by_seq.size === 0,
stalled_reason: '',
stalled_seq: null,
retry_exhausted: false,
error: '',
};
};

const save_active_conv_state = () => {
const state = get_conv_state(active_conv_id);
state.inbox_by_seq = new Map(live_inbox_by_seq);
state.handshake_buffer_by_seq = new Map(live_inbox_handshake_buffer_by_seq);
state.handshake_attempts_by_seq = new Map(live_inbox_handshake_attempts_by_seq);
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
state.auto_apply_commit_after_echo =
Boolean(auto_apply_commit_input && auto_apply_commit_input.checked);
state.auto_decrypt_app_env =
Boolean(auto_decrypt_app_env_input && auto_decrypt_app_env_input.checked);
state.auto_join_on_welcome =
Boolean(auto_join_on_welcome_input && auto_join_on_welcome_input.checked);
state.bob_has_joined = Boolean(bob_has_joined);
state.last_welcome_seq = Number.isInteger(last_welcome_seq) ? last_welcome_seq : null;
state.last_commit_seq = Number.isInteger(last_commit_seq) ? last_commit_seq : null;
state.last_app_seq = Number.isInteger(last_app_seq) ? last_app_seq : null;
};

const apply_conv_state = (state) => {
const normalized_state = state || build_conv_state();
live_inbox_by_seq = new Map(normalized_state.inbox_by_seq || []);
live_inbox_handshake_buffer_by_seq = new Map(normalized_state.handshake_buffer_by_seq || []);
live_inbox_handshake_attempts_by_seq = new Map(normalized_state.handshake_attempts_by_seq || []);
live_inbox_last_ingested_seq =
Number.isInteger(normalized_state.last_ingested_seq) ? normalized_state.last_ingested_seq : null;
set_live_inbox_expected_seq(normalized_state.expected_seq);
if (live_inbox_enabled_input) {
live_inbox_enabled_input.checked = Boolean(normalized_state.live_inbox_enabled);
}
if (live_inbox_auto_input) {
live_inbox_auto_input.checked = Boolean(normalized_state.live_inbox_auto);
}
if (auto_apply_commit_input) {
auto_apply_commit_input.checked = Boolean(normalized_state.auto_apply_commit_after_echo);
}
if (auto_decrypt_app_env_input) {
auto_decrypt_app_env_input.checked = Boolean(normalized_state.auto_decrypt_app_env);
}
if (auto_join_on_welcome_input) {
auto_join_on_welcome_input.checked = Boolean(normalized_state.auto_join_on_welcome);
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
bob_has_joined = Boolean(normalized_state.bob_has_joined);
last_welcome_seq =
Number.isInteger(normalized_state.last_welcome_seq) ? normalized_state.last_welcome_seq : null;
last_commit_seq =
Number.isInteger(normalized_state.last_commit_seq) ? normalized_state.last_commit_seq : null;
last_app_seq =
Number.isInteger(normalized_state.last_app_seq) ? normalized_state.last_app_seq : null;
set_expected_plaintext_input();
set_incoming_env_input(normalized_state.staged_incoming_env_b64 || '');
set_run_next_step_status('last action: idle');
};

const get_live_inbox_enabled = () =>
Boolean(live_inbox_enabled_input && live_inbox_enabled_input.checked);

const get_auto_apply_commit_enabled = () =>
Boolean(auto_apply_commit_input && auto_apply_commit_input.checked);

const get_auto_decrypt_app_env_enabled = () =>
Boolean(auto_decrypt_app_env_input && auto_decrypt_app_env_input.checked);

const get_auto_join_on_welcome_enabled = () =>
Boolean(auto_join_on_welcome_input && auto_join_on_welcome_input.checked);

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

const with_phase5_conv_scope = async (conv_id, opts, fn) => {
const normalized = normalize_conv_id(conv_id);
const prior_state = {
bob_participant_b64,
bob_has_joined,
last_welcome_seq,
last_commit_seq,
last_app_seq,
live_inbox_handshake_buffer_by_seq,
live_inbox_handshake_attempts_by_seq,
live_inbox_expected_seq,
live_inbox_last_ingested_seq,
};
const scoped_state = get_phase5_mls_state(normalized);
bob_participant_b64 = scoped_state.bob_participant_b64 || '';
bob_has_joined = Boolean(scoped_state.bob_has_joined);
last_welcome_seq = scoped_state.last_welcome_seq;
last_commit_seq = scoped_state.last_commit_seq;
last_app_seq = scoped_state.last_app_seq;
live_inbox_handshake_buffer_by_seq = new Map(scoped_state.handshake_buffer_by_seq || []);
live_inbox_handshake_attempts_by_seq = new Map(scoped_state.handshake_attempts_by_seq || []);
live_inbox_last_ingested_seq =
scoped_state.last_ingested_seq !== undefined ? scoped_state.last_ingested_seq : null;
set_live_inbox_expected_seq(
Number.isInteger(scoped_state.expected_seq) ? scoped_state.expected_seq : 1
);
let participant_created = false;
if (opts && opts.ensure_bob_participant && !bob_participant_b64) {
await ensure_wasm_ready();
const created = await dm_create_participant('bob', seed_bob);
if (created && created.participant_b64) {
bob_participant_b64 = created.participant_b64;
participant_created = true;
}
}
try {
return await fn({ participant_created });
} finally {
scoped_state.bob_participant_b64 = bob_participant_b64;
scoped_state.bob_has_joined = bob_has_joined;
scoped_state.last_welcome_seq = last_welcome_seq;
scoped_state.last_commit_seq = last_commit_seq;
scoped_state.last_app_seq = last_app_seq;
scoped_state.handshake_buffer_by_seq = new Map(live_inbox_handshake_buffer_by_seq || []);
scoped_state.handshake_attempts_by_seq = new Map(live_inbox_handshake_attempts_by_seq || []);
scoped_state.expected_seq = live_inbox_expected_seq;
scoped_state.last_ingested_seq = live_inbox_last_ingested_seq;
phase5_mls_state_by_conv_id.set(normalized, scoped_state);
bob_participant_b64 = prior_state.bob_participant_b64;
bob_has_joined = prior_state.bob_has_joined;
last_welcome_seq = prior_state.last_welcome_seq;
last_commit_seq = prior_state.last_commit_seq;
last_app_seq = prior_state.last_app_seq;
live_inbox_handshake_buffer_by_seq = new Map(prior_state.live_inbox_handshake_buffer_by_seq || []);
live_inbox_handshake_attempts_by_seq = new Map(
prior_state.live_inbox_handshake_attempts_by_seq || []
);
live_inbox_last_ingested_seq = prior_state.live_inbox_last_ingested_seq;
set_live_inbox_expected_seq(prior_state.live_inbox_expected_seq);
}
};

const set_run_next_step_status = (message) => {
if (run_next_step_status_line) {
run_next_step_status_line.textContent = message;
}
};

const update_live_inbox_status = (note) => {
if (!live_inbox_status_line) {
return;
}
const queued_count = live_inbox_by_seq.size;
const handshake_count = live_inbox_handshake_buffer_by_seq.size;
const last_seq_text =
live_inbox_last_ingested_seq === null ? 'none' : String(live_inbox_last_ingested_seq);
const parts = [
`queued=${queued_count}`,
`handshake_buffered=${handshake_count}`,
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

const set_outbox_status = (message) => {
if (outbox_status_line) {
outbox_status_line.textContent = message;
}
};

const get_active_conv_id_for_send = () => {
const normalized = normalize_conv_id(active_conv_id);
if (!normalized || normalized === '(none)') {
return '';
}
return normalized;
};

const dispatch_gateway_send_env = (conv_id, env_b64) => {
window.dispatchEvent(
new CustomEvent('gateway.send_env', {
detail: {
conv_id,
env_b64,
},
})
);
};

const dispatch_conv_preview_updated = (conv_id, preview) => {
if (!conv_id || typeof preview !== 'string' || !preview.trim()) {
return;
}
window.dispatchEvent(
new CustomEvent('conv.preview.updated', {
detail: {
conv_id,
preview,
ts_ms: Date.now(),
},
})
);
};

const dispatch_gateway_subscribe = (conv_id, from_seq) => {
const detail = {
conv_id,
};
if (typeof from_seq === 'number' && !Number.isNaN(from_seq)) {
detail.from_seq = from_seq;
}
window.dispatchEvent(
new CustomEvent('gateway.subscribe', {
detail,
})
);
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

const parse_keypackage_lines = (text) => {
if (typeof text !== 'string') {
return [];
}
return text
.split('\n')
.map((line) => line.trim())
.filter((line) => line.length > 0);
};

const parse_user_id_list = (text) => {
if (typeof text !== 'string') {
return [];
}
return text
.split(/[\s,]+/u)
.map((value) => value.trim())
.filter((value) => value.length > 0);
};

const append_textarea_lines = (textarea, lines) => {
if (!textarea || !Array.isArray(lines) || !lines.length) {
return;
}
const existing = textarea.value ? textarea.value.trim() : '';
const prefix = existing ? `${existing}\n` : '';
textarea.value = `${prefix}${lines.join('\n')}`;
};

const get_room_conv_id_for_send = () => {
const normalized = normalize_conv_id(room_conv_id);
if (normalized === '(none)') {
return '';
}
return normalized;
};

const open_transcript_db = () => new Promise((resolve, reject) => {
const request = indexedDB.open(gateway_transcript_db_name, gateway_transcript_db_version);
request.onupgradeneeded = (event) => {
const db = event.target.result;
if (!db.objectStoreNames.contains(gateway_transcript_store_name)) {
const store = db.createObjectStore(gateway_transcript_store_name, { keyPath: 'key' });
store.createIndex(gateway_transcript_index_name, 'conv_id', { unique: false });
return;
}
const store = request.transaction.objectStore(gateway_transcript_store_name);
if (!store.indexNames.contains(gateway_transcript_index_name)) {
store.createIndex(gateway_transcript_index_name, 'conv_id', { unique: false });
}
};
request.onsuccess = () => resolve(request.result);
request.onerror = () => reject(request.error);
});

const read_transcript_records_by_conv_id = async (conv_id) => {
const db = await open_transcript_db();
return new Promise((resolve, reject) => {
const tx = db.transaction(gateway_transcript_store_name, 'readonly');
const store = tx.objectStore(gateway_transcript_store_name);
const index = store.index(gateway_transcript_index_name);
const request = index.getAll(conv_id);
request.onsuccess = () => resolve(request.result || []);
request.onerror = () => reject(request.error || new Error('transcript read failed'));
});
};

const select_latest_app_record = (records) => {
let latest = null;
for (const record of records) {
if (!record || typeof record.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(record.env);
if (!env_meta || env_meta.kind !== 3) {
continue;
}
if (!latest || record.seq > latest.seq) {
latest = record;
}
}
return latest;
};

const select_latest_welcome_record = (records) => {
let latest = null;
for (const record of records) {
if (!record || typeof record.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(record.env);
if (!env_meta || env_meta.kind !== 1) {
continue;
}
if (!latest || record.seq > latest.seq) {
latest = record;
}
}
return latest;
};

const wait_for_new_app_record = async (conv_id, after_seq, timeout_ms) => {
const normalized_after_seq = Number.isInteger(after_seq) ? after_seq : 0;
const normalized_timeout_ms = Number.isInteger(timeout_ms) ? timeout_ms : 8000;
const poll_interval_ms = 300;
const deadline_ms = Date.now() + normalized_timeout_ms;
let last_error = '';
while (Date.now() <= deadline_ms) {
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
last_error = String(error);
}
let latest = null;
for (const record of records) {
if (!record || typeof record.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(record.env);
if (!env_meta || env_meta.kind !== 3) {
continue;
}
if (record.seq <= normalized_after_seq) {
continue;
}
if (!latest || record.seq > latest.seq) {
latest = record;
}
}
if (latest) {
return { ok: true, seq: latest.seq, env_b64: latest.env };
}
await new Promise((resolve) => {
setTimeout(resolve, poll_interval_ms);
});
}
const error_message = last_error
? `timeout waiting for app; last_error=${last_error}`
: 'timeout waiting for app';
return { ok: false, error: error_message };
};

const wait_for_next_app_record = async (conv_id, after_seq, timeout_ms) => {
const normalized_after_seq = Number.isInteger(after_seq) ? after_seq : 0;
const normalized_timeout_ms = Number.isInteger(timeout_ms) ? timeout_ms : 8000;
const poll_interval_ms = 300;
const deadline_ms = Date.now() + normalized_timeout_ms;
let last_error = '';
while (Date.now() <= deadline_ms) {
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
last_error = String(error);
}
let next_record = null;
for (const record of records) {
if (!record || typeof record.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(record.env);
if (!env_meta || env_meta.kind !== 3) {
continue;
}
if (!Number.isInteger(record.seq) || record.seq <= normalized_after_seq) {
continue;
}
if (!next_record || record.seq < next_record.seq) {
next_record = record;
}
}
if (next_record) {
return { ok: true, seq: next_record.seq, env_b64: next_record.env };
}
await new Promise((resolve) => {
setTimeout(resolve, poll_interval_ms);
});
}
const error_message = last_error
? `timeout waiting for app; last_error=${last_error}`
: 'timeout waiting for app';
return { ok: false, error: error_message };
};

const apply_phase5_handshakes_for_records = async (records, options) => {
const normalized_options = options || {};
const context_label = normalized_options.context_label || 'handshake';
const participant_label = 'bob';
const after_seq = Number.isInteger(normalized_options.after_seq)
? normalized_options.after_seq
: Number.isInteger(last_commit_seq)
? last_commit_seq
: 0;
const handshake_events = [];
for (const record of records) {
if (!record || typeof record.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(record.env);
if (!env_meta || env_meta.kind !== 2) {
continue;
}
if (!Number.isInteger(record.seq) || record.seq <= after_seq) {
continue;
}
handshake_events.push({ seq: record.seq, env: record.env });
}
handshake_events.sort((left, right) => left.seq - right.seq);
let handshake_error = '';
for (const handshake_event of handshake_events) {
if (is_unechoed_local_commit_env(handshake_event.env)) {
handshake_error = 'local commit pending echo';
break;
}
const apply_result = await apply_handshake_env(handshake_event.seq, handshake_event.env, {
context_label,
participant_label,
});
if (apply_result.ok) {
last_commit_seq = handshake_event.seq;
continue;
}
if (apply_result.buffered) {
continue;
}
handshake_error = apply_result.error || 'handshake apply failed';
break;
}
if (!handshake_error && live_inbox_handshake_buffer_by_seq.size) {
const drained = await drain_handshake_buffer(`${context_label} buffer`, { participant_label });
if (!drained.ok) {
handshake_error = drained.error || 'handshake buffer drain failed';
}
}
if (handshake_error) {
return { ok: false, error: handshake_error };
}
return { ok: true };
};

const wait_decrypt_peer_app = async (conv_id, after_seq, expected_plaintext, timeout_ms) => {
const normalized_after_seq = Number.isInteger(after_seq) ? after_seq : 0;
const normalized_timeout_ms = Number.isInteger(timeout_ms) ? timeout_ms : 8000;
const expected_value = typeof expected_plaintext === 'string' ? expected_plaintext : '';
return with_phase5_conv_scope(conv_id, { ensure_bob_participant: true }, async () => {
const result = {
ok: false,
peer_app_seq: null,
decrypted_plaintext: '',
match: false,
error: '',
};
if (!bob_participant_b64) {
result.error = 'missing bob participant';
return result;
}
let after_seq_cursor = normalized_after_seq;
const deadline_ms = Date.now() + normalized_timeout_ms;
while (Date.now() <= deadline_ms) {
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
result.error = `transcript read failed: ${error}`;
return result;
}
const handshake_result = await apply_phase5_handshakes_for_records(records, {
context_label: 'peer wait handshake',
after_seq: after_seq_cursor,
});
if (!handshake_result.ok) {
result.error = handshake_result.error;
return result;
}
const remaining_ms = Math.max(0, deadline_ms - Date.now());
if (remaining_ms <= 0) {
break;
}
const wait_result = await wait_for_next_app_record(conv_id, after_seq_cursor, remaining_ms);
if (!wait_result.ok) {
result.error = wait_result.error || 'peer app wait timeout';
return result;
}
after_seq_cursor = wait_result.seq;
result.peer_app_seq = wait_result.seq;
const app_unpacked = unpack_dm_env(wait_result.env_b64);
if (!app_unpacked || app_unpacked.kind !== 3) {
result.error = 'invalid app env';
return result;
}
const dec_result = await dm_decrypt(bob_participant_b64, app_unpacked.payload_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
result.error = `decrypt failed: ${error_text}`;
return result;
}
bob_participant_b64 = dec_result.participant_b64;
result.decrypted_plaintext = dec_result.plaintext;
if (!expected_value || dec_result.plaintext === expected_value) {
result.match = true;
result.ok = true;
return result;
}
}
result.error = result.error || 'peer app wait timeout';
return result;
});
};

const decrypt_app_env_from_records = async (records, seq, expected_plaintext, context_label) => {
const result = {
ok: false,
seq,
plaintext: '',
match: false,
error: '',
};
if (!Number.isInteger(seq)) {
result.error = 'invalid seq';
return result;
}
if (!bob_participant_b64) {
result.error = 'missing bob participant';
return result;
}
const record = Array.isArray(records)
? records.find((entry) => entry && entry.seq === seq && typeof entry.env === 'string')
: null;
if (!record) {
result.error = `missing app env at seq ${seq}`;
return result;
}
const env_meta = parse_live_inbox_env(record.env);
if (!env_meta || env_meta.kind !== 3) {
result.error = `invalid app env at seq ${seq}`;
return result;
}
const handshake_result = await apply_phase5_handshakes_for_records(records || [], {
context_label,
after_seq: last_commit_seq,
});
if (!handshake_result.ok) {
result.error = handshake_result.error || 'handshake apply failed';
return result;
}
const unpacked = unpack_dm_env(record.env);
if (!unpacked || unpacked.kind !== 3) {
result.error = `invalid app env at seq ${seq}`;
return result;
}
const dec_result = await dm_decrypt(bob_participant_b64, unpacked.payload_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
result.error = `decrypt failed: ${error_text}`;
return result;
}
bob_participant_b64 = dec_result.participant_b64;
result.plaintext = dec_result.plaintext;
if (!expected_plaintext || dec_result.plaintext === expected_plaintext) {
result.match = true;
result.ok = true;
}
return result;
};

const build_peer_wait_token = () => {
const token_bytes = new Uint8Array(8);
if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === 'function') {
globalThis.crypto.getRandomValues(token_bytes);
} else {
for (let index = 0; index < token_bytes.length; index += 1) {
token_bytes[index] = Math.floor(Math.random() * 256);
}
}
let token_value = '';
for (const entry of token_bytes) {
token_value += entry.toString(16).padStart(2, '0');
}
return token_value.slice(0, 16);
};

const send_phase5_peer_wait_token = async (conv_id, token_plaintext, opts) => {
const options = opts || {};
const status_prefix = options.status_prefix || 'peer wait token';
const set_status_fn = options.set_status_fn;
const set_status = (message) => {
if (typeof set_status_fn === 'function') {
set_status_fn(`${status_prefix}: ${message}`);
}
};
const result = {
ok: false,
env_b64: '',
error: '',
};
if (!token_plaintext) {
result.error = 'missing peer wait token';
return result;
}
if (!bob_participant_b64) {
result.error = 'missing bob participant';
return result;
}
set_status('encrypting token');
await ensure_wasm_ready();
const enc_result = await dm_encrypt(bob_participant_b64, token_plaintext);
if (!enc_result || !enc_result.ok) {
const error_text = enc_result && enc_result.error ? enc_result.error : 'unknown error';
result.error = `encrypt failed: ${error_text}`;
set_status('token encrypt failed');
return result;
}
bob_participant_b64 = enc_result.participant_b64;
const token_env_b64 = pack_dm_env(3, enc_result.ciphertext_b64);
dispatch_gateway_send_env(conv_id, token_env_b64);
result.ok = true;
result.env_b64 = token_env_b64;
set_status('token sent');
return result;
};

const send_wait_decrypt_app = async (conv_id, label, plaintext, opts) => {
const normalized_label = label || 'coexist';
const normalized_opts = opts || {};
const timeout_ms = Number.isInteger(normalized_opts.timeout_ms)
? normalized_opts.timeout_ms
: 8000;
const status_prefix = normalized_opts.status_prefix || `coexist ${normalized_label}`;
const set_status_fn = normalized_opts.set_status_fn;
const set_status = (message) => {
if (typeof set_status_fn === 'function') {
set_status_fn(`${status_prefix}: ${message}`);
}
};
return with_phase5_conv_scope(conv_id, { ensure_bob_participant: true }, async () => {
const result = {
ok: false,
sent_count: 0,
last_app_seq: null,
decrypt_ok: false,
digest: '',
error: '',
};
if (!bob_participant_b64) {
result.error = 'missing bob participant';
return result;
}
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
result.error = `transcript read failed: ${error}`;
return result;
}
const handshake_result = await apply_phase5_handshakes_for_records(records, {
context_label: `handshake (${normalized_label})`,
});
if (!handshake_result.ok) {
result.error = handshake_result.error;
return result;
}
const latest_app = select_latest_app_record(records);
const after_seq =
latest_app && Number.isInteger(latest_app.seq)
? latest_app.seq
: Number.isInteger(last_app_seq)
? last_app_seq
: 0;
set_status('encrypting app');
await ensure_wasm_ready();
const enc_result = await dm_encrypt(bob_participant_b64, plaintext);
if (!enc_result || !enc_result.ok) {
const error_text = enc_result && enc_result.error ? enc_result.error : 'unknown error';
result.error = `encrypt failed: ${error_text}`;
set_status('encrypt failed');
log_output(`${status_prefix} app encrypt failed: ${error_text}`);
return result;
}
bob_participant_b64 = enc_result.participant_b64;
const app_env_b64 = pack_dm_env(3, enc_result.ciphertext_b64);
dispatch_gateway_send_env(conv_id, app_env_b64);
result.sent_count = 1;
set_status('waiting for echo');
const wait_result = await wait_for_new_app_record(conv_id, after_seq, timeout_ms);
if (!wait_result.ok) {
result.error = wait_result.error || 'app echo timeout';
set_status('echo timeout');
log_output(`${status_prefix} app echo timeout: ${result.error}`);
return result;
}
result.last_app_seq = wait_result.seq;
const app_unpacked = unpack_dm_env(wait_result.env_b64);
if (!app_unpacked || app_unpacked.kind !== 3) {
result.error = 'invalid app env';
set_status('decrypt failed');
log_output(`${status_prefix} app env invalid`);
return result;
}
set_status('decrypting app');
const dec_result = await dm_decrypt(bob_participant_b64, app_unpacked.payload_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
result.error = `decrypt failed: ${error_text}`;
set_status('decrypt failed');
log_output(`${status_prefix} app decrypt failed: ${error_text}`);
return result;
}
bob_participant_b64 = dec_result.participant_b64;
result.decrypt_ok = true;
result.ok = true;
last_app_seq = result.last_app_seq;
set_status('app decrypted');
try {
const updated_records = await read_transcript_records_by_conv_id(conv_id);
const transcript = build_transcript_from_records(conv_id, updated_records);
result.digest = await compute_transcript_digest(transcript);
} catch (error) {
result.digest = '';
}
return result;
});
};

const resolve_room_participant = (action_label) => {
const selection = room_participant_select ? room_participant_select.value : 'bob';
if (selection === 'alice') {
if (!alice_participant_b64) {
set_room_status(`room: need alice participant for ${action_label}`);
log_output(`room ${action_label} blocked: missing alice participant`);
return null;
}
return { label: 'alice', participant_b64: alice_participant_b64 };
}
if (!bob_participant_b64) {
set_room_status(`room: need bob participant for ${action_label}`);
log_output(`room ${action_label} blocked: missing bob participant`);
return null;
}
return { label: 'bob', participant_b64: bob_participant_b64 };
};

const get_group_init_fn = () => {
const group_init_fn = globalThis['groupInit'];
if (typeof group_init_fn !== 'function') {
return null;
}
return group_init_fn;
};

const get_group_add_fn = () => {
const group_add_fn = globalThis['groupAdd'];
if (typeof group_add_fn !== 'function') {
return null;
}
return group_add_fn;
};

/*
Manual sanity (room):
- Use "Create room" to register room_conv_id and optionally invite peers.
- Invite/remove uses gateway HTTP and expects user_id lists (comma/space separated).
- "Fetch room peer keypackages" loads keypackages for init/add without copy/paste.
- "Load latest welcome from transcript" finds the newest kind=1 env and can auto-join.
- "Room init" sends welcome+commit and waits for echo before commit apply.
- "Room add member" sends follow-up welcome+commit, still waiting for echo before commit apply.
- "Room join (peer)" uses bob participant to apply welcome, waits for echoed commit from transcript.
- "Room send app" emits kind=3 env; "Room decrypt latest app" reads from transcript store.
*/

const get_room_gateway_auth = () => {
if (!gateway_session_token || !gateway_http_base_url) {
set_room_status('room: gateway session not ready');
return null;
}
return {
session_token: gateway_session_token,
http_base_url: gateway_http_base_url,
};
};

const parse_peer_fetch_count = () => {
if (!room_peer_fetch_count_input) {
return 1;
}
const parsed = Number.parseInt(room_peer_fetch_count_input.value, 10);
if (!Number.isInteger(parsed) || parsed < 1) {
return 1;
}
return parsed;
};

const resolve_room_create_conv_id = () => {
const normalized = normalize_conv_id(room_conv_id);
if (normalized !== '(none)') {
return normalized;
}
if (!group_id_b64) {
group_id_b64 = generate_group_id();
set_group_id_input();
}
return group_id_b64;
};

const fetch_keypackage_for_user = async (auth, user_id, count) => {
let response;
try {
response = await fetch(`${auth.http_base_url}${keypackage_fetch_path}`, {
method: 'POST',
headers: {
'Content-Type': 'application/json',
Authorization: `Bearer ${auth.session_token}`,
},
body: JSON.stringify({ user_id, count }),
});
} catch (error) {
return { ok: false, error: `fetch failed: ${error}` };
}
let payload = null;
try {
payload = await response.json();
} catch (error) {
payload = null;
}
if (!response.ok) {
const message =
payload && payload.message ? payload.message : `request failed (${response.status})`;
return { ok: false, error: message };
}
const keypackages = payload && Array.isArray(payload.keypackages) ? payload.keypackages : [];
if (!keypackages.length || typeof keypackages[0] !== 'string') {
return { ok: false, error: 'no keypackages returned' };
}
return { ok: true, keypackage: keypackages[0] };
};

const handle_room_create_gateway = async () => {
const auth = get_room_gateway_auth();
if (!auth) {
return;
}
const conv_id = resolve_room_create_conv_id();
if (!conv_id) {
set_room_status('room: missing conv_id');
return;
}
const invite_text = room_gateway_invite_input ? room_gateway_invite_input.value : '';
const members = parse_user_id_list(invite_text);
set_room_status('room: creating room...');
let response;
try {
response = await fetch(`${auth.http_base_url}${room_create_path}`, {
method: 'POST',
headers: {
'Content-Type': 'application/json',
Authorization: `Bearer ${auth.session_token}`,
},
body: JSON.stringify({ conv_id, members }),
});
} catch (error) {
set_room_status(`room: create failed (${error})`);
return;
}
let payload = null;
try {
payload = await response.json();
} catch (error) {
payload = null;
}
if (!response.ok) {
const message =
payload && payload.message ? payload.message : `request failed (${response.status})`;
set_room_status(`room: create failed (${message})`);
return;
}
room_conv_id = conv_id;
update_room_conv_status();
set_room_status('room: created');
log_output(`room created for conv_id ${conv_id}`);
};

const handle_room_invite_gateway = async () => {
const auth = get_room_gateway_auth();
if (!auth) {
return;
}
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before invite');
return;
}
const invite_text = room_gateway_invite_input ? room_gateway_invite_input.value : '';
const members = parse_user_id_list(invite_text);
if (!members.length) {
set_room_status('room: invite user_id required');
return;
}
set_room_status('room: inviting members...');
let response;
try {
response = await fetch(`${auth.http_base_url}${room_invite_path}`, {
method: 'POST',
headers: {
'Content-Type': 'application/json',
Authorization: `Bearer ${auth.session_token}`,
},
body: JSON.stringify({ conv_id, members }),
});
} catch (error) {
set_room_status(`room: invite failed (${error})`);
return;
}
let payload = null;
try {
payload = await response.json();
} catch (error) {
payload = null;
}
if (!response.ok) {
const message =
payload && payload.message ? payload.message : `request failed (${response.status})`;
set_room_status(`room: invite failed (${message})`);
return;
}
set_room_status('room: invite ok');
log_output(`room invite sent for conv_id ${conv_id}`);
};

const handle_room_remove_gateway = async () => {
const auth = get_room_gateway_auth();
if (!auth) {
return;
}
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before remove');
return;
}
const remove_text = room_gateway_remove_input ? room_gateway_remove_input.value : '';
const remove_list = parse_user_id_list(remove_text);
if (!remove_list.length) {
set_room_status('room: remove user_id required');
return;
}
if (remove_list.length > 1) {
set_room_status('room: remove expects single user_id');
return;
}
set_room_status('room: removing member...');
let response;
try {
response = await fetch(`${auth.http_base_url}${room_remove_path}`, {
method: 'POST',
headers: {
'Content-Type': 'application/json',
Authorization: `Bearer ${auth.session_token}`,
},
body: JSON.stringify({ conv_id, members: remove_list }),
});
} catch (error) {
set_room_status(`room: remove failed (${error})`);
return;
}
let payload = null;
try {
payload = await response.json();
} catch (error) {
payload = null;
}
if (!response.ok) {
const message =
payload && payload.message ? payload.message : `request failed (${response.status})`;
set_room_status(`room: remove failed (${message})`);
return;
}
set_room_status('room: remove ok');
log_output(`room remove sent for conv_id ${conv_id}`);
};

const handle_room_fetch_peer_keypackages = async () => {
const auth = get_room_gateway_auth();
if (!auth) {
return;
}
const peers_text = room_peer_fetch_input ? room_peer_fetch_input.value : '';
const peer_user_ids = parse_user_id_list(peers_text);
if (!peer_user_ids.length) {
set_room_status('room: peer user_ids required');
return;
}
const count = parse_peer_fetch_count();
set_room_status('room: fetching peer keypackages...');
const keypackages = [];
for (const user_id of peer_user_ids) {
const result = await fetch_keypackage_for_user(auth, user_id, count);
if (!result.ok) {
set_room_status(`room: fetch failed for ${user_id} (${result.error})`);
return;
}
keypackages.push(result.keypackage);
}
append_textarea_lines(room_keypackages_input, keypackages);
set_room_status('room: peer keypackages loaded');
log_output('room peer keypackages loaded');
};

const handle_room_fetch_add_keypackage = async () => {
const auth = get_room_gateway_auth();
if (!auth) {
return;
}
const user_id = room_add_user_id_input ? room_add_user_id_input.value.trim() : '';
if (!user_id) {
set_room_status('room: add user_id required');
return;
}
const count = parse_peer_fetch_count();
set_room_status('room: fetching add keypackage...');
const result = await fetch_keypackage_for_user(auth, user_id, count);
if (!result.ok) {
set_room_status(`room: fetch add failed (${result.error})`);
return;
}
if (room_add_keypackage_input) {
room_add_keypackage_input.value = result.keypackage;
}
set_room_status('room: add keypackage loaded');
log_output(`room add keypackage loaded for ${user_id}`);
};

const handle_room_load_latest_welcome = async () => {
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before loading welcome');
return;
}
set_room_status('room: loading latest welcome from transcript...');
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
set_room_status('room: transcript read failed');
log_output(`room transcript read failed: ${error}`);
return;
}
const latest = select_latest_welcome_record(records);
if (!latest) {
set_room_status('room: no welcome env found');
log_output('room welcome load blocked: no welcome env found');
return;
}
if (room_welcome_env_input) {
room_welcome_env_input.value = latest.env;
}
set_room_status(`room: welcome loaded (seq=${latest.seq})`);
log_output(`room welcome loaded (seq=${latest.seq})`);
if (room_welcome_auto_join_input && room_welcome_auto_join_input.checked) {
await handle_room_join_peer();
}
};

const handle_room_join_peer = async () => {
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before join');
return false;
}
if (!bob_participant_b64) {
set_room_status('room: need bob participant');
log_output('room join blocked: missing bob participant');
return false;
}
const env_b64 = room_welcome_env_input ? room_welcome_env_input.value.trim() : '';
if (!env_b64) {
set_room_status('room: need welcome env');
log_output('room join blocked: missing welcome env');
return false;
}
const unpacked = unpack_dm_env(env_b64);
if (!unpacked || unpacked.kind !== 1) {
set_room_status('room: expected welcome env (kind=1)');
log_output('room join blocked: invalid welcome env');
return false;
}
set_room_status('room: joining peer...');
await ensure_wasm_ready();
const result = await dm_join(bob_participant_b64, unpacked.payload_b64);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_room_status('room: join failed');
log_output(`room join failed: ${error_text}`);
return false;
}
bob_participant_b64 = result.participant_b64;
bob_has_joined = true;
set_room_status('room: peer joined (waiting for commit echo)');
log_output('room peer applied welcome');
const drained = await drain_handshake_buffer('handshake (room post-welcome)');
if (!drained.ok) {
log_output(`room handshake buffer stalled: ${drained.error || drained.stalled_reason}`);
}
return true;
};

const handle_room_send_app = async () => {
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before send');
return;
}
const participant = resolve_room_participant('send');
if (!participant) {
return;
}
const plaintext = room_send_plaintext_input ? room_send_plaintext_input.value : '';
if (!plaintext) {
set_room_status('room: app plaintext required');
log_output('room send blocked: missing plaintext');
return;
}
set_room_status(`room: encrypting app as ${participant.label}`);
await ensure_wasm_ready();
const enc_result = await dm_encrypt(participant.participant_b64, plaintext);
if (!enc_result || !enc_result.ok) {
const error_text = enc_result && enc_result.error ? enc_result.error : 'unknown error';
set_room_status('room: app encrypt failed');
log_output(`room app encrypt failed: ${error_text}`);
return;
}
if (participant.label === 'alice') {
alice_participant_b64 = enc_result.participant_b64;
} else {
bob_participant_b64 = enc_result.participant_b64;
}
const app_env_b64 = pack_dm_env(3, enc_result.ciphertext_b64);
set_outbox_envs({ app_env_b64 });
dispatch_gateway_send_env(conv_id, app_env_b64);
dispatch_conv_preview_updated(conv_id, `me: ${plaintext}`);
set_room_status(`room: app sent as ${participant.label}`);
log_output(`room app env sent for conv_id ${conv_id}`);
};

const set_room_decrypt_output = (msg_id, plaintext) => {
if (room_decrypt_msg_id_output) {
room_decrypt_msg_id_output.value = msg_id ? String(msg_id) : '';
}
if (room_decrypt_plaintext_output) {
room_decrypt_plaintext_output.value = plaintext || '';
}
};

const handle_room_decrypt_latest_app = async () => {
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before decrypt');
return;
}
const participant = resolve_room_participant('decrypt');
if (!participant) {
return;
}
set_room_status('room: loading transcript app env');
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
set_room_status('room: transcript read failed');
log_output(`room transcript read failed: ${error}`);
return;
}
const latest = select_latest_app_record(records);
if (!latest) {
set_room_status('room: no app env found');
log_output('room decrypt blocked: no app env found');
return;
}
const unpacked = unpack_dm_env(latest.env);
if (!unpacked || unpacked.kind !== 3) {
set_room_status('room: latest app env invalid');
log_output('room decrypt blocked: latest app env invalid');
return;
}
set_room_status(`room: decrypting app seq=${latest.seq}`);
const dec_result = await dm_decrypt(participant.participant_b64, unpacked.payload_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
set_room_status('room: app decrypt failed');
log_output(`room app decrypt failed: ${error_text}`);
return;
}
if (participant.label === 'alice') {
alice_participant_b64 = dec_result.participant_b64;
} else {
bob_participant_b64 = dec_result.participant_b64;
}
set_room_decrypt_output(latest.msg_id, dec_result.plaintext);
dispatch_conv_preview_updated(conv_id, `peer: ${dec_result.plaintext}`);
set_room_status(`room: app decrypted (seq=${latest.seq})`);
log_output(`room app decrypted (seq=${latest.seq})`);
};

const build_phase5_steps = () => ([
{
key: 'subscribe_wait',
label: 'Subscribe / wait',
status: 'pending',
details: 'pending',
},
{
key: 'join',
label: 'Join from welcome',
status: 'pending',
details: 'pending',
},
{
key: 'drain',
label: 'Drain handshakes',
status: 'pending',
details: 'pending',
},
{
key: 'decrypt',
label: 'Decrypt latest app',
status: 'pending',
details: 'pending',
},
{
key: 'reply',
label: 'Optional reply',
status: 'pending',
details: 'pending',
},
{
key: 'report',
label: 'Report',
status: 'pending',
details: 'pending',
},
]);

const build_phase5_coexist_steps = () => ([
{
key: 'parse',
label: 'Parse CLI blocks',
status: 'pending',
details: 'pending',
},
{
key: 'subscribe_wait',
label: 'Subscribe / wait',
status: 'pending',
details: 'pending',
},
{
key: 'dm',
label: 'Run DM proof',
status: 'pending',
details: 'pending',
},
{
key: 'room',
label: 'Run room proof',
status: 'pending',
details: 'pending',
},
{
key: 'peer_tokens',
label: 'Peer tokens',
status: 'pending',
details: 'pending',
},
{
key: 'active_coexist',
label: 'Active coexist',
status: 'pending',
details: 'pending',
},
{
key: 'report',
label: 'Combined report',
status: 'pending',
details: 'pending',
},
]);

const render_phase5_timeline = (steps, timeline_container) => {
if (timeline_container === null) {
return;
}
const target = timeline_container || room_phase5_proof_timeline;
if (!target) {
return;
}
target.innerHTML = '';
steps.forEach((step) => {
const row = document.createElement('div');
row.className = 'phase5_step';
const status = document.createElement('span');
status.className = `phase5_step_status phase5_step_status_${step.status}`;
status.textContent = step.status;
const label = document.createElement('span');
label.className = 'phase5_step_label';
label.textContent = step.label;
const details = document.createElement('span');
details.className = 'phase5_step_details';
details.textContent = step.details || '';
row.appendChild(status);
row.appendChild(document.createTextNode(' '));
row.appendChild(label);
row.appendChild(document.createTextNode(' - '));
row.appendChild(details);
target.appendChild(row);
});
};

const set_phase5_step_status = (steps, key, status, details, timeline_container) => {
const step = steps.find((entry) => entry.key === key);
if (!step) {
return;
}
step.status = status;
if (details !== undefined) {
step.details = details;
}
render_phase5_timeline(steps, timeline_container);
};

const set_phase5_report_text = (value, report_output) => {
if (report_output === null) {
return;
}
const target = report_output || room_phase5_proof_report;
if (!target) {
return;
}
target.value = value || '';
};

const build_bidirectional_cli_command = (command_name, conv_id, token_web_to_cli, token_cli_to_web) => {
if (!command_name || !conv_id || !token_web_to_cli || !token_cli_to_web) {
return '';
}
return `python -m cli_app.mls_poc ${command_name} --conv-id ${conv_id} --wait-peer-app --peer-app-expected ${token_web_to_cli} --send-peer-token ${token_cli_to_web}`;
};

const build_coexist_cli_command = (
dm_conv_id,
room_conv_id,
dm_token_web_to_cli,
room_token_web_to_cli,
dm_token_cli_to_web,
room_token_cli_to_web
) => {
if (!dm_conv_id || !room_conv_id) {
return '';
}
if (!dm_token_web_to_cli || !room_token_web_to_cli || !dm_token_cli_to_web || !room_token_cli_to_web) {
return '';
}
return [
'python -m cli_app.mls_poc gw-phase5-coexist-proof',
`--wait-peer-app`,
`--dm-conv-id ${dm_conv_id}`,
`--room-conv-id ${room_conv_id}`,
`--dm-peer-app-expected ${dm_token_web_to_cli}`,
`--room-peer-app-expected ${room_token_web_to_cli}`,
`--dm-send-peer-token ${dm_token_cli_to_web}`,
`--room-send-peer-token ${room_token_cli_to_web}`,
].join(' ');
};

const parse_peer_wait_timeout_ms = (peer_wait_timeout_input) => {
const parsed_value = Number.parseInt(
peer_wait_timeout_input ? peer_wait_timeout_input.value : '',
10
);
return Number.isInteger(parsed_value) ? parsed_value : phase5_peer_wait_default_timeout_ms;
};

const format_phase5_report = (report) => {
const lines = [
'phase5 proof report:',
`conv_id: ${report.conv_id || '(none)'}`,
`digest: ${report.digest_status || 'digest missing'}`,
`events_used: ${Number.isInteger(report.events_used) ? report.events_used : 'n/a'}`,
`events_source: ${report.events_source || 'unknown'}`,
`participant_scoped: ${report.participant_scoped ? 'true' : 'false'}`,
`participant_created: ${report.participant_created ? 'true' : 'false'}`,
`wait_last_seq_seen: ${
Number.isInteger(report.wait_last_seq_seen) ? report.wait_last_seq_seen : 'n/a'
}`,
`wait_quiescent: ${report.wait_quiescent ? 'true' : 'false'}`,
`wait_expected_handshake_seen: ${report.wait_expected_handshake_seen ? 'true' : 'false'}`,
`welcome_seq: ${Number.isInteger(report.welcome_seq) ? report.welcome_seq : 'n/a'}`,
`last_handshake_applied_seq: ${
Number.isInteger(report.last_handshake_applied_seq) ? report.last_handshake_applied_seq : 'n/a'
}`,
`handshake_apply_participant: ${report.handshake_apply_participant || 'unknown'}`,
`handshake_buffered_count: ${
Number.isInteger(report.handshake_buffered_count) ? report.handshake_buffered_count : 'n/a'
}`,
`handshake_apply_failures: ${
Array.isArray(report.handshake_apply_failures) && report.handshake_apply_failures.length
? report.handshake_apply_failures.join('; ')
: '(none)'
}`,
`handshake_dependency_stalls: ${
Number.isInteger(report.handshake_dependency_stalls) ? report.handshake_dependency_stalls : 'n/a'
}`,
`handshake_replay_retry_used: ${report.handshake_replay_retry_used ? 'true' : 'false'}`,
`app_seq: ${Number.isInteger(report.app_seq) ? report.app_seq : 'n/a'}`,
`decrypted_plaintext: ${report.decrypted_plaintext || '(none)'}`,
`expected_plaintext: ${report.expected_plaintext || '(none)'}`,
`peer_wait_enabled: ${report.peer_wait_enabled ? 'true' : 'false'}`,
`peer_wait_status: ${report.peer_wait_status || '(none)'}`,
`peer_app_seq: ${Number.isInteger(report.peer_app_seq) ? report.peer_app_seq : 'n/a'}`,
`peer_decrypted_plaintext: ${report.peer_decrypted_plaintext || '(none)'}`,
`peer_expected_plaintext: ${report.peer_expected_plaintext || '(none)'}`,
`token_web_to_cli: ${report.token_web_to_cli || '(none)'}`,
`token_cli_to_web_expected: ${report.token_cli_to_web_expected || '(none)'}`,
`token_cli_to_web_result: ${report.token_cli_to_web_result || '(none)'}`,
`cli_command_bidirectional: ${report.cli_command_bidirectional || '(none)'}`,
];
if (report.expected_plaintext_result) {
lines.push(`expected_plaintext_result: ${report.expected_plaintext_result}`);
}
if (report.peer_expected_plaintext_result) {
lines.push(`peer_expected_plaintext_result: ${report.peer_expected_plaintext_result}`);
}
lines.push(`auto_reply_attempted: ${report.auto_reply_attempted ? 'yes' : 'no'}`);
lines.push(`reply_plaintext: ${report.reply_plaintext || '(none)'}`);
lines.push(`start_ms: ${Number.isInteger(report.start_ms) ? report.start_ms : 'n/a'}`);
lines.push(`end_ms: ${Number.isInteger(report.end_ms) ? report.end_ms : 'n/a'}`);
lines.push(`duration_ms: ${Number.isInteger(report.duration_ms) ? report.duration_ms : 'n/a'}`);
if (report.error) {
lines.push(`error: ${report.error}`);
}
if (report.peer_wait_error) {
lines.push(`peer_wait_error: ${report.peer_wait_error}`);
}
return lines.join('\n');
};

const format_phase5_summary_line = (label, report, result_label) => {
const conv_id = report && report.conv_id ? report.conv_id : '(none)';
const digest = report && report.digest_status ? report.digest_status : 'digest missing';
const welcome_seq =
report && Number.isInteger(report.welcome_seq) ? report.welcome_seq : 'n/a';
const handshake_seq =
report && Number.isInteger(report.last_handshake_applied_seq)
? report.last_handshake_applied_seq
: 'n/a';
const app_seq = report && Number.isInteger(report.app_seq) ? report.app_seq : 'n/a';
const proof_app_seq =
report && Number.isInteger(report.proof_app_seq) ? report.proof_app_seq : 'n/a';
return `${label}: conv_id=${conv_id} digest=${digest} welcome_seq=${welcome_seq} last_handshake_applied_seq=${handshake_seq} app_seq=${app_seq} result=${result_label}`;
};

const compute_phase5_result_label = (report) => {
if (!report) {
return 'SKIP';
}
const expected_ok =
!report.expected_plaintext_result || report.expected_plaintext_result === 'PASS';
const peer_wait_failed = report.peer_wait_enabled && report.peer_wait_status === 'FAIL';
if (report.error || !expected_ok || peer_wait_failed) {
return 'FAIL';
}
return 'PASS';
};

const format_phase5_coexist_section = (label, report, result_label) => {
const conv_id = report && report.conv_id ? report.conv_id : '(none)';
const digest = report && report.digest_status ? report.digest_status : 'digest missing';
const welcome_seq =
report && Number.isInteger(report.welcome_seq) ? report.welcome_seq : 'n/a';
const handshake_seq =
report && Number.isInteger(report.last_handshake_applied_seq)
? report.last_handshake_applied_seq
: 'n/a';
const app_seq = report && Number.isInteger(report.app_seq) ? report.app_seq : 'n/a';
const plaintext_or_error =
report && report.error
? `error: ${report.error}`
: report && report.decrypted_plaintext
? report.decrypted_plaintext
: '(none)';
const lines = [
`${label}:`,
`result: ${result_label}`,
`conv_id: ${conv_id}`,
`digest: ${digest}`,
`welcome_seq: ${welcome_seq}`,
`last_handshake_applied_seq: ${handshake_seq}`,
`handshake_apply_participant: ${report && report.handshake_apply_participant
? report.handshake_apply_participant
: 'unknown'}`,
`handshake_buffered_count: ${
report && Number.isInteger(report.handshake_buffered_count)
? report.handshake_buffered_count
: 'n/a'
}`,
`handshake_apply_failures: ${
report && Array.isArray(report.handshake_apply_failures) && report.handshake_apply_failures.length
? report.handshake_apply_failures.join('; ')
: '(none)'
}`,
`app_seq: ${app_seq}`,
`proof_app_seq: ${proof_app_seq}`,
`plaintext_or_error: ${plaintext_or_error}`,
`peer_wait_enabled: ${report && report.peer_wait_enabled ? 'true' : 'false'}`,
`peer_wait_status: ${report && report.peer_wait_status ? report.peer_wait_status : '(none)'}`,
`peer_app_seq: ${report && Number.isInteger(report.peer_app_seq) ? report.peer_app_seq : 'n/a'}`,
`peer_decrypted_plaintext: ${report && report.peer_decrypted_plaintext
? report.peer_decrypted_plaintext
: '(none)'}`,
`token_web_to_cli: ${report && report.token_web_to_cli ? report.token_web_to_cli : '(none)'}`,
`token_cli_to_web_expected: ${report && report.token_cli_to_web_expected
? report.token_cli_to_web_expected
: '(none)'}`,
`token_cli_to_web_result: ${report && report.token_cli_to_web_result
? report.token_cli_to_web_result
: '(none)'}`,
`cli_command_bidirectional: ${report && report.cli_command_bidirectional
? report.cli_command_bidirectional
: '(none)'}`,
`auto_reply_attempted: ${report && report.auto_reply_attempted ? 'yes' : 'no'}`,
`duration_ms: ${report && Number.isInteger(report.duration_ms) ? report.duration_ms : 'n/a'}`,
];
return lines.join('\n');
};

const format_phase5_active_coexist_section = (summary) => {
if (!summary) {
return 'active_coexist: missing';
}
const status = summary.status || 'FAIL';
const reason_suffix = summary.reason ? ` (${summary.reason})` : '';
const lines = [`active_coexist: ${status}${reason_suffix}`];
const append_conv_line = (label, entry) => {
if (!entry) {
lines.push(`${label}: missing`);
return;
}
const sent_count = Number.isInteger(entry.sent_count) ? entry.sent_count : 0;
const last_seq = Number.isInteger(entry.last_app_seq) ? entry.last_app_seq : 'n/a';
const decrypt_ok = entry.decrypt_ok ? 'true' : 'false';
const digest = entry.digest || 'digest missing';
lines.push(
`${label}: sent_count=${sent_count} last_app_seq=${last_seq} decrypt_ok=${decrypt_ok} digest=${digest}`
);
};
append_conv_line('DM', summary.dm);
append_conv_line('ROOM', summary.room);
if (summary.error) {
lines.push(`error: ${summary.error}`);
}
return lines.join('\n');
};

const format_phase5_coexist_peer_tokens = (summary) => {
if (!summary) {
return 'coexist_peer_tokens: missing';
}
const status = summary.status || 'FAIL';
const reason_suffix = summary.reason ? ` (${summary.reason})` : '';
const lines = [`coexist_peer_tokens: ${status}${reason_suffix}`];
lines.push(`cli_command: ${summary.cli_command || '(none)'}`);
const append_conv_line = (label, entry) => {
if (!entry) {
lines.push(`${label}: missing`);
return;
}
const peer_app_seq = Number.isInteger(entry.peer_app_seq) ? entry.peer_app_seq : 'n/a';
const reason_suffix = entry.reason ? ` (${entry.reason})` : '';
lines.push(
`${label}: status=${entry.status || 'FAIL'}${reason_suffix} token_web_to_cli=${entry.token_web_to_cli || '(none)'} ` +
`token_cli_to_web_expected=${entry.token_cli_to_web_expected || '(none)'} ` +
`token_cli_to_web_result=${entry.token_cli_to_web_result || '(none)'} ` +
`peer_app_seq=${peer_app_seq} peer_decrypted_plaintext=${entry.peer_decrypted_plaintext || '(none)'}`
);
if (entry.error) {
lines.push(`${label} error: ${entry.error}`);
}
};
append_conv_line('DM', summary.dm);
append_conv_line('ROOM', summary.room);
if (summary.error) {
lines.push(`error: ${summary.error}`);
}
return lines.join('\n');
};

const format_phase5_coexist_report = (summary) => {
const dm_result = summary.dm_report ? summary.dm_result : 'SKIP';
const room_result = summary.room_report ? summary.room_result : 'FAIL';
const overall_result = summary.overall_result || 'FAIL';
const lines = [
'phase5 coexist proof report:',
`start_ms: ${Number.isInteger(summary.start_ms) ? summary.start_ms : 'n/a'}`,
`end_ms: ${Number.isInteger(summary.end_ms) ? summary.end_ms : 'n/a'}`,
`duration_ms: ${Number.isInteger(summary.duration_ms) ? summary.duration_ms : 'n/a'}`,
`auto_reply_attempted: ${summary.auto_reply_attempted ? 'yes' : 'no'}`,
`overall: ${overall_result}`,
'',
summary.dm_report
? format_phase5_coexist_section('DM', summary.dm_report, dm_result)
: 'DM: skipped (room-only)',
'',
summary.room_report
? format_phase5_coexist_section('ROOM', summary.room_report, room_result)
: 'ROOM: missing',
'',
summary.coexist_peer_tokens
? format_phase5_coexist_peer_tokens(summary.coexist_peer_tokens)
: 'coexist_peer_tokens: missing',
'',
summary.active_coexist
? format_phase5_active_coexist_section(summary.active_coexist)
: 'active_coexist: missing',
];
if (summary.error) {
lines.push('');
lines.push(`error: ${summary.error}`);
}
return lines.join('\n');
};

const resolve_phase5_cli_block = () => {
const cli_block_text = cli_block_input ? cli_block_input.value : '';
if (!cli_block_text || !cli_block_text.trim()) {
return null;
}
const { parsed, found_keys } = parse_cli_block(cli_block_text);
if (!found_keys.length) {
return null;
}
return parsed;
};

const resolve_phase5_inputs = async (options) => {
const allow_cli_block_input = options.allow_cli_block_input !== false;
const cli_block = options.cli_block_override || (allow_cli_block_input ? resolve_phase5_cli_block() : null);
const status_prefix = options.status_prefix || 'proof';
const conv_id_resolver = options.conv_id_resolver;
let transcript = null;
let source_note = '';
let conv_id = conv_id_resolver();
if (last_imported_transcript) {
const allow_import = Boolean(options.allow_imported_any);
if (allow_import || last_imported_transcript.conv_id === conv_id) {
transcript = last_imported_transcript;
conv_id = last_imported_transcript.conv_id;
source_note = `imported transcript (${last_imported_digest_note})`;
}
}
if (!transcript) {
if (!conv_id && cli_block && cli_block.conv_id) {
conv_id = normalize_conv_id(cli_block.conv_id);
}
if (!conv_id) {
return { ok: false, error: 'missing conv_id' };
}
options.set_status_fn(`${status_prefix}: loading transcript from db...`);
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
options.set_status_fn(`${status_prefix}: transcript db read failed`);
log_output(`${status_prefix} transcript read failed: ${error}`);
}
if (records.length) {
transcript = build_transcript_from_records(conv_id, records);
source_note = `transcript db (${records.length} events)`;
}
}
if (cli_block && cli_block.conv_id) {
const normalized = normalize_conv_id(cli_block.conv_id);
if (normalized !== '(none)') {
if (source_note) {
source_note = `${source_note}; cli_block conv_id override`;
}
conv_id = normalized;
}
}
if (!transcript && !cli_block) {
return { ok: false, error: 'missing transcript or cli block' };
}
return {
ok: true,
conv_id,
transcript,
cli_block,
source_note,
};
};

const build_phase5_bundle_cli_block = (bundle_section) => {
const transcript = bundle_section && bundle_section.transcript ? bundle_section.transcript : null;
const events = transcript && Array.isArray(transcript.events) ? transcript.events : [];
const proof_app_seq_value =
bundle_section && Number.isInteger(bundle_section.proof_app_seq)
? bundle_section.proof_app_seq
: null;
const block = {
conv_id: transcript && typeof transcript.conv_id === 'string' ? transcript.conv_id : '',
};
if (proof_app_seq_value !== null) {
const matched_app = find_transcript_event_by_seq(events, proof_app_seq_value, 3);
if (matched_app) {
block.app_env_b64 = matched_app.env;
block.proof_app_seq = proof_app_seq_value;
}
}
return block;
};

const run_offline_peer_tokens = async (bundle_section, conv_id, report, set_status_fn, label) => {
const result = {
status: 'FAIL',
reason: '',
token_web_to_cli: '',
token_cli_to_web_expected: '',
token_cli_to_web_result: '',
peer_app_seq: null,
peer_decrypted_plaintext: '',
error: '',
};
if (!bundle_section || !bundle_section.peer_tokens) {
result.status = 'SKIP';
result.reason = 'peer_tokens missing';
result.error = result.reason;
return result;
}
const peer_tokens = bundle_section.peer_tokens;
result.token_web_to_cli = peer_tokens.peer_app_expected || '';
result.token_cli_to_web_expected = peer_tokens.sent_peer_token_plaintext || '';
const proof_app_seq_value = Number.isInteger(bundle_section.proof_app_seq)
? bundle_section.proof_app_seq
: report && Number.isInteger(report.proof_app_seq)
? report.proof_app_seq
: null;
const peer_app_seq_value =
Number.isInteger(peer_tokens.peer_app_seq) ? peer_tokens.peer_app_seq : null;
const sent_peer_token_seq_value =
Number.isInteger(peer_tokens.sent_peer_token_seq) ? peer_tokens.sent_peer_token_seq : null;
if (!peer_app_seq_value && !sent_peer_token_seq_value) {
result.status = 'SKIP';
result.reason = 'bundle missing peer token events';
result.error = result.reason;
return result;
}
const transcript = bundle_section.transcript;
const records = build_phase5_records_from_transcript(transcript || { events: [] });
const missing_seqs = [];
const target_seqs = [];
for (const seq_value of [peer_app_seq_value, sent_peer_token_seq_value]) {
if (!Number.isInteger(seq_value)) {
continue;
}
const record_match =
records.find((entry) => entry && entry.seq === seq_value && typeof entry.env === 'string') || null;
if (!record_match) {
missing_seqs.push(seq_value);
} else {
const env_meta = parse_live_inbox_env(record_match.env);
if (!env_meta || env_meta.kind !== 3) {
missing_seqs.push(seq_value);
} else {
target_seqs.push(seq_value);
}
}
}
if (missing_seqs.length) {
result.status = 'SKIP';
result.reason = 'bundle missing peer token events';
result.error = result.reason;
return result;
}
if (Number.isInteger(proof_app_seq_value)) {
const invalid_order = target_seqs.some((seq_value) => seq_value <= proof_app_seq_value);
if (invalid_order) {
result.status = 'FAIL';
result.error = 'peer token seq before proof app';
return result;
}
}
if (typeof set_status_fn === 'function') {
set_status_fn(`coexist ${label} peer tokens: offline validate`);
}
return with_phase5_conv_scope(conv_id, { ensure_bob_participant: true }, async () => {
const ordered_targets = [...target_seqs].sort((left, right) => left - right);
const decrypted_by_seq = new Map();
for (const seq_value of ordered_targets) {
const expected_plaintext =
seq_value === peer_app_seq_value
? peer_tokens.peer_app_expected
: peer_tokens.sent_peer_token_plaintext;
const decrypt_result = await decrypt_app_env_from_records(
records,
seq_value,
expected_plaintext,
`offline peer tokens (${label})`
);
if (!decrypt_result.ok && decrypt_result.error) {
result.error = decrypt_result.error;
return result;
}
decrypted_by_seq.set(seq_value, decrypt_result);
}
if (peer_app_seq_value !== null) {
const peer_app_result = decrypted_by_seq.get(peer_app_seq_value);
if (peer_app_result) {
result.peer_app_seq = peer_app_seq_value;
result.peer_decrypted_plaintext = peer_app_result.plaintext || '';
}
}
const token_result = sent_peer_token_seq_value !== null
? decrypted_by_seq.get(sent_peer_token_seq_value)
: null;
const peer_app_match =
peer_app_seq_value === null
? true
: Boolean(decrypted_by_seq.get(peer_app_seq_value) && decrypted_by_seq.get(peer_app_seq_value).match);
const token_match =
sent_peer_token_seq_value === null
? true
: Boolean(token_result && token_result.match);
result.token_cli_to_web_result = token_match ? 'MATCH' : 'MISMATCH';
result.status = peer_app_match && token_match ? 'PASS' : 'FAIL';
if (!peer_app_match) {
result.error = result.error || 'peer_app_expected mismatch';
}
if (!token_match) {
result.error = result.error || 'token_cli_to_web mismatch';
}
return result;
});
};

const resolve_phase5_bundle_inputs = (bundle_section) => {
if (!bundle_section || !bundle_section.transcript) {
return { ok: false, error: 'bundle transcript missing' };
}
const conv_id = normalize_conv_id(bundle_section.transcript.conv_id);
if (!conv_id || conv_id === '(none)') {
return { ok: false, error: 'bundle conv_id missing' };
}
expected_plaintext = bundle_section.expected_plaintext || '';
set_expected_plaintext_input();
return {
ok: true,
conv_id,
transcript: bundle_section.transcript,
cli_block: build_phase5_bundle_cli_block(bundle_section),
source_note: 'coexist bundle',
};
};

const resolve_phase5_expected_plaintext = (cli_block) => {
if (cli_block && cli_block.expected_plaintext !== undefined) {
return cli_block.expected_plaintext;
}
return expected_plaintext || '';
};

const build_phase5_cli_block_from_envs = (conv_id, envs) => ({
conv_id,
welcome_env_b64: envs.welcome_env_b64 || '',
commit_env_b64: envs.commit_env_b64 || '',
app_env_b64: envs.app_env_b64 || '',
expected_plaintext: '',
});

const extract_phase5_envs_from_records = (conv_id, records) => {
const transcript = build_transcript_from_records(conv_id, records);
const events = transcript && Array.isArray(transcript.events) ? transcript.events : [];
const latest_welcome = pick_latest_env(events, 1);
const latest_commit = pick_latest_env(events, 2);
const latest_app = pick_latest_env(events, 3);
return {
transcript,
events,
welcome_env_b64: latest_welcome ? latest_welcome.env : '',
commit_env_b64: latest_commit ? latest_commit.env : '',
app_env_b64: latest_app ? latest_app.env : '',
};
};

const read_phase5_transcript_snapshot = async (conv_id) => {
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
return {
ok: false,
error: `transcript read failed for conv_id ${conv_id}`,
transcript: null,
events: [],
envs: {
welcome_env_b64: '',
commit_env_b64: '',
app_env_b64: '',
},
record_count: 0,
};
}
const extracted = extract_phase5_envs_from_records(conv_id, records);
return {
ok: true,
transcript: extracted.transcript,
events: extracted.events || [],
envs: {
welcome_env_b64: extracted.welcome_env_b64 || '',
commit_env_b64: extracted.commit_env_b64 || '',
app_env_b64: extracted.app_env_b64 || '',
},
record_count: records.length,
};
};

const build_phase5_records_from_transcript = (transcript) => {
const events = transcript && Array.isArray(transcript.events) ? transcript.events : [];
const records = [];
for (const event of events) {
if (!event || typeof event.env !== 'string') {
continue;
}
records.push({
seq: event.seq,
msg_id: event.msg_id,
env: event.env,
});
}
return records;
};

const read_phase5_records_with_fallback = async (conv_id, transcript) => {
let records = [];
try {
records = await read_transcript_records_by_conv_id(conv_id);
} catch (error) {
records = [];
}
if (records.length) {
return records;
}
if (!transcript) {
return records;
}
return build_phase5_records_from_transcript(transcript);
};

const read_phase5_transcript_snapshot_with_fallback = async (conv_id, transcript) => {
const snapshot = await read_phase5_transcript_snapshot(conv_id);
if (snapshot.ok && snapshot.record_count > 0) {
return { ...snapshot, source: 'transcript db' };
}
if (!transcript) {
return snapshot;
}
const records = build_phase5_records_from_transcript(transcript);
const extracted = extract_phase5_envs_from_records(conv_id, records);
return {
ok: true,
transcript: extracted.transcript,
events: extracted.events || [],
envs: {
welcome_env_b64: extracted.welcome_env_b64 || '',
commit_env_b64: extracted.commit_env_b64 || '',
app_env_b64: extracted.app_env_b64 || '',
},
record_count: records.length,
source: 'fallback transcript',
};
};

const count_phase5_envs_in_records = (records) => {
const counts = {
welcome: 0,
handshake: 0,
app: 0,
total: 0,
};
let last_seq_seen = null;
for (const record of records) {
if (!record || typeof record.env !== 'string') {
continue;
}
counts.total += 1;
if (Number.isInteger(record.seq)) {
last_seq_seen = last_seq_seen === null ? record.seq : Math.max(last_seq_seen, record.seq);
}
const env_meta = parse_live_inbox_env(record.env);
if (!env_meta) {
continue;
}
if (env_meta.kind === 1) {
counts.welcome += 1;
} else if (env_meta.kind === 2) {
counts.handshake += 1;
} else if (env_meta.kind === 3) {
counts.app += 1;
}
}
return { counts, last_seq_seen };
};

const format_phase5_wait_details = (wait_result) => {
if (!wait_result || !wait_result.counts) {
return 'no transcript data';
}
const last_seq_text =
Number.isInteger(wait_result.last_seq_seen) ? wait_result.last_seq_seen : 'n/a';
return `welcome=${wait_result.counts.welcome} handshake=${wait_result.counts.handshake} app=${wait_result.counts.app} last_seq=${last_seq_text}`;
};

const subscribe_and_wait_for_phase5 = async (conv_id, opts) => {
const options = opts || {};
const require_app = options.require_app !== false;
const timeout_ms = Number.isInteger(options.timeout_ms) ? options.timeout_ms : 8000;
const initial_timeout_ms =
Number.isInteger(options.initial_timeout_ms) ? options.initial_timeout_ms : 1500;
const poll_interval_ms =
Number.isInteger(options.poll_interval_ms) ? options.poll_interval_ms : 400;
const handshake_grace_ms =
Number.isInteger(options.handshake_grace_ms) ? options.handshake_grace_ms : 800;
const expected_handshake_env_b64 =
typeof options.expected_handshake_env_b64 === 'string' ? options.expected_handshake_env_b64 : '';
const require_handshake_min =
Number.isInteger(options.require_handshake_min) ? options.require_handshake_min : 0;
const quiescent_polls =
Number.isInteger(options.quiescent_polls) ? options.quiescent_polls : 0;
const quiescent_interval_ms =
Number.isInteger(options.quiescent_interval_ms) ? options.quiescent_interval_ms : 300;
const read_records_fn =
typeof options.read_records_fn === 'function'
? options.read_records_fn
: read_transcript_records_by_conv_id;
const deadline_ms = Date.now() + timeout_ms;
let welcome_seen_ms = null;
let last_counts = {
welcome: 0,
handshake: 0,
app: 0,
total: 0,
};
let last_seq_seen = null;
let expected_handshake_seen = false;
let quiescent_streak = 0;
let quiescent_seq = null;

const build_missing = (counts) => {
const missing = [];
if (!counts || counts.welcome === 0) {
missing.push('welcome');
}
if (require_app && (!counts || counts.app === 0)) {
missing.push('app');
}
if (require_handshake_min > 0 && (!counts || counts.handshake < require_handshake_min)) {
missing.push('handshake');
}
if (expected_handshake_env_b64 && !expected_handshake_seen) {
missing.push('expected_handshake');
}
if (quiescent_polls > 0 && quiescent_streak < quiescent_polls) {
missing.push('quiescent');
}
return missing;
};

const should_wait_for_handshake = (counts) => {
if (handshake_grace_ms <= 0) {
return false;
}
if (require_handshake_min > 0 || expected_handshake_env_b64) {
return false;
}
if (!counts || counts.handshake > 0 || welcome_seen_ms === null) {
return false;
}
return Date.now() - welcome_seen_ms < handshake_grace_ms;
};

const read_counts = async () => {
let records = [];
try {
records = await read_records_fn(conv_id);
} catch (error) {
records = [];
}
const summary = count_phase5_envs_in_records(records);
last_counts = summary.counts;
last_seq_seen = summary.last_seq_seen;
if (summary.counts.welcome > 0 && welcome_seen_ms === null) {
welcome_seen_ms = Date.now();
}
expected_handshake_seen = expected_handshake_env_b64
? records.some((record) => record && record.env === expected_handshake_env_b64)
: false;
if (quiescent_polls > 0) {
if (quiescent_seq === summary.last_seq_seen) {
quiescent_streak += 1;
} else {
quiescent_seq = summary.last_seq_seen;
quiescent_streak = 1;
}
}
return summary;
};

const wait_loop = async (deadline_limit_ms) => {
while (Date.now() < deadline_limit_ms) {
await read_counts();
const missing = build_missing(last_counts);
if (!missing.length && !should_wait_for_handshake(last_counts)) {
return {
ok: true,
missing,
counts: last_counts,
last_seq_seen,
wait_quiescent: quiescent_polls > 0 ? quiescent_streak >= quiescent_polls : false,
wait_expected_handshake_seen: expected_handshake_seen,
};
}
await new Promise((resolve) => {
setTimeout(resolve, quiescent_polls > 0 ? quiescent_interval_ms : poll_interval_ms);
});
}
const missing = build_missing(last_counts);
return {
ok: false,
missing,
counts: last_counts,
last_seq_seen,
wait_quiescent: quiescent_polls > 0 ? quiescent_streak >= quiescent_polls : false,
wait_expected_handshake_seen: expected_handshake_seen,
};
};

dispatch_gateway_subscribe(conv_id);
const initial_deadline_ms = Math.min(Date.now() + initial_timeout_ms, deadline_ms);
const initial_result = await wait_loop(initial_deadline_ms);
if (initial_result.ok) {
return initial_result;
}
const initial_missing = initial_result.missing || [];
if (initial_missing.includes('welcome') || (require_app && initial_missing.includes('app'))) {
dispatch_gateway_subscribe(conv_id, 1);
}
const final_result = await wait_loop(deadline_ms);
return final_result;
};

const build_phase5_steps_debug = () => build_phase5_steps().map((step) => ({
key: step.key,
status: step.status,
details: step.details,
}));

const run_phase5_proof_core = async (options) => {
const status_prefix = options.status_prefix || 'proof';
const on_step = typeof options.on_step === 'function' ? options.on_step : null;
const steps_debug = build_phase5_steps_debug();
const proof_start_ms = Date.now();
const proof_report = {
conv_id: '',
digest_status: 'digest missing',
events_used: 0,
events_source: '',
wait_last_seq_seen: null,
wait_quiescent: false,
wait_expected_handshake_seen: false,
welcome_seq: null,
last_handshake_applied_seq: null,
handshake_apply_participant: 'unknown',
handshake_buffered_count: 0,
handshake_apply_failures: [],
handshake_dependency_stalls: 0,
handshake_replay_retry_used: false,
app_seq: null,
proof_app_seq: null,
decrypted_plaintext: '',
expected_plaintext: '',
expected_plaintext_result: '',
auto_reply_attempted: false,
reply_plaintext: '',
peer_wait_enabled: false,
peer_wait_status: '',
peer_app_seq: null,
peer_decrypted_plaintext: '',
peer_expected_plaintext: '',
peer_expected_plaintext_result: '',
peer_wait_error: '',
peer_wait_token: '',
token_web_to_cli: '',
token_cli_to_web_expected: '',
token_cli_to_web_result: '',
cli_command_bidirectional: '',
peer_wait_cli_command_name: '',
participant_scoped: false,
participant_created: false,
start_ms: proof_start_ms,
end_ms: null,
duration_ms: null,
error: '',
};
const set_status_prefixed = (message) => {
if (typeof options.set_status_fn === 'function') {
options.set_status_fn(`${status_prefix}: ${message}`);
}
};
const set_step = (key, status, details) => {
const step = steps_debug.find((entry) => entry.key === key);
if (step) {
step.status = status;
if (details !== undefined) {
step.details = details;
}
} else {
steps_debug.push({
key,
status,
details: details !== undefined ? details : '',
});
}
if (on_step) {
on_step(key, status, details);
}
};
const resolve_events_source = (source_note) => {
if (!source_note) {
return 'unknown';
}
if (source_note.includes('coexist bundle')) {
return 'bundle';
}
if (source_note.includes('imported transcript')) {
return 'imported';
}
if (source_note.includes('transcript db')) {
return 'transcript db';
}
return source_note;
};
const finalize_report = () => {
proof_report.end_ms = Date.now();
proof_report.duration_ms =
Number.isInteger(proof_report.end_ms) && Number.isInteger(proof_report.start_ms)
? proof_report.end_ms - proof_report.start_ms
: null;
};
const run_core = async () => {
const resolved = await options.resolve_inputs();
if (!resolved.ok) {
set_step('subscribe_wait', 'fail', resolved.error);
set_step('join', 'pending', 'skipped (subscribe failed)');
set_step('drain', 'pending', 'skipped (subscribe failed)');
set_step('decrypt', 'pending', 'skipped (subscribe failed)');
set_step('reply', 'pending', 'skipped (subscribe failed)');
set_step('report', 'running', 'building report');
set_step('report', 'ok', 'report ready');
proof_report.error = resolved.error;
set_status_prefixed(resolved.error);
return proof_report;
}
proof_report.conv_id = resolved.conv_id;
if (resolved.source_note) {
set_status_prefixed(resolved.source_note);
}
const offline_transcript_mode = Boolean(
resolved.source_note && (
resolved.source_note.includes('imported transcript') ||
resolved.source_note.includes('coexist bundle')
)
);
const peer_wait_enabled = Boolean(options.peer_wait_input && options.peer_wait_input.checked);
const peer_wait_expected_plaintext = options.peer_wait_expected_input
? options.peer_wait_expected_input.value
: phase5_peer_wait_default_plaintext;
const peer_wait_timeout_ms = Number.isInteger(Number.parseInt(
options.peer_wait_timeout_input ? options.peer_wait_timeout_input.value : '',
10
))
? Number.parseInt(options.peer_wait_timeout_input.value, 10)
: phase5_peer_wait_default_timeout_ms;
proof_report.peer_wait_enabled = peer_wait_enabled;
proof_report.peer_expected_plaintext = peer_wait_expected_plaintext || '';
proof_report.peer_wait_cli_command_name =
typeof options.peer_wait_cli_command_name === 'string' ? options.peer_wait_cli_command_name : '';
const scoped_result = await with_phase5_conv_scope(proof_report.conv_id, {
ensure_bob_participant: true,
}, async (scope_note) => {
proof_report.participant_scoped = true;
proof_report.participant_created = Boolean(scope_note && scope_note.participant_created);
const handshake_participant_label = 'bob';
proof_report.handshake_apply_participant = handshake_participant_label;
const handshake_apply_failures = [];
let handshake_dependency_stalls = 0;
let handshake_replay_retry_used = false;
const record_handshake_failure = (message) => {
if (!message) {
return;
}
if (!handshake_apply_failures.includes(message)) {
handshake_apply_failures.push(message);
}
};
const resolved_transcript = resolved.transcript;
const resolved_events =
resolved_transcript && Array.isArray(resolved_transcript.events) ? resolved_transcript.events : [];
if (resolved_transcript && resolved_transcript.digest_sha256_b64) {
const computed_digest = await compute_transcript_digest(resolved_transcript);
proof_report.digest_status =
computed_digest === resolved_transcript.digest_sha256_b64 ? 'digest ok' : 'digest mismatch';
}
const cli_envs = resolved.cli_block || {
welcome_env_b64: '',
commit_env_b64: '',
app_env_b64: '',
expected_plaintext: '',
};
const resolved_expected_plaintext = resolve_phase5_expected_plaintext(cli_envs);
proof_report.expected_plaintext = resolved_expected_plaintext || '';
if (cli_envs.expected_plaintext !== undefined) {
expected_plaintext = cli_envs.expected_plaintext;
set_expected_plaintext_input();
}
set_step('subscribe_wait', 'running', 'subscribing to transcript');
const expected_commit_env_b64 =
cli_envs.commit_env_b64 && cli_envs.commit_env_b64.trim() ? cli_envs.commit_env_b64 : '';
const read_records_fn = (conv_id) => read_phase5_records_with_fallback(conv_id, resolved_transcript);
const subscribe_wait = await subscribe_and_wait_for_phase5(proof_report.conv_id, {
require_app: true,
timeout_ms: 8000,
initial_timeout_ms: 1500,
poll_interval_ms: 400,
handshake_grace_ms: 800,
expected_handshake_env_b64: expected_commit_env_b64,
require_handshake_min: expected_commit_env_b64 ? 1 : 0,
quiescent_polls: 2,
quiescent_interval_ms: 300,
read_records_fn,
});
proof_report.wait_quiescent = Boolean(subscribe_wait.wait_quiescent);
proof_report.wait_expected_handshake_seen = Boolean(subscribe_wait.wait_expected_handshake_seen);
if (!subscribe_wait.ok) {
const missing_label = subscribe_wait.missing.length
? subscribe_wait.missing.join(', ')
: 'unknown';
const details = `missing ${missing_label}`;
set_step('subscribe_wait', 'fail', details);
proof_report.error = details;
proof_report.decrypted_plaintext = `error: ${details}`;
set_status_prefixed(details);
set_step('join', 'pending', 'skipped (subscribe failed)');
set_step('drain', 'pending', 'skipped (subscribe failed)');
set_step('decrypt', 'pending', 'skipped (subscribe failed)');
set_step('reply', 'pending', 'skipped (subscribe failed)');
set_step('report', 'running', 'building report');
set_step('report', 'ok', 'report ready');
return proof_report;
}
set_step('subscribe_wait', 'ok', format_phase5_wait_details(subscribe_wait));
proof_report.wait_last_seq_seen = subscribe_wait.last_seq_seen;
const refreshed_snapshot = await read_phase5_transcript_snapshot_with_fallback(
proof_report.conv_id,
resolved_transcript
);
let transcript = resolved_transcript;
let events = resolved_events;
if (refreshed_snapshot.ok) {
transcript = refreshed_snapshot.transcript;
events = refreshed_snapshot.events || [];
proof_report.events_source =
refreshed_snapshot.source === 'transcript db'
? 'transcript db'
: resolve_events_source(resolved.source_note || '');
proof_report.events_used = events.length;
} else {
proof_report.events_source = resolve_events_source(resolved.source_note || '');
proof_report.events_used = events.length;
}
if (!proof_report.events_source) {
proof_report.events_source = resolve_events_source(resolved.source_note || '');
}
const lookup_events = (env_b64, kind) => {
const primary_match = find_transcript_event_by_env(events, env_b64, kind);
if (primary_match) {
return primary_match;
}
if (events !== resolved_events) {
return find_transcript_event_by_env(resolved_events, env_b64, kind);
}
return null;
};
set_step('join', 'running', 'selecting welcome');
const latest_welcome = pick_latest_env(events, 1);
const selected_welcome_env = cli_envs.welcome_env_b64 || (latest_welcome && latest_welcome.env);
const matched_welcome = selected_welcome_env ? lookup_events(selected_welcome_env, 1) : null;
proof_report.welcome_seq =
matched_welcome && Number.isInteger(matched_welcome.seq) ? matched_welcome.seq : null;
if (!selected_welcome_env) {
set_step('join', 'fail', 'missing welcome env');
proof_report.error = 'missing welcome env';
proof_report.decrypted_plaintext = 'error: missing welcome env';
set_status_prefixed('missing welcome env');
} else {
const welcome_unpacked = unpack_dm_env(selected_welcome_env);
if (!welcome_unpacked || welcome_unpacked.kind !== 1) {
set_step('join', 'fail', 'invalid welcome env');
proof_report.error = 'invalid welcome env';
proof_report.decrypted_plaintext = 'error: invalid welcome env';
set_status_prefixed('invalid welcome env');
} else if (!bob_participant_b64) {
set_step('join', 'fail', 'missing bob participant');
proof_report.error = 'missing bob participant';
proof_report.decrypted_plaintext = 'error: missing bob participant';
set_status_prefixed('missing bob participant');
} else {
if (options.set_welcome_env_input) {
options.set_welcome_env_input(selected_welcome_env);
}
set_status_prefixed('joining bob from welcome...');
await ensure_wasm_ready();
const join_result = await dm_join(bob_participant_b64, welcome_unpacked.payload_b64);
if (!join_result || !join_result.ok) {
const error_text = join_result && join_result.error ? join_result.error : 'unknown error';
set_step('join', 'fail', `join failed: ${error_text}`);
proof_report.error = `join failed: ${error_text}`;
proof_report.decrypted_plaintext = `error: join failed: ${error_text}`;
set_status_prefixed('join failed');
log_output(`${status_prefix}: join failed: ${error_text}`);
} else {
bob_participant_b64 = join_result.participant_b64;
bob_has_joined = true;
last_welcome_seq = proof_report.welcome_seq;
set_step('join', 'ok', 'welcome applied');
set_status_prefixed('welcome applied');
log_output(`${status_prefix}: welcome applied`);
}
}
}
if (steps_debug.find((step) => step.key === 'join').status !== 'ok') {
set_step('drain', 'pending', 'skipped (join failed)');
set_step('decrypt', 'pending', 'skipped (join failed)');
set_step('reply', 'pending', 'skipped (join failed)');
if (!proof_report.decrypted_plaintext && proof_report.error) {
proof_report.decrypted_plaintext = `error: ${proof_report.error}`;
}
set_step('report', 'running', 'building report');
set_step('report', 'ok', 'report ready');
return proof_report;
}

const drain_snapshot = await read_phase5_transcript_snapshot_with_fallback(
proof_report.conv_id,
transcript
);
if (drain_snapshot.ok) {
transcript = drain_snapshot.transcript;
events = drain_snapshot.events || [];
proof_report.events_source =
drain_snapshot.source === 'transcript db'
? 'transcript db'
: resolve_events_source(resolved.source_note || '');
proof_report.events_used = events.length;
} else if (!proof_report.events_source) {
proof_report.events_source = resolve_events_source(resolved.source_note || '');
}

set_step('drain', 'running', 'applying handshakes');
const collect_handshake_events = (records) => {
const handshake_events = [];
for (const event of records) {
if (!event || typeof event.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(event.env);
if (!env_meta || env_meta.kind !== 2) {
continue;
}
handshake_events.push({ seq: event.seq, env: event.env });
}
handshake_events.sort((left, right) => left.seq - right.seq);
if (cli_envs.commit_env_b64) {
const matched_commit = lookup_events(cli_envs.commit_env_b64, 2);
if (!matched_commit) {
handshake_events.push({ seq: null, env: cli_envs.commit_env_b64 });
}
}
return handshake_events;
};
const apply_handshake_events = async (records) => {
const handshake_events = collect_handshake_events(records);
let last_handshake_seq = null;
let handshake_error = '';
let dependency_stalled = false;
let handshake_buffered_count = live_inbox_handshake_buffer_by_seq.size;
if (!handshake_events.length) {
return {
ok: true,
handshake_error: '',
last_handshake_seq: null,
handshake_buffered_count,
dependency_stalled: false,
};
}
for (const handshake_event of handshake_events) {
if (is_unechoed_local_commit_env(handshake_event.env)) {
handshake_error = handshake_error || 'local commit pending echo';
log_output(`${status_prefix} blocked: local commit pending echo`);
continue;
}
const apply_result = await apply_handshake_env(handshake_event.seq, handshake_event.env, {
context_label: options.handshake_context_label,
participant_label: handshake_participant_label,
});
if (apply_result.ok) {
if (Number.isInteger(handshake_event.seq)) {
last_handshake_seq = handshake_event.seq;
}
continue;
}
if (apply_result.buffered) {
handshake_buffered_count += 1;
record_handshake_failure(apply_result.error);
if (apply_result.buffered_reason === 'missing proposal') {
dependency_stalled = true;
handshake_dependency_stalls += 1;
}
continue;
}
record_handshake_failure(apply_result.error || 'handshake apply failed');
handshake_error = handshake_error || 'handshake apply failed';
break;
}
if (live_inbox_handshake_buffer_by_seq.size) {
const drained = await drain_handshake_buffer(options.handshake_buffer_label, {
participant_label: handshake_participant_label,
});
if (!drained.ok) {
record_handshake_failure(drained.error || 'handshake buffer drain failed');
handshake_error = drained.error || 'handshake buffer drain failed';
if (drained.stalled_reason === 'dependency missing') {
dependency_stalled = true;
handshake_dependency_stalls += 1;
}
}
}
return {
ok: !handshake_error && !dependency_stalled,
handshake_error,
last_handshake_seq,
handshake_buffered_count,
dependency_stalled,
};
};
let last_handshake_seq = null;
let handshake_error = '';
let handshake_buffered_count = live_inbox_handshake_buffer_by_seq.size;
const handshake_result = await apply_handshake_events(events);
last_handshake_seq = handshake_result.last_handshake_seq;
handshake_error = handshake_result.handshake_error;
handshake_buffered_count = handshake_result.handshake_buffered_count;
if (handshake_result.dependency_stalled && !handshake_replay_retry_used) {
handshake_replay_retry_used = true;
proof_report.handshake_replay_retry_used = true;
set_step('drain', 'running', 'dependency missing; replaying from seq=1');
dispatch_gateway_subscribe(proof_report.conv_id, 1);
live_inbox_handshake_attempts_by_seq = new Map();
const replay_snapshot = await read_phase5_transcript_snapshot_with_fallback(
proof_report.conv_id,
transcript
);
if (replay_snapshot.ok) {
transcript = replay_snapshot.transcript;
events = replay_snapshot.events || [];
proof_report.events_source =
replay_snapshot.source === 'transcript db'
? 'transcript db'
: proof_report.events_source || resolve_events_source(resolved.source_note || '');
proof_report.events_used = events.length;
}
const replay_result = await apply_handshake_events(events);
last_handshake_seq = replay_result.last_handshake_seq;
handshake_error = replay_result.handshake_error;
handshake_buffered_count = replay_result.handshake_buffered_count;
}
if (!collect_handshake_events(events).length && !handshake_error) {
set_step('drain', 'ok', 'no handshake envs');
} else if (handshake_error) {
set_step('drain', 'fail', handshake_error);
proof_report.error = proof_report.error || handshake_error;
if (!proof_report.decrypted_plaintext) {
proof_report.decrypted_plaintext = `error: ${handshake_error}`;
}
} else if (steps_debug.find((step) => step.key === 'drain').status !== 'ok') {
set_step('drain', 'ok', 'handshakes applied');
}
proof_report.last_handshake_applied_seq = last_handshake_seq;
proof_report.handshake_buffered_count = handshake_buffered_count;
proof_report.handshake_apply_failures = handshake_apply_failures;
proof_report.handshake_dependency_stalls = handshake_dependency_stalls;
proof_report.handshake_replay_retry_used = handshake_replay_retry_used;
last_commit_seq = last_handshake_seq;

if (steps_debug.find((step) => step.key === 'drain').status !== 'ok') {
set_step('decrypt', 'pending', 'skipped (handshake failed)');
set_step('reply', 'pending', 'skipped (handshake failed)');
if (!proof_report.decrypted_plaintext && proof_report.error) {
proof_report.decrypted_plaintext = `error: ${proof_report.error}`;
}
set_step('report', 'running', 'building report');
set_step('report', 'ok', 'report ready');
return proof_report;
}

set_step('decrypt', 'running', 'selecting app env');
const latest_app = pick_latest_env(events, 3);
const selected_app_env = cli_envs.app_env_b64 || (latest_app && latest_app.env);
const matched_app = selected_app_env ? lookup_events(selected_app_env, 3) : null;
const app_seq = matched_app && Number.isInteger(matched_app.seq) ? matched_app.seq : null;
proof_report.app_seq = app_seq;
const proof_app_seq_value =
cli_envs && Number.isInteger(cli_envs.proof_app_seq) ? cli_envs.proof_app_seq : app_seq;
proof_report.proof_app_seq = proof_app_seq_value;
if (!selected_app_env) {
set_step('decrypt', 'fail', 'no app env found');
proof_report.error = proof_report.error || 'no app env found';
proof_report.decrypted_plaintext = 'error: no app env found';
set_status_prefixed('no app env found');
} else {
const app_unpacked = unpack_dm_env(selected_app_env);
if (!app_unpacked || app_unpacked.kind !== 3) {
set_step('decrypt', 'fail', 'invalid app env');
proof_report.error = proof_report.error || 'invalid app env';
proof_report.decrypted_plaintext = 'error: invalid app env';
set_status_prefixed('invalid app env');
} else if (!bob_participant_b64) {
set_step('decrypt', 'fail', 'missing participant');
proof_report.error = proof_report.error || 'missing participant';
proof_report.decrypted_plaintext = 'error: missing participant';
set_status_prefixed('missing participant for decrypt');
} else {
const seq_suffix = Number.isInteger(app_seq) ? ` (seq=${app_seq})` : '';
set_status_prefixed(`decrypting app${seq_suffix}`);
const dec_result = await dm_decrypt(bob_participant_b64, app_unpacked.payload_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
set_step('decrypt', 'fail', `decrypt failed: ${error_text}`);
proof_report.decrypted_plaintext = `decrypt error: ${error_text}`;
proof_report.error = proof_report.error || `decrypt failed: ${error_text}`;
set_status_prefixed('app decrypt failed');
log_output(`${status_prefix} app decrypt failed: ${error_text}`);
} else {
bob_participant_b64 = dec_result.participant_b64;
proof_report.decrypted_plaintext = dec_result.plaintext;
last_app_seq = app_seq;
if (options.set_decrypt_output) {
options.set_decrypt_output(matched_app ? matched_app.msg_id : '', dec_result.plaintext);
}
set_step('decrypt', 'ok', `decrypted${seq_suffix}`);
set_status_prefixed(`app decrypted${seq_suffix}`);
log_output(`${status_prefix} app decrypted${seq_suffix}`);
const expected_value = resolved_expected_plaintext || '';
if (expected_value) {
proof_report.expected_plaintext_result =
dec_result.plaintext === expected_value ? 'PASS' : 'FAIL';
if (proof_report.expected_plaintext_result === 'PASS') {
log_output(`${status_prefix} expected_plaintext PASS`);
} else {
log_output(`${status_prefix} expected_plaintext FAIL`);
}
}
}
}
}

const decrypt_ok = steps_debug.find((step) => step.key === 'decrypt').status === 'ok';
const expected_pass =
!proof_report.expected_plaintext_result || proof_report.expected_plaintext_result === 'PASS';
const auto_reply_enabled = Boolean(options.auto_reply_input && options.auto_reply_input.checked);
proof_report.reply_plaintext = options.reply_input ? options.reply_input.value : '';
if (!decrypt_ok) {
set_step('reply', 'pending', 'skipped (decrypt failed)');
} else if (!expected_pass) {
set_step('reply', 'pending', 'skipped (expected_plaintext FAIL)');
} else if (!auto_reply_enabled) {
set_step('reply', 'ok', 'skipped (disabled)');
} else if (!proof_report.reply_plaintext) {
set_step('reply', 'fail', 'reply plaintext empty');
proof_report.error = proof_report.error || 'reply plaintext empty';
} else if (!bob_participant_b64) {
set_step('reply', 'fail', 'missing participant');
proof_report.error = proof_report.error || 'missing participant for reply';
} else {
set_step('reply', 'running', 'encrypting reply');
proof_report.auto_reply_attempted = true;
await ensure_wasm_ready();
const enc_result = await dm_encrypt(bob_participant_b64, proof_report.reply_plaintext);
if (!enc_result || !enc_result.ok) {
const error_text = enc_result && enc_result.error ? enc_result.error : 'unknown error';
set_step('reply', 'fail', `reply encrypt failed: ${error_text}`);
proof_report.error = proof_report.error || `reply encrypt failed: ${error_text}`;
set_status_prefixed('reply encrypt failed');
log_output(`${status_prefix} reply encrypt failed: ${error_text}`);
} else {
bob_participant_b64 = enc_result.participant_b64;
const reply_env_b64 = pack_dm_env(3, enc_result.ciphertext_b64);
dispatch_gateway_send_env(proof_report.conv_id, reply_env_b64);
set_step('reply', 'ok', 'reply sent');
set_status_prefixed('reply sent');
log_output(`${status_prefix} reply env sent`);
}
}

if (peer_wait_enabled) {
if (!decrypt_ok) {
proof_report.peer_wait_status = 'SKIP';
proof_report.peer_wait_error = 'skipped (decrypt failed)';
proof_report.token_cli_to_web_result = 'SKIP';
proof_report.cli_command_bidirectional = 'skipped (decrypt failed)';
} else if (!expected_pass) {
proof_report.peer_wait_status = 'SKIP';
proof_report.peer_wait_error = 'skipped (expected_plaintext FAIL)';
proof_report.token_cli_to_web_result = 'SKIP';
proof_report.cli_command_bidirectional = 'skipped (expected_plaintext FAIL)';
} else if (offline_transcript_mode) {
proof_report.peer_wait_status = 'SKIP';
proof_report.peer_wait_error = 'offline transcript mode';
proof_report.token_cli_to_web_result = 'SKIP';
proof_report.cli_command_bidirectional = 'skipped (offline transcript mode)';
} else {
const token_web_to_cli = build_peer_wait_token();
const token_cli_to_web = build_peer_wait_token();
proof_report.token_web_to_cli = token_web_to_cli;
proof_report.token_cli_to_web_expected = token_cli_to_web;
proof_report.peer_expected_plaintext = token_cli_to_web;
proof_report.cli_command_bidirectional = build_bidirectional_cli_command(
proof_report.peer_wait_cli_command_name,
proof_report.conv_id,
token_web_to_cli,
token_cli_to_web
);
proof_report.peer_wait_token = token_web_to_cli;
const token_send_result = await send_phase5_peer_wait_token(
proof_report.conv_id,
token_web_to_cli,
{
status_prefix: `${status_prefix} peer wait token`,
set_status_fn: options.set_status_fn,
}
);
if (!token_send_result.ok) {
proof_report.peer_wait_status = 'FAIL';
proof_report.peer_wait_error = token_send_result.error || 'peer wait token send failed';
proof_report.token_cli_to_web_result = 'MISMATCH';
set_status_prefixed('peer wait token send failed');
} else {
set_status_prefixed('waiting for peer app');
const peer_after_seq = Number.isInteger(proof_report.app_seq)
? proof_report.app_seq
: Number.isInteger(last_app_seq)
? last_app_seq
: 0;
const peer_wait_result = await wait_decrypt_peer_app(
proof_report.conv_id,
peer_after_seq,
token_cli_to_web,
peer_wait_timeout_ms
);
proof_report.peer_app_seq = peer_wait_result.peer_app_seq;
proof_report.peer_decrypted_plaintext = peer_wait_result.decrypted_plaintext || '';
proof_report.peer_expected_plaintext_result = peer_wait_result.match ? 'PASS' : 'FAIL';
proof_report.token_cli_to_web_result = peer_wait_result.match ? 'MATCH' : 'MISMATCH';
if (peer_wait_result.ok) {
proof_report.peer_wait_status = 'PASS';
set_status_prefixed('peer app decrypted');
} else {
proof_report.peer_wait_status = 'FAIL';
proof_report.peer_wait_error = peer_wait_result.error || 'peer wait failed';
proof_report.token_cli_to_web_result = 'MISMATCH';
set_status_prefixed('peer app wait failed');
}
}
}
}

set_step('report', 'running', 'building report');
set_step('report', 'ok', 'report ready');
return proof_report;
});
return scoped_result;
};

let final_report = null;
try {
final_report = await run_core();
} catch (error) {
set_status_prefixed('error');
log_output(`${status_prefix} failed: ${error}`);
set_step('report', 'fail', 'report failed');
proof_report.error = proof_report.error || String(error);
final_report = proof_report;
} finally {
finalize_report();
}
return {
ok: !final_report.error,
report: final_report,
steps_debug,
};
};

const run_phase5_proof_wizard = async (options) => {
const status_prefix = options.status_prefix;
if (options.get_in_flight()) {
return;
}
options.set_in_flight(true);
if (options.run_btn) {
options.run_btn.disabled = true;
}
const steps = build_phase5_steps();
render_phase5_timeline(steps, options.timeline_container);
set_phase5_report_text('', options.report_output);
const on_step = (key, status, details) => {
set_phase5_step_status(steps, key, status, details, options.timeline_container);
};
const core_result = await run_phase5_proof_core({
status_prefix,
resolve_inputs: options.resolve_inputs,
set_status_fn: options.set_status_fn,
on_step,
set_welcome_env_input: options.set_welcome_env_input,
set_decrypt_output: options.set_decrypt_output,
auto_reply_input: options.auto_reply_input,
reply_input: options.reply_input,
peer_wait_input: options.peer_wait_input,
peer_wait_expected_input: options.peer_wait_expected_input,
peer_wait_timeout_input: options.peer_wait_timeout_input,
peer_wait_cli_command_name: options.peer_wait_cli_command_name,
handshake_context_label: options.handshake_context_label,
handshake_buffer_label: options.handshake_buffer_label,
});
set_phase5_report_text(format_phase5_report(core_result.report), options.report_output);
options.set_in_flight(false);
if (options.run_btn) {
options.run_btn.disabled = false;
}
};

const run_dm_phase5_proof_wizard = async () => run_phase5_proof_wizard({
status_prefix: 'dm proof',
resolve_inputs: () => resolve_phase5_inputs({
conv_id_resolver: get_active_conv_id_for_send,
set_status_fn: set_status,
status_prefix: 'dm proof',
allow_imported_any: true,
}),
set_status_fn: set_status,
timeline_container: dm_phase5_proof_timeline,
report_output: dm_phase5_proof_report,
run_btn: dm_phase5_proof_run_btn,
get_in_flight: () => dm_phase5_proof_in_flight,
set_in_flight: (value) => {
dm_phase5_proof_in_flight = value;
},
set_welcome_env_input: (env_b64) => {
set_incoming_env_input(env_b64);
},
set_decrypt_output: (_msg_id, plaintext) => {
set_decrypted_output(plaintext);
},
auto_reply_input: dm_phase5_proof_auto_reply_input,
reply_input: dm_phase5_proof_reply_input,
peer_wait_input: dm_phase5_peer_wait_input,
peer_wait_expected_input: dm_phase5_peer_expected_input,
peer_wait_timeout_input: dm_phase5_peer_timeout_input,
peer_wait_cli_command_name: 'gw-phase5-dm-proof',
handshake_context_label: 'handshake (dm proof)',
handshake_buffer_label: 'handshake (dm proof buffer)',
});

const run_room_phase5_proof_wizard = async () => run_phase5_proof_wizard({
status_prefix: 'room proof',
resolve_inputs: () => resolve_phase5_inputs({
conv_id_resolver: get_room_conv_id_for_send,
set_status_fn: set_room_status,
status_prefix: 'room proof',
allow_imported_any: false,
}),
set_status_fn: set_room_status,
timeline_container: room_phase5_proof_timeline,
report_output: room_phase5_proof_report,
run_btn: room_phase5_proof_run_btn,
get_in_flight: () => room_phase5_proof_in_flight,
set_in_flight: (value) => {
room_phase5_proof_in_flight = value;
},
set_welcome_env_input: (env_b64) => {
if (room_welcome_env_input) {
room_welcome_env_input.value = env_b64;
}
},
set_decrypt_output: set_room_decrypt_output,
auto_reply_input: room_phase5_proof_auto_reply_input,
reply_input: room_phase5_proof_reply_input,
peer_wait_input: room_phase5_peer_wait_input,
peer_wait_expected_input: room_phase5_peer_expected_input,
peer_wait_timeout_input: room_phase5_peer_timeout_input,
peer_wait_cli_command_name: 'gw-phase5-room-proof',
handshake_context_label: 'handshake (proof wizard)',
handshake_buffer_label: 'handshake (proof wizard buffer)',
});

const run_coexist_phase5_proof_wizard = async () => {
if (coexist_phase5_proof_in_flight) {
return;
}
coexist_phase5_proof_in_flight = true;
if (coexist_phase5_proof_run_btn) {
coexist_phase5_proof_run_btn.disabled = true;
}
set_phase5_report_text('', coexist_phase5_proof_report);
const coexist_start_ms = Date.now();
const coexist_steps = build_phase5_coexist_steps();
render_phase5_timeline(coexist_steps, coexist_phase5_proof_timeline);
const set_coexist_step = (key, status, details) => {
set_phase5_step_status(coexist_steps, key, status, details, coexist_phase5_proof_timeline);
};
const finalize_coexist = (summary) => {
const end_ms = Date.now();
const duration_ms = Number.isInteger(end_ms) && Number.isInteger(coexist_start_ms)
? end_ms - coexist_start_ms
: null;
const resolved_summary = {
start_ms: coexist_start_ms,
end_ms,
duration_ms,
auto_reply_attempted: false,
dm_report: null,
room_report: null,
active_coexist: null,
coexist_peer_tokens: null,
dm_result: 'SKIP',
room_result: 'FAIL',
overall_result: 'FAIL',
error: '',
...summary,
};
resolved_summary.auto_reply_attempted = Boolean(
(resolved_summary.dm_report && resolved_summary.dm_report.auto_reply_attempted) ||
(resolved_summary.room_report && resolved_summary.room_report.auto_reply_attempted)
);
set_phase5_report_text(
format_phase5_coexist_report(resolved_summary),
coexist_phase5_proof_report
);
coexist_phase5_proof_in_flight = false;
if (coexist_phase5_proof_run_btn) {
coexist_phase5_proof_run_btn.disabled = false;
}
};
const extract_step_debug = (steps_debug, key) => {
if (!Array.isArray(steps_debug)) {
return null;
}
return steps_debug.find((step) => step.key === key) || null;
};
const is_phase5_step_ok = (steps_debug, key) => {
const step = extract_step_debug(steps_debug, key);
return step && step.status === 'ok';
};
const is_phase5_conv_ready = (steps_debug) => (
is_phase5_step_ok(steps_debug, 'subscribe_wait') &&
is_phase5_step_ok(steps_debug, 'join') &&
is_phase5_step_ok(steps_debug, 'drain')
);
const format_subscribe_detail = (label, steps_debug) => {
const step = extract_step_debug(steps_debug, 'subscribe_wait');
if (!step || !step.details) {
return `${label} subscribe_wait: n/a`;
}
return `${label} ${step.details}`;
};
set_coexist_step('parse', 'running', 'checking CLI blocks');
const block_text = coexist_phase5_proof_cli_input ? coexist_phase5_proof_cli_input.value : '';
const trimmed_block_text = block_text ? block_text.trim() : '';
const resolved_blocks = resolve_coexist_cli_blocks(block_text);
const has_cli_blocks = resolved_blocks.ok && resolved_blocks.room_block;
let dm_block = null;
let room_block = null;
let dm_resolve_inputs = null;
let room_resolve_inputs = null;
const coexist_bundle = last_imported_coexist_bundle;
if (coexist_bundle) {
const dm_conv_id = coexist_bundle.dm.transcript.conv_id;
const room_conv_id_value = coexist_bundle.room.transcript.conv_id;
set_coexist_step(
'parse',
'ok',
`bundle mode (dm conv_id=${dm_conv_id}, room conv_id=${room_conv_id_value})`
);
dm_block = build_phase5_bundle_cli_block(coexist_bundle.dm);
room_block = build_phase5_bundle_cli_block(coexist_bundle.room);
dm_resolve_inputs = () => resolve_phase5_bundle_inputs(coexist_bundle.dm);
room_resolve_inputs = () => resolve_phase5_bundle_inputs(coexist_bundle.room);
} else if (has_cli_blocks) {
set_coexist_step('parse', 'ok', 'cli blocks ready');
dm_block = resolved_blocks.dm_block;
room_block = resolved_blocks.room_block;
const room_conv_id_value = normalize_conv_id(room_block ? room_block.conv_id : '');
if (!room_conv_id_value || room_conv_id_value === '(none)') {
set_room_status('coexist proof: room conv_id required');
set_coexist_step('subscribe_wait', 'fail', 'room conv_id required');
set_coexist_step('report', 'fail', 'report failed');
finalize_coexist({ error: 'room conv_id required' });
return;
}
dm_resolve_inputs = () => resolve_phase5_inputs({
conv_id_resolver: () => normalize_conv_id(dm_block ? dm_block.conv_id : ''),
set_status_fn: set_status,
status_prefix: 'coexist dm',
allow_imported_any: false,
cli_block_override: dm_block,
allow_cli_block_input: false,
});
room_resolve_inputs = () => resolve_phase5_inputs({
conv_id_resolver: () => normalize_conv_id(room_block ? room_block.conv_id : ''),
set_status_fn: set_room_status,
status_prefix: 'coexist room',
allow_imported_any: false,
cli_block_override: room_block,
allow_cli_block_input: false,
});
} else {
const fallback_reason = trimmed_block_text
? resolved_blocks.error || 'invalid cli block'
: 'no cli block provided';
set_coexist_step('parse', 'ok', `using transcript mode (${fallback_reason})`);
const dm_conv_id = get_active_conv_id_for_send();
const room_conv_id_value = get_room_conv_id_for_send();
if (!room_conv_id_value) {
set_room_status('coexist proof: room conv_id required');
set_coexist_step('subscribe_wait', 'fail', 'room conv_id required');
set_coexist_step('report', 'fail', 'report failed');
finalize_coexist({ error: 'room conv_id required' });
return;
}
if (dm_conv_id) {
dm_block = { conv_id: dm_conv_id };
}
dm_resolve_inputs = () => resolve_phase5_inputs({
conv_id_resolver: () => normalize_conv_id(dm_conv_id),
set_status_fn: set_status,
status_prefix: 'coexist dm',
allow_imported_any: false,
});
room_resolve_inputs = () => resolve_phase5_inputs({
conv_id_resolver: () => normalize_conv_id(room_conv_id_value),
set_status_fn: set_room_status,
status_prefix: 'coexist room',
allow_imported_any: false,
});
}
const run_block_core = async (label, resolve_inputs, options) => run_phase5_proof_core({
status_prefix: `coexist ${label}`,
resolve_inputs,
set_status_fn: options.set_status_fn,
set_welcome_env_input: options.set_welcome_env_input,
set_decrypt_output: options.set_decrypt_output,
auto_reply_input: coexist_phase5_proof_auto_reply_input,
reply_input: coexist_phase5_proof_reply_input,
peer_wait_input: null,
peer_wait_expected_input: null,
peer_wait_timeout_input: null,
peer_wait_cli_command_name: '',
handshake_context_label: `handshake (coexist ${label})`,
handshake_buffer_label: `handshake (coexist ${label} buffer)`,
});
let dm_report = null;
let room_report = null;
let dm_steps_debug = null;
let room_steps_debug = null;
let coexist_peer_tokens = null;
let active_coexist = null;
try {
set_coexist_step('subscribe_wait', 'running', 'running core proofs');
set_coexist_step(
'dm',
'running',
dm_block ? 'running dm proof' : 'skipped (room-only)'
);
if (dm_block) {
const dm_result = await run_block_core('dm', dm_resolve_inputs, {
set_status_fn: set_status,
set_welcome_env_input: (env_b64) => {
set_incoming_env_input(env_b64);
},
set_decrypt_output: (_msg_id, plaintext) => {
set_decrypted_output(plaintext);
},
});
dm_report = dm_result.report;
dm_steps_debug = dm_result.steps_debug;
const dm_result_label = compute_phase5_result_label(dm_report);
set_coexist_step('dm', dm_result_label === 'PASS' ? 'ok' : 'fail', `result ${dm_result_label}`);
} else {
set_coexist_step('dm', 'ok', 'skipped (room-only)');
}
set_coexist_step('room', 'running', 'running room proof');
const room_core_result = await run_block_core('room', room_resolve_inputs, {
set_status_fn: set_room_status,
set_welcome_env_input: (env_b64) => {
if (room_welcome_env_input) {
room_welcome_env_input.value = env_b64;
}
},
set_decrypt_output: set_room_decrypt_output,
});
room_report = room_core_result.report;
room_steps_debug = room_core_result.steps_debug;
const dm_result = dm_report ? compute_phase5_result_label(dm_report) : 'SKIP';
const room_result = room_report ? compute_phase5_result_label(room_report) : 'FAIL';
set_coexist_step('room', room_result === 'PASS' ? 'ok' : 'fail', `result ${room_result}`);
const offline_transcript_mode = Boolean(coexist_bundle) ||
(dm_report && dm_report.events_source && dm_report.events_source !== 'transcript db') ||
(room_report && room_report.events_source && room_report.events_source !== 'transcript db');
const dm_ready = dm_block ? is_phase5_conv_ready(dm_steps_debug) : false;
const room_ready = is_phase5_conv_ready(room_steps_debug);
const peer_wait_timeout_ms = parse_peer_wait_timeout_ms(coexist_phase5_peer_timeout_input);
const dm_conv_id = dm_report ? dm_report.conv_id : '';
const room_conv_id_value = room_report ? room_report.conv_id : '';
const run_coexist_peer_tokens = async (
conv_id,
label,
token_web_to_cli,
token_cli_to_web,
app_seq,
set_status_fn
) => {
const result = {
status: 'FAIL',
token_web_to_cli,
token_cli_to_web_expected: token_cli_to_web,
token_cli_to_web_result: 'MISMATCH',
peer_app_seq: null,
peer_decrypted_plaintext: '',
error: '',
};
if (!conv_id) {
result.error = 'missing conv_id';
return result;
}
const send_result = await send_phase5_peer_wait_token(conv_id, token_web_to_cli, {
status_prefix: `coexist ${label} peer token`,
set_status_fn,
});
if (!send_result.ok) {
result.error = send_result.error || 'peer token send failed';
return result;
}
const peer_after_seq = Number.isInteger(app_seq) ? app_seq : 0;
const peer_wait_result = await wait_decrypt_peer_app(
conv_id,
peer_after_seq,
token_cli_to_web,
peer_wait_timeout_ms
);
result.peer_app_seq = peer_wait_result.peer_app_seq;
result.peer_decrypted_plaintext = peer_wait_result.decrypted_plaintext || '';
result.token_cli_to_web_result = peer_wait_result.match ? 'MATCH' : 'MISMATCH';
if (peer_wait_result.ok && peer_wait_result.match) {
result.status = 'PASS';
} else {
result.error = peer_wait_result.error || 'peer token wait failed';
}
return result;
};
set_coexist_step('peer_tokens', 'running', 'sending peer tokens');
if (offline_transcript_mode) {
const bundle_peer_tokens_present = Boolean(
coexist_bundle &&
(
(coexist_bundle.dm && coexist_bundle.dm.peer_tokens) ||
(coexist_bundle.room && coexist_bundle.room.peer_tokens)
)
);
if (bundle_peer_tokens_present) {
const dm_token_result =
dm_block && coexist_bundle.dm
? await run_offline_peer_tokens(
coexist_bundle.dm,
dm_conv_id,
dm_report,
set_status,
'dm'
)
: null;
const room_token_result =
coexist_bundle.room
? await run_offline_peer_tokens(
coexist_bundle.room,
room_conv_id_value,
room_report,
set_room_status,
'room'
)
: null;
const token_statuses = [];
if (dm_token_result) {
token_statuses.push(dm_token_result.status);
}
if (room_token_result) {
token_statuses.push(room_token_result.status);
}
let peer_tokens_status = 'SKIP';
if (token_statuses.includes('FAIL')) {
peer_tokens_status = 'FAIL';
} else if (token_statuses.includes('PASS')) {
peer_tokens_status = 'PASS';
}
const peer_tokens_errors = [];
if (dm_token_result && dm_token_result.error) {
peer_tokens_errors.push(`dm: ${dm_token_result.error}`);
}
if (room_token_result && room_token_result.error) {
peer_tokens_errors.push(`room: ${room_token_result.error}`);
}
coexist_peer_tokens = {
status: peer_tokens_status,
reason: '',
cli_command: '',
dm: dm_token_result,
room: room_token_result,
error: peer_tokens_errors.length ? peer_tokens_errors.join('; ') : '',
};
set_coexist_step(
'peer_tokens',
peer_tokens_status === 'FAIL' ? 'fail' : 'ok',
peer_tokens_status === 'FAIL' ? 'peer tokens failed' : 'offline peer tokens validated'
);
} else {
coexist_peer_tokens = {
status: 'SKIP',
reason: 'offline transcript mode',
cli_command: '',
dm: null,
room: null,
};
set_coexist_step('peer_tokens', 'ok', 'skipped (offline transcript mode)');
}
} else if (!dm_block) {
coexist_peer_tokens = {
status: 'SKIP',
reason: 'room-only',
cli_command: '',
dm: null,
room: null,
};
set_coexist_step('peer_tokens', 'ok', 'skipped (room-only)');
} else if (!dm_ready || !room_ready) {
coexist_peer_tokens = {
status: 'FAIL',
reason: 'prerequisites not met',
cli_command: '',
dm: null,
room: null,
};
set_coexist_step('peer_tokens', 'fail', 'prerequisites not met');
} else {
const dm_token_web_to_cli = build_peer_wait_token();
const dm_token_cli_to_web = build_peer_wait_token();
const room_token_web_to_cli = build_peer_wait_token();
const room_token_cli_to_web = build_peer_wait_token();
const cli_command = build_coexist_cli_command(
dm_conv_id,
room_conv_id_value,
dm_token_web_to_cli,
room_token_web_to_cli,
dm_token_cli_to_web,
room_token_cli_to_web
);
const dm_token_result = await run_coexist_peer_tokens(
dm_conv_id,
'dm',
dm_token_web_to_cli,
dm_token_cli_to_web,
dm_report ? dm_report.app_seq : null,
set_status
);
const room_token_result = await run_coexist_peer_tokens(
room_conv_id_value,
'room',
room_token_web_to_cli,
room_token_cli_to_web,
room_report ? room_report.app_seq : null,
set_room_status
);
const peer_tokens_status =
dm_token_result.status === 'PASS' && room_token_result.status === 'PASS' ? 'PASS' : 'FAIL';
const peer_tokens_errors = [];
if (dm_token_result.error) {
peer_tokens_errors.push(`dm: ${dm_token_result.error}`);
}
if (room_token_result.error) {
peer_tokens_errors.push(`room: ${room_token_result.error}`);
}
coexist_peer_tokens = {
status: peer_tokens_status,
reason: '',
cli_command,
dm: dm_token_result,
room: room_token_result,
error: peer_tokens_errors.length ? peer_tokens_errors.join('; ') : '',
};
set_coexist_step(
'peer_tokens',
peer_tokens_status === 'PASS' ? 'ok' : 'fail',
peer_tokens_status === 'PASS' ? 'peer tokens ok' : 'peer tokens failed'
);
}
const active_errors = [];
if (offline_transcript_mode) {
active_coexist = {
status: 'SKIP',
reason: 'offline transcript mode',
dm: null,
room: null,
};
set_coexist_step('active_coexist', 'ok', 'skipped (offline transcript mode)');
} else if (!dm_block) {
active_coexist = {
status: 'SKIP',
reason: 'room-only',
dm: null,
room: null,
};
set_coexist_step('active_coexist', 'ok', 'skipped (room-only)');
} else if (!dm_ready || !room_ready) {
active_coexist = {
status: 'FAIL',
reason: 'prerequisites not met',
dm: null,
room: null,
};
set_coexist_step('active_coexist', 'fail', 'prerequisites not met');
} else {
set_coexist_step('active_coexist', 'running', 'sending interleaved app messages');
const dm_results = [];
const room_results = [];
const dm_plaintexts = ['phase5-coexist-dm-1', 'phase5-coexist-dm-2'];
const room_plaintexts = ['phase5-coexist-room-1', 'phase5-coexist-room-2'];
for (let index = 0; index < dm_plaintexts.length; index += 1) {
const dm_result_active = await send_wait_decrypt_app(dm_conv_id, 'dm', dm_plaintexts[index], {
timeout_ms: 8000,
status_prefix: `coexist dm active ${index + 1}`,
set_status_fn: set_status,
});
dm_results.push(dm_result_active);
const room_result_active = await send_wait_decrypt_app(
room_conv_id_value,
'room',
room_plaintexts[index],
{
timeout_ms: 8000,
status_prefix: `coexist room active ${index + 1}`,
set_status_fn: set_room_status,
}
);
room_results.push(room_result_active);
}
const summarize_active = (results) => {
let sent_count = 0;
let last_app_seq = null;
let decrypt_ok = true;
let digest = '';
const errors = [];
for (const entry of results) {
if (!entry) {
continue;
}
sent_count += Number.isInteger(entry.sent_count) ? entry.sent_count : 0;
if (Number.isInteger(entry.last_app_seq)) {
last_app_seq = entry.last_app_seq;
}
if (entry.digest) {
digest = entry.digest;
}
if (!entry.decrypt_ok) {
decrypt_ok = false;
}
if (entry.error) {
errors.push(entry.error);
}
}
if (errors.length) {
active_errors.push(errors.join('; '));
}
return {
sent_count,
last_app_seq,
decrypt_ok,
digest,
};
};
const dm_active_summary = summarize_active(dm_results);
const room_active_summary = summarize_active(room_results);
const dm_active_ok = dm_active_summary.decrypt_ok && dm_active_summary.sent_count === 2;
const room_active_ok = room_active_summary.decrypt_ok && room_active_summary.sent_count === 2;
const digest_stable = Boolean(dm_active_summary.digest) && Boolean(room_active_summary.digest);
const active_status = dm_active_ok && room_active_ok && digest_stable ? 'PASS' : 'FAIL';
active_coexist = {
status: active_status,
dm: dm_active_summary,
room: room_active_summary,
error: active_errors.length ? active_errors.join('; ') : '',
};
set_coexist_step(
'active_coexist',
active_status === 'PASS' ? 'ok' : 'fail',
active_status === 'PASS' ? 'active coexist ok' : 'active coexist failed'
);
}
const subscribe_ok =
(!dm_block || (extract_step_debug(dm_steps_debug, 'subscribe_wait') || {}).status === 'ok') &&
(extract_step_debug(room_steps_debug, 'subscribe_wait') || {}).status === 'ok';
const subscribe_details = [
format_subscribe_detail('room', room_steps_debug),
dm_block ? format_subscribe_detail('dm', dm_steps_debug) : null,
].filter(Boolean).join('; ');
set_coexist_step('subscribe_wait', subscribe_ok ? 'ok' : 'fail', subscribe_details || 'n/a');
const digest_stable =
(!dm_report || dm_report.digest_status !== 'digest mismatch') &&
(!room_report || room_report.digest_status !== 'digest mismatch');
const active_status = active_coexist ? active_coexist.status : 'FAIL';
const active_ok = active_status === 'PASS';
const active_skipped = active_status === 'SKIP';
const peer_tokens_status = coexist_peer_tokens ? coexist_peer_tokens.status : 'SKIP';
const peer_tokens_ok = peer_tokens_status === 'PASS';
const peer_tokens_skipped = peer_tokens_status === 'SKIP';
const overall_ok =
room_result === 'PASS' &&
(dm_report ? dm_result === 'PASS' : true) &&
digest_stable &&
(active_ok || active_skipped) &&
(peer_tokens_ok || peer_tokens_skipped);
const overall_should_skip = active_skipped || peer_tokens_skipped;
const overall_result = overall_ok ? (overall_should_skip ? 'SKIP' : 'PASS') : 'FAIL';
set_coexist_step('report', 'running', 'building combined report');
set_coexist_step('report', 'ok', 'report ready');
finalize_coexist({
dm_report,
room_report,
coexist_peer_tokens,
active_coexist,
dm_result,
room_result,
overall_result,
});
} catch (error) {
set_coexist_step('report', 'fail', 'report failed');
finalize_coexist({
dm_report,
room_report,
coexist_peer_tokens,
error: String(error),
});
}
};

const handle_room_init = async () => {
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before init');
return;
}
if (!alice_participant_b64) {
set_room_status('room: need owner participant');
log_output('room init blocked: missing owner participant');
return;
}
const peer_keypackages = parse_keypackage_lines(
room_keypackages_input ? room_keypackages_input.value : ''
);
if (peer_keypackages.length < 2) {
set_room_status('room: need at least 2 peer keypackages');
log_output('room init blocked: need at least 2 peer keypackages');
return;
}
if (!group_id_b64) {
group_id_b64 = generate_group_id();
set_group_id_input();
}
set_room_status('room: init running');
await ensure_wasm_ready();
const group_init_fn = get_group_init_fn();
if (!group_init_fn) {
set_room_status('room: wasm group_init missing');
log_output('room init failed: wasm group_init missing');
return;
}
const result = group_init_fn(alice_participant_b64, peer_keypackages, group_id_b64, seed_room_init);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_room_status('room: init failed');
log_output(`room init failed: ${error_text}`);
return;
}
if (typeof result.participant_b64 === 'string') {
alice_participant_b64 = result.participant_b64;
}
if (typeof result.commit_b64 !== 'string' || typeof result.welcome_b64 !== 'string') {
set_room_status('room: init missing envelopes');
log_output('room init failed: missing welcome/commit');
return;
}
commit_b64 = result.commit_b64;
const welcome_env_b64 = pack_dm_env(1, result.welcome_b64);
const commit_env_b64 = pack_dm_env(2, result.commit_b64);
set_outbox_envs({ welcome_env_b64, commit_env_b64 });
last_local_commit_env_b64 = commit_env_b64;
set_commit_echo_state('waiting', null);
set_room_status('room: sending init (welcome)');
dispatch_gateway_send_env(conv_id, welcome_env_b64);
set_room_status('room: sending init (commit)');
dispatch_gateway_send_env(conv_id, commit_env_b64);
set_room_status('room: init sent (waiting for commit echo)');
log_output(`room init outbox ready for conv_id ${conv_id}`);
};

const handle_room_add = async () => {
const conv_id = get_room_conv_id_for_send();
if (!conv_id) {
set_room_status('room: select conv_id before add');
return;
}
if (!alice_participant_b64) {
set_room_status('room: need owner participant');
log_output('room add blocked: missing owner participant');
return;
}
const peer_keypackages = parse_keypackage_lines(
room_add_keypackage_input ? room_add_keypackage_input.value : ''
);
if (peer_keypackages.length < 1) {
set_room_status('room: need 1 peer keypackage');
log_output('room add blocked: missing peer keypackage');
return;
}
set_room_status('room: add running');
await ensure_wasm_ready();
const group_add_fn = get_group_add_fn();
if (!group_add_fn) {
set_room_status('room: wasm group_add missing');
log_output('room add failed: wasm group_add missing');
return;
}
const result = group_add_fn(alice_participant_b64, peer_keypackages, seed_room_add);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_room_status('room: add failed');
log_output(`room add failed: ${error_text}`);
return;
}
if (typeof result.participant_b64 === 'string') {
alice_participant_b64 = result.participant_b64;
}
if (typeof result.commit_b64 !== 'string' || typeof result.welcome_b64 !== 'string') {
set_room_status('room: add missing envelopes');
log_output('room add failed: missing welcome/commit');
return;
}
commit_b64 = result.commit_b64;
const welcome_env_b64 = pack_dm_env(1, result.welcome_b64);
const commit_env_b64 = pack_dm_env(2, result.commit_b64);
const proposals_b64 = Array.isArray(result.proposals_b64) ? result.proposals_b64 : [];
set_outbox_envs({ welcome_env_b64, commit_env_b64 });
last_local_commit_env_b64 = commit_env_b64;
set_commit_echo_state('waiting', null);
if (proposals_b64.length > 0) {
set_room_status(`room: sending add (${proposals_b64.length} proposal${proposals_b64.length === 1 ? '' : 's'})`);
proposals_b64.forEach((proposal_b64) => {
const proposal_env_b64 = pack_dm_env(2, proposal_b64);
if (!proposal_env_b64) {
return;
}
dispatch_gateway_send_env(conv_id, proposal_env_b64);
});
}
set_room_status('room: sending add (welcome)');
dispatch_gateway_send_env(conv_id, welcome_env_b64);
set_room_status('room: sending add (commit)');
dispatch_gateway_send_env(conv_id, commit_env_b64);
set_room_status('room: add sent (waiting for commit echo)');
log_output(`room add outbox ready for conv_id ${conv_id}`);
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
bob_has_joined = false;
last_welcome_seq = null;
last_commit_seq = null;
last_app_seq = null;
live_inbox_by_seq = new Map();
live_inbox_handshake_buffer_by_seq = new Map();
live_inbox_handshake_attempts_by_seq = new Map();
live_inbox_last_ingested_seq = null;
set_live_inbox_expected_seq(1);
set_group_id_input();
set_ciphertext_output('');
set_decrypted_output('');
if (room_welcome_env_input) {
room_welcome_env_input.value = '';
}
if (room_send_plaintext_input) {
room_send_plaintext_input.value = '';
}
set_room_decrypt_output('', '');
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

const parse_keypackage_count = () => {
if (!dm_bootstrap_count_input) {
return 1;
}
const parsed = Number.parseInt(dm_bootstrap_count_input.value, 10);
if (!Number.isInteger(parsed) || parsed < 1) {
return 1;
}
return parsed;
};

const get_dm_bootstrap_auth = () => {
if (!gateway_session_token || !gateway_http_base_url) {
set_dm_bootstrap_status('gateway session not ready');
return null;
}
return {
session_token: gateway_session_token,
http_base_url: gateway_http_base_url,
};
};

const handle_fetch_peer_keypackage = async () => {
const auth = get_dm_bootstrap_auth();
if (!auth) {
return;
}
const peer_user_id = dm_bootstrap_peer_input ? dm_bootstrap_peer_input.value.trim() : '';
if (!peer_user_id) {
set_dm_bootstrap_status('missing peer_user_id');
return;
}
const count = parse_keypackage_count();
set_dm_bootstrap_status('fetching peer keypackage...');
let response;
try {
response = await fetch(`${auth.http_base_url}${keypackage_fetch_path}`, {
method: 'POST',
headers: {
'Content-Type': 'application/json',
Authorization: `Bearer ${auth.session_token}`,
},
body: JSON.stringify({ user_id: peer_user_id, count }),
});
} catch (error) {
set_dm_bootstrap_status(`fetch failed: ${error}`);
return;
}
let payload = null;
try {
payload = await response.json();
} catch (error) {
payload = null;
}
if (!response.ok) {
const error_message =
payload && payload.message ? payload.message : `request failed (${response.status})`;
set_dm_bootstrap_status(`fetch failed: ${error_message}`);
return;
}
const keypackages = payload && Array.isArray(payload.keypackages) ? payload.keypackages : [];
if (!keypackages.length || typeof keypackages[0] !== 'string') {
set_dm_bootstrap_status('no keypackages returned');
return;
}
bob_keypackage_b64 = keypackages[0];
set_dm_bootstrap_status('peer keypackage loaded');
set_status('peer keypackage loaded');
};

const handle_publish_keypackage = async () => {
const auth = get_dm_bootstrap_auth();
if (!auth) {
return;
}
const device_id = device_id_input ? device_id_input.value.trim() : '';
if (!device_id) {
set_dm_bootstrap_status('missing device_id');
return;
}
const keypackage_b64 = alice_keypackage_b64 || bob_keypackage_b64;
if (!keypackage_b64) {
set_dm_bootstrap_status('missing keypackage to publish');
return;
}
set_dm_bootstrap_status('publishing keypackage...');
let response;
try {
response = await fetch(`${auth.http_base_url}${keypackage_publish_path}`, {
method: 'POST',
headers: {
'Content-Type': 'application/json',
Authorization: `Bearer ${auth.session_token}`,
},
body: JSON.stringify({ device_id, keypackages: [keypackage_b64] }),
});
} catch (error) {
set_dm_bootstrap_status(`publish failed: ${error}`);
return;
}
let payload = null;
try {
payload = await response.json();
} catch (error) {
payload = null;
}
if (!response.ok) {
const error_message =
payload && payload.message ? payload.message : `request failed (${response.status})`;
set_dm_bootstrap_status(`publish failed: ${error_message}`);
return;
}
set_dm_bootstrap_status('published keypackage');
set_status('keypackage published');
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
bob_has_joined = false;
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
return false;
}
set_status('joining...');
log_output('');
const result = await dm_join(bob_participant_b64, welcome_b64);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_status('error');
log_output(`join failed: ${error_text}`);
return false;
}
bob_participant_b64 = result.participant_b64;
bob_has_joined = true;
set_status('bob joined');
log_output('bob applied welcome');
const drained = await drain_handshake_buffer('handshake (post-welcome)');
if (!drained.ok) {
log_output(`handshake buffer stalled: ${drained.error || drained.stalled_reason}`);
}
return true;
};

const handle_commit_apply = async () => {
if (commit_apply_in_flight) {
set_status('commit apply already in progress');
log_output('commit apply already in progress');
return false;
}
if (!alice_participant_b64 || !commit_b64) {
set_status('error');
log_output('need alice participant and commit');
return false;
}
commit_apply_in_flight = true;
try {
set_status('applying commit...');
log_output('');
const result = await dm_commit_apply(alice_participant_b64, commit_b64);
if (!result || !result.ok) {
const error_text = result && result.error ? result.error : 'unknown error';
set_status('error');
log_output(`commit apply failed: ${error_text}`);
return false;
}
alice_participant_b64 = result.participant_b64;
const suffix = result.noop ? ' (noop)' : '';
set_status(`commit applied${suffix}`);
log_output(`alice commit applied${suffix}`);
return true;
} catch (error) {
set_status('error');
log_output(`commit apply failed: ${error}`);
return false;
} finally {
commit_apply_in_flight = false;
}
};

const handle_import_welcome_env = async (options) => {
const normalized_options = options || {};
const env_b64 = incoming_env_input ? incoming_env_input.value.trim() : '';
const unpacked = unpack_dm_env(env_b64);
if (!unpacked) {
return { ok: false };
}
if (unpacked.kind !== 1) {
set_status('error');
log_output('expected welcome env (kind=1)');
return { ok: false };
}
welcome_b64 = unpacked.payload_b64;
set_status('welcome loaded');
log_output('welcome env loaded from gateway/cli');
if (normalized_options.seq !== undefined) {
last_welcome_seq =
Number.isInteger(normalized_options.seq) ? normalized_options.seq : last_welcome_seq;
} else {
last_welcome_seq = null;
}
if (!normalized_options.allow_auto_join) {
return { ok: true };
}
if (!get_auto_join_on_welcome_enabled()) {
return { ok: true };
}
if (bob_has_joined) {
set_run_next_step_status('last action: auto-join skipped; bob already joined');
return { ok: true };
}
if (!bob_participant_b64) {
set_run_next_step_status('last action: auto-join skipped; missing bob participant');
return { ok: false };
}
const joined = await handle_join();
if (joined) {
const suffix =
Number.isInteger(normalized_options.seq) ? ` (seq=${normalized_options.seq})` : '';
set_run_next_step_status(`last action: auto-joined bob on welcome${suffix}`);
return { ok: true };
}
set_run_next_step_status('last action: auto-join failed; check status');
return { ok: false };
};

const handle_import_commit_env = (options) => {
const normalized_options = options || {};
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
if (normalized_options.seq !== undefined) {
last_commit_seq =
Number.isInteger(normalized_options.seq) ? normalized_options.seq : last_commit_seq;
} else {
last_commit_seq = null;
}
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
if (auto_join_on_welcome_input) {
auto_join_on_welcome_input.disabled = !enabled;
}
};

const ingest_live_inbox_seq = async (seq) => {
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
await handle_import_welcome_env({ allow_auto_join: true, seq });
} else if (env_meta.kind === 2) {
last_commit_seq = seq;
if (env_b64 === last_local_commit_env_b64 && last_local_commit_env_b64) {
set_commit_echo_state('received', seq);
set_status(`commit echo received (seq=${seq})`);
log_output(`commit echo received at seq=${seq}`);
}
const apply_result = await apply_handshake_env(seq, env_b64, { context_label: 'handshake' });
if (!apply_result.ok && !apply_result.buffered) {
update_live_inbox_status(`handshake apply failed at seq=${seq}`);
}
} else {
last_app_seq = seq;
set_status(`app env staged (seq=${seq})`);
log_output(`app env staged from inbox (seq=${seq})`);
await handle_auto_decrypt_app_env();
}
live_inbox_by_seq.delete(seq);
live_inbox_last_ingested_seq = seq;
set_live_inbox_expected_seq(seq + 1);
update_live_inbox_status();
return true;
};

const run_live_inbox_auto_ingest = async () => {
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
const ok = await ingest_live_inbox_seq(seq);
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
return { ok: false, error: 'invalid env' };
}
if (unpacked.kind !== 3) {
set_status('error');
log_output('expected app env (kind=3)');
return { ok: false, error: 'wrong kind' };
}
if (participant_label === 'bob' && !bob_participant_b64) {
set_status('error');
log_output('need bob participant');
return { ok: false, error: 'missing bob participant' };
}
if (participant_label === 'alice' && !alice_participant_b64) {
set_status('error');
log_output('need alice participant');
return { ok: false, error: 'missing alice participant' };
}
set_status(`decrypting as ${participant_label}...`);
log_output('');
const participant_b64 = participant_label === 'bob' ? bob_participant_b64 : alice_participant_b64;
const dec_result = await dm_decrypt(participant_b64, unpacked.payload_b64);
if (!dec_result || !dec_result.ok) {
const error_text = dec_result && dec_result.error ? dec_result.error : 'unknown error';
set_status('error');
log_output(`decrypt failed: ${error_text}`);
return { ok: false, error: error_text };
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
return { ok: true };
};

const handle_auto_decrypt_app_env = async () => {
if (!get_auto_decrypt_app_env_enabled()) {
return false;
}
let attempted = false;
if (bob_participant_b64) {
attempted = true;
const result = await handle_decrypt_app_env('bob');
if (result.ok) {
if (expected_plaintext_input && expected_plaintext_input.value) {
handle_verify_expected();
}
return true;
}
}
if (alice_participant_b64) {
attempted = true;
const result = await handle_decrypt_app_env('alice');
if (result.ok) {
if (expected_plaintext_input && expected_plaintext_input.value) {
handle_verify_expected();
}
return true;
}
}
const message = attempted ? 'auto-decrypt failed; env staged' : 'auto-decrypt skipped; env staged';
set_status(message);
log_output(message);
return false;
};

const build_seq_suffix = (seq) => (Number.isInteger(seq) ? ` (seq=${seq})` : '');

const get_commit_env_b64 = () => {
if (!commit_b64) {
return '';
}
return pack_dm_env(2, commit_b64);
};

const is_local_commit_pending = () => {
const commit_env_b64 = get_commit_env_b64();
if (!commit_env_b64 || !last_local_commit_env_b64) {
return false;
}
return commit_env_b64 === last_local_commit_env_b64;
};

const is_staged_app_env = () => {
const env_b64 = incoming_env_input ? incoming_env_input.value.trim() : '';
if (!env_b64) {
return false;
}
const unpacked = unpack_dm_env(env_b64);
return Boolean(unpacked && unpacked.kind === 3);
};

const handle_run_next_step = async () => {
if (run_next_step_in_flight) {
set_run_next_step_status('last action: run next step already in progress');
return;
}
run_next_step_in_flight = true;
try {
if (welcome_b64 && bob_participant_b64 && !bob_has_joined) {
const joined = await handle_join();
const suffix = build_seq_suffix(last_welcome_seq);
if (joined) {
set_run_next_step_status(`last action: joined bob from welcome${suffix}`);
} else {
set_run_next_step_status('last action: join failed; check status');
}
return;
}
if (welcome_b64 && !bob_participant_b64 && !bob_has_joined) {
set_run_next_step_status('last action: join blocked; missing bob participant');
return;
}
if (commit_b64) {
const is_local = is_local_commit_pending();
if (is_local && commit_echo_state !== 'received') {
set_run_next_step_status('last action: commit pending; waiting for echo');
return;
}
if (!commit_apply_btn || commit_apply_btn.disabled) {
set_run_next_step_status('last action: commit apply unavailable');
return;
}
const applied = await handle_commit_apply();
const seq_note = is_local ? commit_echo_seq : last_commit_seq;
const suffix = build_seq_suffix(seq_note);
if (applied) {
set_run_next_step_status(`last action: applied commit${suffix}`);
} else {
set_run_next_step_status('last action: commit apply failed; check status');
}
return;
}
if (is_staged_app_env()) {
if (!get_auto_decrypt_app_env_enabled()) {
set_run_next_step_status('last action: app env staged; auto-decrypt disabled');
return;
}
const decrypted = await handle_auto_decrypt_app_env();
const suffix = build_seq_suffix(last_app_seq);
if (decrypted) {
set_run_next_step_status(`last action: auto-decrypt attempted${suffix}`);
} else {
set_run_next_step_status('last action: auto-decrypt skipped; env staged');
}
return;
}
set_run_next_step_status('last action: nothing to do');
} finally {
run_next_step_in_flight = false;
}
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
conv_id: '',
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

const parse_coexist_cli_blocks = (block_text) => {
const lines = block_text.split(/\r?\n/);
const blocks = [];
let current_lines = [];
let current_label = '';
const flush_block = () => {
if (!current_lines.length) {
current_label = '';
return;
}
const { parsed, found_keys } = parse_cli_block(current_lines.join('\n'));
if (found_keys.length) {
blocks.push({ label: current_label, parsed, found_keys });
}
current_lines = [];
current_label = '';
};
for (const raw_line of lines) {
const line = raw_line.trim();
if (!line) {
flush_block();
continue;
}
const header_match = line.match(/^(dm|room)\s*:/i);
if (header_match) {
flush_block();
current_label = header_match[1].toLowerCase();
continue;
}
current_lines.push(line);
}
flush_block();
return blocks;
};

const resolve_coexist_cli_blocks = (block_text) => {
if (!block_text || !block_text.trim()) {
return { ok: false, error: 'missing coexist cli block' };
}
const blocks = parse_coexist_cli_blocks(block_text);
if (!blocks.length) {
return { ok: false, error: 'no coexist cli blocks found' };
}
if (blocks.length === 1) {
return { ok: true, dm_block: null, room_block: blocks[0].parsed };
}
let dm_block = null;
let room_block = null;
for (const block of blocks) {
if (block.label === 'dm' && !dm_block) {
dm_block = block.parsed;
}
if (block.label === 'room' && !room_block) {
room_block = block.parsed;
}
}
for (const block of blocks) {
if (!dm_block) {
dm_block = block.parsed;
continue;
}
if (!room_block && block.parsed !== dm_block) {
room_block = block.parsed;
}
}
return { ok: true, dm_block, room_block };
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

const parse_coexist_bundle_json = (payload_text) => {
if (!payload_text || !payload_text.trim()) {
return { ok: false, error: 'bundle input is empty' };
}
try {
const parsed = JSON.parse(payload_text);
return { ok: true, bundle: parsed };
} catch (error) {
return { ok: false, error: 'invalid bundle json' };
}
};

const validate_coexist_bundle = (bundle) => {
if (!bundle || typeof bundle !== 'object') {
return { ok: false, error: 'bundle must be an object' };
}
if (bundle.schema_version !== 'phase5_coexist_bundle_v1') {
return { ok: false, error: 'unsupported bundle schema_version' };
}
const validate_bundle_section_fields = (section, transcript, label) => {
const proof_app_seq_value =
Number.isInteger(section.proof_app_seq) ? section.proof_app_seq : null;
if (proof_app_seq_value !== null) {
if (!Array.isArray(transcript.events)) {
return { ok: false, error: `${label} transcript events missing` };
}
let proof_app_found = false;
for (const event of transcript.events) {
if (!event || event.seq !== proof_app_seq_value || typeof event.env !== 'string') {
continue;
}
const env_bytes = base64_to_bytes(event.env);
if (env_bytes && env_bytes.length > 0 && env_bytes[0] === 3) {
proof_app_found = true;
break;
}
}
if (!proof_app_found) {
return { ok: false, error: `${label} proof_app_seq missing from transcript` };
}
}
if (section.proof_app_msg_id !== undefined && typeof section.proof_app_msg_id !== 'string') {
return { ok: false, error: `${label} proof_app_msg_id must be a string` };
}
if (section.peer_tokens !== undefined && section.peer_tokens !== null) {
if (!section.peer_tokens || typeof section.peer_tokens !== 'object') {
return { ok: false, error: `${label} peer_tokens must be an object` };
}
const peer_tokens = section.peer_tokens;
if (typeof peer_tokens.peer_app_expected !== 'string') {
return { ok: false, error: `${label} peer_tokens.peer_app_expected must be a string` };
}
if (
peer_tokens.peer_app_seq !== null &&
peer_tokens.peer_app_seq !== undefined &&
!Number.isInteger(peer_tokens.peer_app_seq)
) {
return { ok: false, error: `${label} peer_tokens.peer_app_seq must be int or null` };
}
if (typeof peer_tokens.sent_peer_token_plaintext !== 'string') {
return { ok: false, error: `${label} peer_tokens.sent_peer_token_plaintext must be a string` };
}
if (
peer_tokens.sent_peer_token_seq !== null &&
peer_tokens.sent_peer_token_seq !== undefined &&
!Number.isInteger(peer_tokens.sent_peer_token_seq)
) {
return { ok: false, error: `${label} peer_tokens.sent_peer_token_seq must be int or null` };
}
if (typeof peer_tokens.peer_app_expected_match !== 'boolean') {
return { ok: false, error: `${label} peer_tokens.peer_app_expected_match must be a boolean` };
}
}
return { ok: true };
};
const dm_section = bundle.dm && typeof bundle.dm === 'object' ? bundle.dm : null;
const room_section = bundle.room && typeof bundle.room === 'object' ? bundle.room : null;
if (!dm_section || !room_section) {
return { ok: false, error: 'bundle must include dm and room sections' };
}
if (typeof dm_section.expected_plaintext !== 'string') {
return { ok: false, error: 'dm expected_plaintext must be a string' };
}
if (typeof room_section.expected_plaintext !== 'string') {
return { ok: false, error: 'room expected_plaintext must be a string' };
}
const dm_validated = validate_transcript(dm_section.transcript);
if (!dm_validated.ok) {
return { ok: false, error: `dm transcript invalid: ${dm_validated.error}` };
}
const room_validated = validate_transcript(room_section.transcript);
if (!room_validated.ok) {
return { ok: false, error: `room transcript invalid: ${room_validated.error}` };
}
const dm_fields_validated = validate_bundle_section_fields(dm_section, dm_validated.transcript, 'dm');
if (!dm_fields_validated.ok) {
return { ok: false, error: dm_fields_validated.error };
}
const room_fields_validated = validate_bundle_section_fields(
room_section,
room_validated.transcript,
'room'
);
if (!room_fields_validated.ok) {
return { ok: false, error: room_fields_validated.error };
}
return {
ok: true,
bundle: {
schema_version: 'phase5_coexist_bundle_v1',
dm: {
expected_plaintext: dm_section.expected_plaintext,
transcript: dm_validated.transcript,
proof_app_seq: Number.isInteger(dm_section.proof_app_seq) ? dm_section.proof_app_seq : undefined,
proof_app_msg_id:
typeof dm_section.proof_app_msg_id === 'string' ? dm_section.proof_app_msg_id : undefined,
peer_tokens: dm_section.peer_tokens || undefined,
},
room: {
expected_plaintext: room_section.expected_plaintext,
transcript: room_validated.transcript,
proof_app_seq: Number.isInteger(room_section.proof_app_seq) ? room_section.proof_app_seq : undefined,
proof_app_msg_id:
typeof room_section.proof_app_msg_id === 'string' ? room_section.proof_app_msg_id : undefined,
peer_tokens: room_section.peer_tokens || undefined,
},
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
if (commit_seq === null || seq > commit_seq) {
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

const pick_latest_env = (events, kind) => {
if (!Array.isArray(events)) {
return null;
}
let latest = null;
for (const event of events) {
if (!event || typeof event.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(event.env);
if (!env_meta || env_meta.kind !== kind) {
continue;
}
if (!latest || event.seq > latest.seq) {
latest = {
seq: event.seq,
msg_id: event.msg_id,
env: event.env,
};
}
}
return latest;
};

const find_transcript_event_by_env = (events, env_b64, kind) => {
if (!Array.isArray(events) || !env_b64) {
return null;
}
for (const event of events) {
if (!event || event.env !== env_b64) {
continue;
}
const env_meta = parse_live_inbox_env(event.env);
if (!env_meta || env_meta.kind !== kind) {
continue;
}
return { seq: event.seq, msg_id: event.msg_id, env: event.env };
}
return null;
};

const find_transcript_event_by_seq = (events, seq, kind) => {
if (!Array.isArray(events) || !Number.isInteger(seq)) {
return null;
}
for (const event of events) {
if (!event || event.seq !== seq || typeof event.env !== 'string') {
continue;
}
const env_meta = parse_live_inbox_env(event.env);
if (!env_meta || env_meta.kind !== kind) {
continue;
}
return { seq: event.seq, msg_id: event.msg_id, env: event.env };
}
return null;
};

const build_transcript_from_records = (conv_id, records) => {
const events = [];
for (const record of records) {
if (!record || typeof record.env !== 'string') {
continue;
}
events.push({
seq: record.seq,
msg_id: record.msg_id,
env: record.env,
});
}
events.sort((left, right) => left.seq - right.seq);
return {
schema_version: 1,
conv_id,
from_seq: null,
next_seq: null,
events,
};
};

const is_unechoed_local_commit_env = (env_b64) => {
if (!env_b64 || !last_local_commit_env_b64) {
return false;
}
if (env_b64 !== last_local_commit_env_b64) {
return false;
}
return commit_echo_state !== 'received';
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
if (parsed.conv_id) {
const normalized_conv_id = normalize_conv_id(parsed.conv_id);
if (normalized_conv_id !== '(none)' && active_conv_id === '(none)') {
save_active_conv_state();
active_conv_id = normalized_conv_id;
apply_conv_state(get_conv_state(active_conv_id));
update_conv_status_label();
}
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

const set_coexist_bundle_status = (message) => {
if (!coexist_phase5_bundle_status_line) {
return;
}
coexist_phase5_bundle_status_line.textContent = message;
};

const handle_import_coexist_bundle = async () => {
const file = coexist_phase5_bundle_file_input && coexist_phase5_bundle_file_input.files
? coexist_phase5_bundle_file_input.files[0]
: null;
if (!file) {
set_coexist_bundle_status('no bundle file selected');
set_status('error');
return;
}
let bundle_text = '';
try {
bundle_text = await file.text();
} catch (error) {
set_coexist_bundle_status('failed reading bundle file');
set_status('error');
return;
}
const parsed = parse_coexist_bundle_json(bundle_text);
if (!parsed.ok) {
set_coexist_bundle_status(parsed.error);
set_status('error');
last_imported_coexist_bundle = null;
return;
}
const validated = validate_coexist_bundle(parsed.bundle);
if (!validated.ok) {
set_coexist_bundle_status(validated.error);
set_status('error');
last_imported_coexist_bundle = null;
return;
}
last_imported_coexist_bundle = validated.bundle;
const dm_conv_id = validated.bundle.dm.transcript.conv_id;
const room_conv_id_value = validated.bundle.room.transcript.conv_id;
set_coexist_bundle_status(
`coexist bundle imported (dm conv_id=${dm_conv_id}, room conv_id=${room_conv_id_value})`
);
set_status('coexist bundle imported');
if (coexist_phase5_bundle_auto_run_input && coexist_phase5_bundle_auto_run_input.checked) {
void run_coexist_phase5_proof_wizard();
}
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
last_imported_transcript = transcript;
last_imported_digest_note = digest_note;
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

window.addEventListener('gateway.session.ready', (event) => {
const detail = event && event.detail ? event.detail : null;
gateway_session_token = detail && typeof detail.session_token === 'string' ? detail.session_token : '';
gateway_user_id = detail && typeof detail.user_id === 'string' ? detail.user_id : '';
gateway_http_base_url =
detail && typeof detail.http_base_url === 'string' ? detail.http_base_url : '';
if (gateway_session_token && gateway_http_base_url) {
const user_note = gateway_user_id ? ` (user_id=${gateway_user_id})` : '';
set_dm_bootstrap_status(`gateway session ready${user_note}`);
return;
}
set_dm_bootstrap_status('gateway session not ready');
});

window.addEventListener('social.peer.selected', (event) => {
const detail = event && event.detail ? event.detail : null;
const next_peer_user_id = detail && typeof detail.user_id === 'string' ? detail.user_id.trim() : '';
if (!next_peer_user_id || !dm_bootstrap_peer_input) {
return;
}
dm_bootstrap_peer_input.value = next_peer_user_id;
set_dm_bootstrap_status(`peer selected from social: ${next_peer_user_id}`);
});

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
void maybe_auto_apply_commit(detail.seq, 'auto-applied commit after echo');
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
void run_live_inbox_auto_ingest();
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
outbox_send_init_btn = document.createElement('button');
outbox_send_init_btn.type = 'button';
outbox_send_init_btn.textContent = 'Send init (welcome then commit)';
outbox_send_init_btn.addEventListener('click', () => {
const conv_id = get_active_conv_id_for_send();
if (!conv_id) {
set_outbox_status('outbox: select conv_id before sending');
return;
}
if (!outbox_welcome_env_b64 || !outbox_commit_env_b64) {
set_outbox_status('outbox: init requires welcome+commit in outbox');
return;
}
set_outbox_status('outbox: sending init (welcome)');
dispatch_gateway_send_env(conv_id, outbox_welcome_env_b64);
set_outbox_status('outbox: sending init (commit)');
dispatch_gateway_send_env(conv_id, outbox_commit_env_b64);
last_local_commit_env_b64 = outbox_commit_env_b64;
set_commit_echo_state('waiting', null);
set_outbox_status('outbox: init sent (waiting for commit echo)');
});
outbox_buttons.appendChild(outbox_send_init_btn);
outbox_send_app_btn = document.createElement('button');
outbox_send_app_btn.type = 'button';
outbox_send_app_btn.textContent = 'Send app env';
outbox_send_app_btn.addEventListener('click', () => {
const conv_id = get_active_conv_id_for_send();
if (!conv_id) {
set_outbox_status('outbox: select conv_id before sending');
return;
}
if (!outbox_app_env_b64) {
set_outbox_status('outbox: app env missing in outbox');
return;
}
set_outbox_status('outbox: sending app env');
dispatch_gateway_send_env(conv_id, outbox_app_env_b64);
set_outbox_status('outbox: app env sent');
});
outbox_buttons.appendChild(outbox_send_app_btn);
outbox_container.appendChild(outbox_buttons);
outbox_status_line = document.createElement('div');
outbox_status_line.className = 'dm_outbox_status';
outbox_status_line.textContent = 'outbox: idle';
outbox_container.appendChild(outbox_status_line);

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

const dm_phase5_proof_panel = document.createElement('div');
dm_phase5_proof_panel.className = 'dm_phase5_proof_panel';
const dm_phase5_proof_title = document.createElement('div');
dm_phase5_proof_title.textContent = 'Run DM Proof';
dm_phase5_proof_panel.appendChild(dm_phase5_proof_title);

const dm_phase5_proof_controls = document.createElement('div');
dm_phase5_proof_controls.className = 'button-row';
dm_phase5_proof_run_btn = document.createElement('button');
dm_phase5_proof_run_btn.type = 'button';
dm_phase5_proof_run_btn.textContent = 'Run DM Proof';
dm_phase5_proof_run_btn.addEventListener('click', () => {
void run_dm_phase5_proof_wizard();
});
dm_phase5_proof_controls.appendChild(dm_phase5_proof_run_btn);

const dm_phase5_proof_auto_reply_label = document.createElement('label');
dm_phase5_proof_auto_reply_label.textContent = 'Auto-reply after PASS';
dm_phase5_proof_auto_reply_input = document.createElement('input');
dm_phase5_proof_auto_reply_input.type = 'checkbox';
dm_phase5_proof_auto_reply_label.appendChild(dm_phase5_proof_auto_reply_input);
dm_phase5_proof_controls.appendChild(dm_phase5_proof_auto_reply_label);
const dm_phase5_peer_wait_label = document.createElement('label');
dm_phase5_peer_wait_label.textContent = 'Require peer app after PASS';
dm_phase5_peer_wait_input = document.createElement('input');
dm_phase5_peer_wait_input.type = 'checkbox';
dm_phase5_peer_wait_label.appendChild(dm_phase5_peer_wait_input);
dm_phase5_proof_controls.appendChild(dm_phase5_peer_wait_label);
dm_phase5_proof_panel.appendChild(dm_phase5_proof_controls);

const dm_phase5_proof_reply_label = document.createElement('label');
dm_phase5_proof_reply_label.textContent = 'Reply plaintext';
dm_phase5_proof_reply_input = document.createElement('input');
dm_phase5_proof_reply_input.type = 'text';
dm_phase5_proof_reply_input.size = 48;
dm_phase5_proof_reply_input.value = 'phase5-peer-reply';
dm_phase5_proof_reply_label.appendChild(dm_phase5_proof_reply_input);
dm_phase5_proof_panel.appendChild(dm_phase5_proof_reply_label);
const dm_phase5_peer_expected_label = document.createElement('label');
dm_phase5_peer_expected_label.textContent = 'Peer expected plaintext';
dm_phase5_peer_expected_input = document.createElement('input');
dm_phase5_peer_expected_input.type = 'text';
dm_phase5_peer_expected_input.size = 48;
dm_phase5_peer_expected_input.value = phase5_peer_wait_default_plaintext;
dm_phase5_peer_expected_label.appendChild(dm_phase5_peer_expected_input);
dm_phase5_proof_panel.appendChild(dm_phase5_peer_expected_label);
const dm_phase5_peer_timeout_label = document.createElement('label');
dm_phase5_peer_timeout_label.textContent = 'Peer wait timeout (ms)';
dm_phase5_peer_timeout_input = document.createElement('input');
dm_phase5_peer_timeout_input.type = 'number';
dm_phase5_peer_timeout_input.min = '1000';
dm_phase5_peer_timeout_input.value = String(phase5_peer_wait_default_timeout_ms);
dm_phase5_peer_timeout_label.appendChild(dm_phase5_peer_timeout_input);
dm_phase5_proof_panel.appendChild(dm_phase5_peer_timeout_label);

const dm_phase5_proof_timeline_label = document.createElement('div');
dm_phase5_proof_timeline_label.textContent = 'Proof steps';
dm_phase5_proof_panel.appendChild(dm_phase5_proof_timeline_label);
dm_phase5_proof_timeline = document.createElement('div');
dm_phase5_proof_timeline.className = 'dm_room_phase5_timeline';
dm_phase5_proof_panel.appendChild(dm_phase5_proof_timeline);

const dm_phase5_proof_report_label = document.createElement('label');
dm_phase5_proof_report_label.textContent = 'Proof report';
dm_phase5_proof_report = document.createElement('textarea');
dm_phase5_proof_report.rows = 10;
dm_phase5_proof_report.cols = 70;
dm_phase5_proof_report.readOnly = true;
dm_phase5_proof_report_label.appendChild(dm_phase5_proof_report);
dm_phase5_proof_panel.appendChild(dm_phase5_proof_report_label);

if (outbox_container.parentNode) {
if (outbox_container.nextSibling) {
outbox_container.parentNode.insertBefore(dm_phase5_proof_panel, outbox_container.nextSibling);
} else {
outbox_container.parentNode.appendChild(dm_phase5_proof_panel);
}
} else {
dm_fieldset.appendChild(dm_phase5_proof_panel);
}

const room_container = document.createElement('div');
room_container.className = 'dm_room';
room_container.id = 'dm_room_panel';

const room_title = document.createElement('div');
room_title.textContent = 'MLS Room (gateway)';
room_container.appendChild(room_title);

room_conv_status_line = document.createElement('div');
room_conv_status_line.className = 'dm_room_conv_status';
room_conv_status_line.textContent = `room conv_id: ${room_conv_id}`;
room_container.appendChild(room_conv_status_line);

const room_bind_row = document.createElement('div');
room_bind_row.className = 'button-row';
const room_bind_btn = document.createElement('button');
room_bind_btn.type = 'button';
room_bind_btn.textContent = 'Use active conv_id for room';
room_bind_btn.addEventListener('click', () => {
room_conv_id = active_conv_id;
update_room_conv_status();
set_room_status('room: conv_id bound');
});
room_bind_row.appendChild(room_bind_btn);
room_container.appendChild(room_bind_row);

const room_gateway_title = document.createElement('div');
room_gateway_title.textContent = 'Room management (gateway)';
room_container.appendChild(room_gateway_title);

const room_gateway_invite_label = document.createElement('label');
room_gateway_invite_label.textContent = 'invite_user_ids (comma/space separated)';
room_gateway_invite_input = document.createElement('input');
room_gateway_invite_input.type = 'text';
room_gateway_invite_input.size = 64;
room_gateway_invite_label.appendChild(room_gateway_invite_input);
room_container.appendChild(room_gateway_invite_label);

const room_gateway_remove_label = document.createElement('label');
room_gateway_remove_label.textContent = 'remove_user_id';
room_gateway_remove_input = document.createElement('input');
room_gateway_remove_input.type = 'text';
room_gateway_remove_input.size = 48;
room_gateway_remove_label.appendChild(room_gateway_remove_input);
room_container.appendChild(room_gateway_remove_label);

const room_gateway_buttons = document.createElement('div');
room_gateway_buttons.className = 'button-row';
room_gateway_create_btn = document.createElement('button');
room_gateway_create_btn.type = 'button';
room_gateway_create_btn.textContent = 'Create room';
room_gateway_create_btn.addEventListener('click', () => {
void handle_room_create_gateway();
});
room_gateway_buttons.appendChild(room_gateway_create_btn);

room_gateway_invite_btn = document.createElement('button');
room_gateway_invite_btn.type = 'button';
room_gateway_invite_btn.textContent = 'Invite';
room_gateway_invite_btn.addEventListener('click', () => {
void handle_room_invite_gateway();
});
room_gateway_buttons.appendChild(room_gateway_invite_btn);

room_gateway_remove_btn = document.createElement('button');
room_gateway_remove_btn.type = 'button';
room_gateway_remove_btn.textContent = 'Remove';
room_gateway_remove_btn.addEventListener('click', () => {
void handle_room_remove_gateway();
});
room_gateway_buttons.appendChild(room_gateway_remove_btn);
room_container.appendChild(room_gateway_buttons);

const room_fetch_title = document.createElement('div');
room_fetch_title.textContent = 'Fetch room peer keypackages';
room_container.appendChild(room_fetch_title);

const room_peer_fetch_label = document.createElement('label');
room_peer_fetch_label.textContent = 'peer_user_ids (comma/space separated)';
room_peer_fetch_input = document.createElement('input');
room_peer_fetch_input.type = 'text';
room_peer_fetch_input.size = 64;
room_peer_fetch_label.appendChild(room_peer_fetch_input);
room_container.appendChild(room_peer_fetch_label);

const room_peer_fetch_count_label = document.createElement('label');
room_peer_fetch_count_label.textContent = 'count';
room_peer_fetch_count_input = document.createElement('input');
room_peer_fetch_count_input.type = 'number';
room_peer_fetch_count_input.min = '1';
room_peer_fetch_count_input.value = '1';
room_peer_fetch_count_label.appendChild(room_peer_fetch_count_input);
room_container.appendChild(room_peer_fetch_count_label);

const room_peer_fetch_row = document.createElement('div');
room_peer_fetch_row.className = 'button-row';
room_peer_fetch_btn = document.createElement('button');
room_peer_fetch_btn.type = 'button';
room_peer_fetch_btn.textContent = 'Fetch keypackages for init';
room_peer_fetch_btn.addEventListener('click', () => {
void handle_room_fetch_peer_keypackages();
});
room_peer_fetch_row.appendChild(room_peer_fetch_btn);
room_container.appendChild(room_peer_fetch_row);

const room_add_fetch_label = document.createElement('label');
room_add_fetch_label.textContent = 'add_member_user_id';
room_add_user_id_input = document.createElement('input');
room_add_user_id_input.type = 'text';
room_add_user_id_input.size = 48;
room_add_fetch_label.appendChild(room_add_user_id_input);
room_container.appendChild(room_add_fetch_label);

const room_add_fetch_row = document.createElement('div');
room_add_fetch_row.className = 'button-row';
room_add_fetch_btn = document.createElement('button');
room_add_fetch_btn.type = 'button';
room_add_fetch_btn.textContent = 'Fetch keypackage for add';
room_add_fetch_btn.addEventListener('click', () => {
void handle_room_fetch_add_keypackage();
});
room_add_fetch_row.appendChild(room_add_fetch_btn);
room_container.appendChild(room_add_fetch_row);

const room_keypackages_label = document.createElement('label');
room_keypackages_label.textContent = 'room_peer_keypackages (one per line)';
room_keypackages_input = document.createElement('textarea');
room_keypackages_input.rows = 4;
room_keypackages_input.cols = 64;
room_keypackages_label.appendChild(room_keypackages_input);
room_container.appendChild(room_keypackages_label);

const room_add_label = document.createElement('label');
room_add_label.textContent = 'room_add_peer_keypackage';
room_add_keypackage_input = document.createElement('textarea');
room_add_keypackage_input.rows = 2;
room_add_keypackage_input.cols = 64;
room_add_label.appendChild(room_add_keypackage_input);
room_container.appendChild(room_add_label);

const room_welcome_label = document.createElement('label');
room_welcome_label.textContent = 'room_welcome_env_b64 (kind=1)';
room_welcome_env_input = document.createElement('textarea');
room_welcome_env_input.rows = 3;
room_welcome_env_input.cols = 64;
room_welcome_label.appendChild(room_welcome_env_input);
room_container.appendChild(room_welcome_label);

const room_welcome_controls = document.createElement('div');
room_welcome_controls.className = 'button-row';
const room_welcome_load_btn = document.createElement('button');
room_welcome_load_btn.type = 'button';
room_welcome_load_btn.textContent = 'Load latest welcome from transcript';
room_welcome_load_btn.addEventListener('click', () => {
void handle_room_load_latest_welcome();
});
room_welcome_controls.appendChild(room_welcome_load_btn);
const room_welcome_auto_label = document.createElement('label');
room_welcome_auto_label.textContent = 'Auto-join when welcome loaded';
room_welcome_auto_join_input = document.createElement('input');
room_welcome_auto_join_input.type = 'checkbox';
room_welcome_auto_label.appendChild(room_welcome_auto_join_input);
room_welcome_controls.appendChild(room_welcome_auto_label);
room_container.appendChild(room_welcome_controls);

const coexist_phase5_panel = document.createElement('div');
coexist_phase5_panel.className = 'dm_room_phase5_proof';
const coexist_phase5_title = document.createElement('div');
coexist_phase5_title.textContent = 'Phase 5 Coexist Proof';
coexist_phase5_panel.appendChild(coexist_phase5_title);

const coexist_phase5_controls = document.createElement('div');
coexist_phase5_controls.className = 'button-row';
coexist_phase5_proof_run_btn = document.createElement('button');
coexist_phase5_proof_run_btn.type = 'button';
coexist_phase5_proof_run_btn.textContent = 'Run Coexist Proof (DM + Room)';
coexist_phase5_proof_run_btn.addEventListener('click', () => {
void run_coexist_phase5_proof_wizard();
});
coexist_phase5_controls.appendChild(coexist_phase5_proof_run_btn);
const coexist_phase5_auto_reply_label = document.createElement('label');
coexist_phase5_auto_reply_label.textContent = 'Auto-reply after PASS';
coexist_phase5_proof_auto_reply_input = document.createElement('input');
coexist_phase5_proof_auto_reply_input.type = 'checkbox';
coexist_phase5_auto_reply_label.appendChild(coexist_phase5_proof_auto_reply_input);
coexist_phase5_controls.appendChild(coexist_phase5_auto_reply_label);
const coexist_phase5_peer_wait_label = document.createElement('label');
coexist_phase5_peer_wait_label.textContent = 'Require peer app after PASS';
coexist_phase5_peer_wait_input = document.createElement('input');
coexist_phase5_peer_wait_input.type = 'checkbox';
coexist_phase5_peer_wait_label.appendChild(coexist_phase5_peer_wait_input);
coexist_phase5_controls.appendChild(coexist_phase5_peer_wait_label);
coexist_phase5_panel.appendChild(coexist_phase5_controls);

const coexist_bundle_label = document.createElement('label');
coexist_bundle_label.textContent = 'Coexist bundle JSON';
coexist_phase5_bundle_file_input = document.createElement('input');
coexist_phase5_bundle_file_input.type = 'file';
coexist_phase5_bundle_file_input.accept = 'application/json';
coexist_bundle_label.appendChild(coexist_phase5_bundle_file_input);
coexist_phase5_panel.appendChild(coexist_bundle_label);

const coexist_bundle_controls = document.createElement('div');
coexist_bundle_controls.className = 'button-row';
coexist_phase5_bundle_import_btn = document.createElement('button');
coexist_phase5_bundle_import_btn.type = 'button';
coexist_phase5_bundle_import_btn.textContent = 'Import bundle';
coexist_phase5_bundle_import_btn.addEventListener('click', () => {
void handle_import_coexist_bundle();
});
coexist_bundle_controls.appendChild(coexist_phase5_bundle_import_btn);
const coexist_bundle_auto_run_label = document.createElement('label');
coexist_bundle_auto_run_label.textContent = 'Auto-run after import';
coexist_phase5_bundle_auto_run_input = document.createElement('input');
coexist_phase5_bundle_auto_run_input.type = 'checkbox';
coexist_bundle_auto_run_label.appendChild(coexist_phase5_bundle_auto_run_input);
coexist_bundle_controls.appendChild(coexist_bundle_auto_run_label);
coexist_phase5_panel.appendChild(coexist_bundle_controls);

coexist_phase5_bundle_status_line = document.createElement('div');
coexist_phase5_bundle_status_line.className = 'dm_room_status';
coexist_phase5_bundle_status_line.textContent = 'coexist bundle: idle';
coexist_phase5_panel.appendChild(coexist_phase5_bundle_status_line);

const coexist_phase5_cli_label = document.createElement('label');
coexist_phase5_cli_label.textContent = 'Paste coexist CLI output';
coexist_phase5_proof_cli_input = document.createElement('textarea');
coexist_phase5_proof_cli_input.rows = 8;
coexist_phase5_proof_cli_input.cols = 70;
coexist_phase5_cli_label.appendChild(coexist_phase5_proof_cli_input);
coexist_phase5_panel.appendChild(coexist_phase5_cli_label);

const coexist_phase5_reply_label = document.createElement('label');
coexist_phase5_reply_label.textContent = 'Reply plaintext';
coexist_phase5_proof_reply_input = document.createElement('input');
coexist_phase5_proof_reply_input.type = 'text';
coexist_phase5_proof_reply_input.size = 48;
coexist_phase5_proof_reply_input.value = 'phase5-coexist-peer-reply';
coexist_phase5_reply_label.appendChild(coexist_phase5_proof_reply_input);
coexist_phase5_panel.appendChild(coexist_phase5_reply_label);
const coexist_phase5_peer_expected_label = document.createElement('label');
coexist_phase5_peer_expected_label.textContent = 'Peer expected plaintext';
coexist_phase5_peer_expected_input = document.createElement('input');
coexist_phase5_peer_expected_input.type = 'text';
coexist_phase5_peer_expected_input.size = 48;
coexist_phase5_peer_expected_input.value = phase5_peer_wait_default_plaintext;
coexist_phase5_peer_expected_label.appendChild(coexist_phase5_peer_expected_input);
coexist_phase5_panel.appendChild(coexist_phase5_peer_expected_label);
const coexist_phase5_peer_timeout_label = document.createElement('label');
coexist_phase5_peer_timeout_label.textContent = 'Peer wait timeout (ms)';
coexist_phase5_peer_timeout_input = document.createElement('input');
coexist_phase5_peer_timeout_input.type = 'number';
coexist_phase5_peer_timeout_input.min = '1000';
coexist_phase5_peer_timeout_input.value = String(phase5_peer_wait_default_timeout_ms);
coexist_phase5_peer_timeout_label.appendChild(coexist_phase5_peer_timeout_input);
coexist_phase5_panel.appendChild(coexist_phase5_peer_timeout_label);

const coexist_phase5_timeline_label = document.createElement('div');
coexist_phase5_timeline_label.textContent = 'Combined proof steps';
coexist_phase5_panel.appendChild(coexist_phase5_timeline_label);
coexist_phase5_proof_timeline = document.createElement('div');
coexist_phase5_proof_timeline.className = 'dm_room_phase5_timeline';
coexist_phase5_panel.appendChild(coexist_phase5_proof_timeline);

const coexist_phase5_report_label = document.createElement('label');
coexist_phase5_report_label.textContent = 'Combined proof report';
coexist_phase5_proof_report = document.createElement('textarea');
coexist_phase5_proof_report.rows = 12;
coexist_phase5_proof_report.cols = 70;
coexist_phase5_proof_report.readOnly = true;
coexist_phase5_report_label.appendChild(coexist_phase5_proof_report);
coexist_phase5_panel.appendChild(coexist_phase5_report_label);

room_container.appendChild(coexist_phase5_panel);

const room_phase5_proof_panel = document.createElement('div');
room_phase5_proof_panel.className = 'dm_room_phase5_proof';
const room_phase5_proof_title = document.createElement('div');
room_phase5_proof_title.textContent = 'Phase 5 Proof Wizard';
room_phase5_proof_panel.appendChild(room_phase5_proof_title);

const room_phase5_proof_controls = document.createElement('div');
room_phase5_proof_controls.className = 'button-row';
room_phase5_proof_run_btn = document.createElement('button');
room_phase5_proof_run_btn.type = 'button';
room_phase5_proof_run_btn.textContent = 'Run Proof';
room_phase5_proof_run_btn.addEventListener('click', () => {
void run_room_phase5_proof_wizard();
});
room_phase5_proof_controls.appendChild(room_phase5_proof_run_btn);

const room_phase5_proof_auto_reply_label = document.createElement('label');
room_phase5_proof_auto_reply_label.textContent = 'Auto-reply after PASS';
room_phase5_proof_auto_reply_input = document.createElement('input');
room_phase5_proof_auto_reply_input.type = 'checkbox';
room_phase5_proof_auto_reply_label.appendChild(room_phase5_proof_auto_reply_input);
room_phase5_proof_controls.appendChild(room_phase5_proof_auto_reply_label);
const room_phase5_peer_wait_label = document.createElement('label');
room_phase5_peer_wait_label.textContent = 'Require peer app after PASS';
room_phase5_peer_wait_input = document.createElement('input');
room_phase5_peer_wait_input.type = 'checkbox';
room_phase5_peer_wait_label.appendChild(room_phase5_peer_wait_input);
room_phase5_proof_controls.appendChild(room_phase5_peer_wait_label);
room_phase5_proof_panel.appendChild(room_phase5_proof_controls);

const room_phase5_proof_reply_label = document.createElement('label');
room_phase5_proof_reply_label.textContent = 'Reply plaintext';
room_phase5_proof_reply_input = document.createElement('input');
room_phase5_proof_reply_input.type = 'text';
room_phase5_proof_reply_input.size = 48;
room_phase5_proof_reply_input.value = 'phase5-peer-reply';
room_phase5_proof_reply_label.appendChild(room_phase5_proof_reply_input);
room_phase5_proof_panel.appendChild(room_phase5_proof_reply_label);
const room_phase5_peer_expected_label = document.createElement('label');
room_phase5_peer_expected_label.textContent = 'Peer expected plaintext';
room_phase5_peer_expected_input = document.createElement('input');
room_phase5_peer_expected_input.type = 'text';
room_phase5_peer_expected_input.size = 48;
room_phase5_peer_expected_input.value = phase5_peer_wait_default_plaintext;
room_phase5_peer_expected_label.appendChild(room_phase5_peer_expected_input);
room_phase5_proof_panel.appendChild(room_phase5_peer_expected_label);
const room_phase5_peer_timeout_label = document.createElement('label');
room_phase5_peer_timeout_label.textContent = 'Peer wait timeout (ms)';
room_phase5_peer_timeout_input = document.createElement('input');
room_phase5_peer_timeout_input.type = 'number';
room_phase5_peer_timeout_input.min = '1000';
room_phase5_peer_timeout_input.value = String(phase5_peer_wait_default_timeout_ms);
room_phase5_peer_timeout_label.appendChild(room_phase5_peer_timeout_input);
room_phase5_proof_panel.appendChild(room_phase5_peer_timeout_label);

const room_phase5_proof_timeline_label = document.createElement('div');
room_phase5_proof_timeline_label.textContent = 'Proof steps';
room_phase5_proof_panel.appendChild(room_phase5_proof_timeline_label);
room_phase5_proof_timeline = document.createElement('div');
room_phase5_proof_timeline.className = 'dm_room_phase5_timeline';
room_phase5_proof_panel.appendChild(room_phase5_proof_timeline);

const room_phase5_proof_report_label = document.createElement('label');
room_phase5_proof_report_label.textContent = 'Proof report';
room_phase5_proof_report = document.createElement('textarea');
room_phase5_proof_report.rows = 10;
room_phase5_proof_report.cols = 70;
room_phase5_proof_report.readOnly = true;
room_phase5_proof_report_label.appendChild(room_phase5_proof_report);
room_phase5_proof_panel.appendChild(room_phase5_proof_report_label);

room_container.appendChild(room_phase5_proof_panel);

const room_buttons = document.createElement('div');
room_buttons.className = 'button-row';
const room_init_btn = document.createElement('button');
room_init_btn.type = 'button';
room_init_btn.textContent = 'Room init (owner)';
room_init_btn.addEventListener('click', () => {
void handle_room_init();
});
room_buttons.appendChild(room_init_btn);

const room_add_btn = document.createElement('button');
room_add_btn.type = 'button';
room_add_btn.textContent = 'Room add member (owner)';
room_add_btn.addEventListener('click', () => {
void handle_room_add();
});
room_buttons.appendChild(room_add_btn);

room_join_btn = document.createElement('button');
room_join_btn.type = 'button';
room_join_btn.textContent = 'Room join (peer)';
room_join_btn.addEventListener('click', () => {
void handle_room_join_peer();
});
room_buttons.appendChild(room_join_btn);
room_container.appendChild(room_buttons);

const room_participant_label = document.createElement('label');
room_participant_label.textContent = 'room_participant';
room_participant_select = document.createElement('select');
const room_participant_bob = document.createElement('option');
room_participant_bob.value = 'bob';
room_participant_bob.textContent = 'bob (peer)';
room_participant_select.appendChild(room_participant_bob);
const room_participant_alice = document.createElement('option');
room_participant_alice.value = 'alice';
room_participant_alice.textContent = 'alice (owner)';
room_participant_select.appendChild(room_participant_alice);
room_participant_label.appendChild(room_participant_select);
room_container.appendChild(room_participant_label);

const room_send_label = document.createElement('label');
room_send_label.textContent = 'room_app_plaintext';
room_send_plaintext_input = document.createElement('textarea');
room_send_plaintext_input.rows = 2;
room_send_plaintext_input.cols = 64;
room_send_label.appendChild(room_send_plaintext_input);
room_container.appendChild(room_send_label);

const room_send_row = document.createElement('div');
room_send_row.className = 'button-row';
room_send_btn = document.createElement('button');
room_send_btn.type = 'button';
room_send_btn.textContent = 'Room send app (current participant)';
room_send_btn.addEventListener('click', () => {
void handle_room_send_app();
});
room_send_row.appendChild(room_send_btn);
room_container.appendChild(room_send_row);

const room_decrypt_row = document.createElement('div');
room_decrypt_row.className = 'button-row';
room_decrypt_btn = document.createElement('button');
room_decrypt_btn.type = 'button';
room_decrypt_btn.textContent = 'Room decrypt latest app';
room_decrypt_btn.addEventListener('click', () => {
void handle_room_decrypt_latest_app();
});
room_decrypt_row.appendChild(room_decrypt_btn);
room_container.appendChild(room_decrypt_row);

const room_msg_id_label = document.createElement('label');
room_msg_id_label.textContent = 'room_latest_msg_id';
room_decrypt_msg_id_output = document.createElement('input');
room_decrypt_msg_id_output.type = 'text';
room_decrypt_msg_id_output.readOnly = true;
room_decrypt_msg_id_output.size = 36;
room_msg_id_label.appendChild(room_decrypt_msg_id_output);
room_container.appendChild(room_msg_id_label);

const room_plaintext_label = document.createElement('label');
room_plaintext_label.textContent = 'room_latest_plaintext';
room_decrypt_plaintext_output = document.createElement('textarea');
room_decrypt_plaintext_output.rows = 2;
room_decrypt_plaintext_output.cols = 64;
room_decrypt_plaintext_output.readOnly = true;
room_plaintext_label.appendChild(room_decrypt_plaintext_output);
room_container.appendChild(room_plaintext_label);

room_status_line = document.createElement('div');
room_status_line.className = 'dm_room_status';
room_status_line.textContent = 'room: idle';
room_container.appendChild(room_status_line);

const room_anchor = dm_phase5_proof_panel || outbox_container;
if (room_anchor.parentNode) {
if (room_anchor.nextSibling) {
room_anchor.parentNode.insertBefore(room_container, room_anchor.nextSibling);
} else {
room_anchor.parentNode.appendChild(room_container);
}
} else {
dm_fieldset.appendChild(room_container);
}

const bootstrap_container = document.createElement('div');
bootstrap_container.className = 'dm_bootstrap';

const bootstrap_title = document.createElement('div');
bootstrap_title.textContent = 'DM bootstrap';
bootstrap_container.appendChild(bootstrap_title);

const bootstrap_peer_label = document.createElement('label');
bootstrap_peer_label.textContent = 'peer_user_id';
dm_bootstrap_peer_input = document.createElement('input');
dm_bootstrap_peer_input.type = 'text';
dm_bootstrap_peer_input.size = 48;
bootstrap_peer_label.appendChild(dm_bootstrap_peer_input);
bootstrap_container.appendChild(bootstrap_peer_label);

const bootstrap_count_label = document.createElement('label');
bootstrap_count_label.textContent = 'keypackage_count';
dm_bootstrap_count_input = document.createElement('input');
dm_bootstrap_count_input.type = 'number';
dm_bootstrap_count_input.min = '1';
dm_bootstrap_count_input.value = '1';
bootstrap_count_label.appendChild(dm_bootstrap_count_input);
bootstrap_container.appendChild(bootstrap_count_label);

const bootstrap_buttons = document.createElement('div');
bootstrap_buttons.className = 'button-row';
dm_bootstrap_fetch_btn = document.createElement('button');
dm_bootstrap_fetch_btn.type = 'button';
dm_bootstrap_fetch_btn.textContent = 'Fetch peer keypackage';
dm_bootstrap_fetch_btn.addEventListener('click', () => {
void handle_fetch_peer_keypackage();
});
bootstrap_buttons.appendChild(dm_bootstrap_fetch_btn);

dm_bootstrap_publish_btn = document.createElement('button');
dm_bootstrap_publish_btn.type = 'button';
dm_bootstrap_publish_btn.textContent = 'Publish my keypackage';
dm_bootstrap_publish_btn.addEventListener('click', () => {
void handle_publish_keypackage();
});
bootstrap_buttons.appendChild(dm_bootstrap_publish_btn);
bootstrap_container.appendChild(bootstrap_buttons);

dm_bootstrap_status_line = document.createElement('div');
dm_bootstrap_status_line.className = 'dm_bootstrap_status';
dm_bootstrap_status_line.textContent = 'gateway session not ready';
bootstrap_container.appendChild(dm_bootstrap_status_line);

if (room_container.parentNode) {
if (room_container.nextSibling) {
room_container.parentNode.insertBefore(bootstrap_container, room_container.nextSibling);
} else {
room_container.parentNode.appendChild(bootstrap_container);
}
} else {
dm_fieldset.appendChild(bootstrap_container);
}

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
void handle_import_welcome_env();
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
void run_live_inbox_auto_ingest();
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
void run_live_inbox_auto_ingest();
}
});
live_inbox_auto_label.appendChild(live_inbox_auto_input);
live_inbox_auto_label.appendChild(document.createTextNode(' Auto-ingest in order'));
live_inbox_container.appendChild(live_inbox_auto_label);

const auto_join_on_welcome_label = document.createElement('label');
auto_join_on_welcome_input = document.createElement('input');
auto_join_on_welcome_input.type = 'checkbox';
auto_join_on_welcome_label.appendChild(auto_join_on_welcome_input);
auto_join_on_welcome_label.appendChild(document.createTextNode(' Auto-join on welcome ingest'));
live_inbox_container.appendChild(auto_join_on_welcome_label);

const auto_apply_commit_label = document.createElement('label');
auto_apply_commit_input = document.createElement('input');
auto_apply_commit_input.type = 'checkbox';
auto_apply_commit_label.appendChild(auto_apply_commit_input);
auto_apply_commit_label.appendChild(document.createTextNode(' Auto-apply commit after echo'));
live_inbox_container.appendChild(auto_apply_commit_label);

const auto_decrypt_app_label = document.createElement('label');
auto_decrypt_app_env_input = document.createElement('input');
auto_decrypt_app_env_input.type = 'checkbox';
auto_decrypt_app_label.appendChild(auto_decrypt_app_env_input);
auto_decrypt_app_label.appendChild(document.createTextNode(' Auto-decrypt app env on ingest'));
live_inbox_container.appendChild(auto_decrypt_app_label);

const live_inbox_expected_label = document.createElement('label');
live_inbox_expected_label.textContent = 'expected_seq';
live_inbox_expected_input = document.createElement('input');
live_inbox_expected_input.type = 'number';
live_inbox_expected_input.min = '1';
live_inbox_expected_input.value = String(live_inbox_expected_seq);
live_inbox_expected_input.addEventListener('change', () => {
set_live_inbox_expected_seq(live_inbox_expected_input.value);
if (get_live_inbox_enabled()) {
void run_live_inbox_auto_ingest();
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
void ingest_live_inbox_seq(live_inbox_expected_seq);
});
live_inbox_buttons.appendChild(live_inbox_ingest_btn);

run_next_step_btn = document.createElement('button');
run_next_step_btn.type = 'button';
run_next_step_btn.textContent = 'Run next step';
run_next_step_btn.addEventListener('click', () => {
void handle_run_next_step();
});
live_inbox_buttons.appendChild(run_next_step_btn);
live_inbox_container.appendChild(live_inbox_buttons);

live_inbox_status_line = document.createElement('div');
live_inbox_status_line.className = 'dm_live_inbox_status';
live_inbox_container.appendChild(live_inbox_status_line);
update_live_inbox_controls();
update_live_inbox_status();

run_next_step_status_line = document.createElement('div');
run_next_step_status_line.className = 'dm_live_inbox_status';
run_next_step_status_line.textContent = 'last action: idle';
live_inbox_container.appendChild(run_next_step_status_line);

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
update_room_conv_status();

window.addEventListener('conv.selected', (event) => {
const detail = event && event.detail ? event.detail : null;
const next_conv_id = normalize_conv_id(detail && typeof detail.conv_id === 'string' ? detail.conv_id : '');
if (next_conv_id === active_conv_id) {
return;
}
const previous_conv_id = active_conv_id;
save_active_conv_state();
active_conv_id = next_conv_id;
apply_conv_state(get_conv_state(active_conv_id));
set_status('idle');
update_conv_status_label();
if (room_conv_id === previous_conv_id) {
room_conv_id = active_conv_id;
update_room_conv_status();
}
});
