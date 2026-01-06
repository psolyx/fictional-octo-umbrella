#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
vendor_dir="${repo_root}/clients/web/vendor"

mkdir -p "${vendor_dir}"

: "${GOFLAGS:=-mod=vendor}"
: "${GOTOOLCHAIN:=local}"

export GOFLAGS
export GOTOOLCHAIN

GOOS=js GOARCH=wasm go -C "${script_dir}" build -o "${vendor_dir}/mls_harness.wasm" ./cmd/mls-wasm

goroot="$(go env GOROOT)"
wasm_exec_candidates=("${goroot}/misc/wasm/wasm_exec.js" "${goroot}/lib/wasm/wasm_exec.js")

for candidate in "${wasm_exec_candidates[@]}"; do
if [[ -f "${candidate}" ]]; then
cp "${candidate}" "${vendor_dir}/wasm_exec.js"
exit 0
fi
done

echo "wasm_exec.js not found in expected locations" >&2
exit 1
