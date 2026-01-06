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

