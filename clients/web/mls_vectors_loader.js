const wasm_path = 'vendor/mls_harness.wasm';
const wasm_missing_message = 'WASM module not built. Run: tools/mls_harness/build_wasm.sh then serve over HTTP.';
let wasm_ready;

const load_wasm = async () => {
if (wasm_ready) {
return wasm_ready;
}
wasm_ready = (async () => {
const go = new Go();
let response;
try {
response = await fetch(wasm_path);
} catch (err) {
throw new Error(wasm_missing_message);
}
if (!response.ok) {
throw new Error(`${wasm_missing_message} (status ${response.status})`);
}
const buffer = await response.arrayBuffer();
const result = await WebAssembly.instantiate(buffer, go.importObject);
go.run(result.instance);
})();
return wasm_ready;
};

export const ensure_wasm_ready = async () => {
await load_wasm();
};

export const verify_vectors_from_url = async (vector_url) => {
await load_wasm();
const response = await fetch(vector_url);
if (!response.ok) {
throw new Error(`failed to fetch vectors: ${response.status}`);
}
const vector_body = await response.text();
const output = globalThis.verifyVectors(vector_body);
return output;
};

export const dm_create_participant = async (name, seed_int) => {
await load_wasm();
return globalThis.dmCreateParticipant(name, seed_int);
};

export const dm_init = async (participant_b64, peer_keypackage_b64, group_id_b64, seed_int) => {
await load_wasm();
return globalThis.dmInit(participant_b64, peer_keypackage_b64, group_id_b64, seed_int);
};

export const dm_join = async (participant_b64, welcome_b64) => {
await load_wasm();
return globalThis.dmJoin(participant_b64, welcome_b64);
};

export const dm_commit_apply = async (participant_b64, commit_b64) => {
await load_wasm();
return globalThis.dmCommitApply(participant_b64, commit_b64);
};

export const dm_encrypt = async (participant_b64, plaintext) => {
await load_wasm();
return globalThis.dmEncrypt(participant_b64, plaintext);
};

export const dm_decrypt = async (participant_b64, ciphertext_b64) => {
await load_wasm();
return globalThis.dmDecrypt(participant_b64, ciphertext_b64);
};
