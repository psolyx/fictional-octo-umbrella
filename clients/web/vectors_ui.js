import { verify_vectors_from_url } from './mls_vectors_loader.js';

const run_vectors_btn = document.getElementById('run_vectors');
const vector_status = document.getElementById('vector_status');
const vector_output = document.getElementById('vector_output');
const vector_path = 'vectors/dm_smoke_v1.json';

const render_result = (result) => {
if (!result) {
vector_status.textContent = 'failed';
vector_output.textContent = 'error=empty result';
return;
}
if (result.ok) {
vector_status.textContent = 'ok';
vector_output.textContent = `digest=${result.digest}`;
return;
}
const error_text = result.error || 'unknown error';
vector_status.textContent = 'failed';
vector_output.textContent = `digest=${result.digest || ''} error=${error_text}`;
};

const handle_run_vectors = async () => {
vector_status.textContent = 'running...';
vector_output.textContent = '';
try {
const result = await verify_vectors_from_url(vector_path);
render_result(result);
} catch (err) {
vector_status.textContent = 'failed';
const message = err && err.message ? err.message : String(err);
vector_output.textContent = `error=${message}`;
}
};

if (run_vectors_btn) {
run_vectors_btn.addEventListener('click', handle_run_vectors);
}

