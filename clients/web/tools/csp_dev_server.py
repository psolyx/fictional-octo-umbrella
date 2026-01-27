#!/usr/bin/env python3
import argparse
import http.server
import html.parser
import mimetypes
import pathlib
import subprocess
import sys
import traceback


class csp_meta_parser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csp_content = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta":
            return
        attr_map = {key.lower(): value for key, value in attrs}
        http_equiv = attr_map.get("http-equiv")
        if http_equiv is None or http_equiv.lower() != "content-security-policy":
            return
        content = attr_map.get("content")
        if content:
            self.csp_content = content.strip()


def extract_csp(index_path: pathlib.Path) -> str:
    html_text = index_path.read_text(encoding="utf-8")
    parser = csp_meta_parser()
    parser.feed(html_text)
    if not parser.csp_content:
        raise ValueError("missing Content-Security-Policy meta tag in index.html")
    return parser.csp_content


def parse_csp_directives(csp_value: str) -> dict:
    directives = {}
    for chunk in csp_value.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split()
        if not parts:
            continue
        directive = parts[0].lower()
        values = [item for item in parts[1:] if item]
        directives.setdefault(directive, []).extend(values)
    return directives


def validate_csp(csp_value: str) -> list:
    errors = []
    directives = parse_csp_directives(csp_value)
    connect_src = directives.get("connect-src")
    if not connect_src:
        errors.append("missing connect-src directive")
    else:
        required_tokens = {"'self'", "ws:", "wss:"}
        missing_tokens = sorted(required_tokens - set(connect_src))
        if missing_tokens:
            errors.append("connect-src missing: " + ", ".join(missing_tokens))
    script_src = directives.get("script-src")
    if not script_src or "'wasm-unsafe-eval'" not in script_src:
        errors.append("script-src must include 'wasm-unsafe-eval'")
    all_tokens = set()
    for values in directives.values():
        all_tokens.update(values)
    if "'unsafe-eval'" in all_tokens:
        errors.append("CSP must not include 'unsafe-eval'")
    return errors


def ensure_frame_ancestors(csp_value: str) -> str:
    directives = parse_csp_directives(csp_value)
    if "frame-ancestors" in directives:
        return csp_value
    if csp_value.endswith(";"):
        return f"{csp_value} frame-ancestors 'none'"
    return f"{csp_value}; frame-ancestors 'none'"


def run_check(index_path: pathlib.Path) -> int:
    try:
        csp_value = extract_csp(index_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = validate_csp(csp_value)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(csp_value)
    return 0


def run_server(index_path: pathlib.Path, host: str, port: int) -> int:
    try:
        csp_value = extract_csp(index_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = validate_csp(csp_value)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    csp_header = ensure_frame_ancestors(csp_value)
    web_root = index_path.parent
    mimetypes.add_type("application/wasm", ".wasm")

    class csp_dev_handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self.csp_header = csp_header
            super().__init__(*args, directory=str(web_root), **kwargs)

        def end_headers(self):
            self.send_header("Content-Security-Policy", self.csp_header)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    server = http.server.ThreadingHTTPServer((host, port), csp_dev_handler)
    actual_port = server.server_address[1]
    print(f"READY http://{host}:{actual_port}", flush=True)
    print(f"serving {web_root} on http://{host}:{actual_port}")
    print("press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0


def wasm_paths(repo_root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    wasm_path = repo_root / "clients" / "web" / "vendor" / "mls_harness.wasm"
    wasm_exec_path = repo_root / "clients" / "web" / "vendor" / "wasm_exec.js"
    return wasm_path, wasm_exec_path


def report_build_failure(
    message: str,
    exc: BaseException,
    *,
    verbose: bool,
    stdout: str | None = None,
    stderr: str | None = None,
) -> None:
    print(f"error: {message}", file=sys.stderr)
    if verbose:
        print(f"details: {exc}", file=sys.stderr)
        if stdout:
            print("build stdout:", file=sys.stderr)
            print(stdout, file=sys.stderr)
        if stderr:
            print("build stderr:", file=sys.stderr)
            print(stderr, file=sys.stderr)
        traceback.print_exc()


def ensure_wasm(
    repo_root: pathlib.Path,
    *,
    build_wasm: bool,
    build_wasm_if_missing: bool,
    require_wasm: bool,
    verbose: bool,
) -> int:
    wasm_path, wasm_exec_path = wasm_paths(repo_root)
    wasm_missing = not wasm_path.exists()
    wasm_exec_missing = not wasm_exec_path.exists()
    if require_wasm and (wasm_missing or wasm_exec_missing):
        missing = []
        if wasm_missing:
            missing.append(str(wasm_path))
        if wasm_exec_missing:
            missing.append(str(wasm_exec_path))
        print(
            "error: required WASM artifacts missing: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    should_build = build_wasm or (
        build_wasm_if_missing and (wasm_missing or wasm_exec_missing)
    )
    if not should_build:
        return 0

    build_script = repo_root / "tools" / "mls_harness" / "build_wasm.sh"
    if not build_script.exists():
        print(f"error: build script missing: {build_script}", file=sys.stderr)
        return 1
    try:
        subprocess.run(
            ["bash", str(build_script)],
            check=True,
            capture_output=verbose,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stdout = None
        stderr = None
        if isinstance(exc, subprocess.CalledProcessError):
            stdout = exc.stdout
            stderr = exc.stderr
        report_build_failure(
            "failed to build MLS WASM harness; ensure Go is installed and "
            "tools/mls_harness/build_wasm.sh is present",
            exc,
            verbose=verbose,
            stdout=stdout,
            stderr=stderr,
        )
        return 1

    wasm_missing = not wasm_path.exists()
    wasm_exec_missing = not wasm_exec_path.exists()
    if wasm_missing or wasm_exec_missing:
        missing = []
        if wasm_missing:
            missing.append(str(wasm_path))
        if wasm_exec_missing:
            missing.append(str(wasm_exec_path))
        print(
            "error: build completed but expected artifacts are missing: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 1
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and serve clients/web with CSP response headers."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--check", action="store_true", help="validate CSP and exit")
    mode_group.add_argument("--serve", action="store_true", help="serve clients/web")
    parser.add_argument(
        "--build-wasm",
        action="store_true",
        help="build MLS WASM harness before serving or checking",
    )
    parser.add_argument(
        "--build-wasm-if-missing",
        action="store_true",
        help="build MLS WASM harness only when artifacts are missing",
    )
    parser.add_argument(
        "--require-wasm",
        action="store_true",
        help="exit non-zero if MLS WASM artifacts are missing",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (serve mode)")
    parser.add_argument("--port", default=8081, type=int, help="bind port (serve mode)")
    parser.add_argument("--verbose", action="store_true", help="show error details")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    index_path = repo_root / "clients" / "web" / "index.html"
    wasm_status = ensure_wasm(
        repo_root,
        build_wasm=args.build_wasm,
        build_wasm_if_missing=args.build_wasm_if_missing,
        require_wasm=args.require_wasm,
        verbose=args.verbose,
    )
    if wasm_status != 0:
        return wasm_status
    if args.serve:
        return run_server(index_path, args.host, args.port)
    return run_check(index_path)


if __name__ == "__main__":
    raise SystemExit(main())
