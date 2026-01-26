import os
import re
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
WASM_MAIN = ROOT_DIR / "tools" / "mls_harness" / "cmd" / "mls-wasm" / "main.go"
WEB_DIR = ROOT_DIR / "clients" / "web"
WEB_LOADER = WEB_DIR / "mls_vectors_loader.js"
WEB_VECTORS_UI = WEB_DIR / "vectors_ui.js"
WEB_TOOLS_DIR = WEB_DIR / "tools"

REQUIRED_GLOBALS = {
    "verifyVectors",
    "dmCreateParticipant",
    "dmInit",
    "dmJoin",
    "dmCommitApply",
    "dmEncrypt",
    "dmDecrypt",
    "groupInit",
    "groupAdd",
}

EXPECTED_LOADER_GLOBALS = {
    "verifyVectors",
    "dmCreateParticipant",
    "dmInit",
    "dmJoin",
    "dmCommitApply",
    "dmEncrypt",
    "dmDecrypt",
}

EXPECTED_VECTORS_UI_GLOBALS = {
    "dmCreateParticipant",
    "dmJoin",
    "dmCommitApply",
    "dmDecrypt",
    "groupInit",
    "groupAdd",
}

DISALLOWED_WEB_FILES = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_matches(pattern: str, text: str) -> set[str]:
    return set(re.findall(pattern, text))


def _assert_set_match(label: str, found: set[str], expected: set[str]) -> None:
    missing = expected - found
    extra = found - expected
    if not missing and not extra:
        return
    lines = [f"{label} mismatch:"]
    for name in sorted(missing):
        lines.append(f"- {name}")
    for name in sorted(extra):
        lines.append(f"+ {name}")
    raise AssertionError("\n".join(lines))


def _assert_subset(label: str, found: set[str], allowed: set[str]) -> None:
    unexpected = found - allowed
    if not unexpected:
        return
    lines = [f"{label} references globals not provided by wasm harness:"]
    for name in sorted(unexpected):
        lines.append(f"+ {name}")
    raise AssertionError("\n".join(lines))


class Phase5WasmCliCoexistOverGatewayTests(unittest.TestCase):
    def test_wasm_global_api_contract(self) -> None:
        text = _read_text(WASM_MAIN)
        found = _extract_matches(r'js\.Global\(\)\.Set\("([^"]+)"', text)
        _assert_set_match("wasm globals", found, REQUIRED_GLOBALS)

    def test_web_loader_contract(self) -> None:
        text = _read_text(WEB_LOADER)
        found = _extract_matches(r"globalThis\.([A-Za-z0-9_]+)", text)
        _assert_set_match("mls_vectors_loader.js globals", found, EXPECTED_LOADER_GLOBALS)
        _assert_subset("mls_vectors_loader.js", found, REQUIRED_GLOBALS)

    def test_web_vectors_ui_contract(self) -> None:
        text = _read_text(WEB_VECTORS_UI)
        found = _extract_matches(r"window\.([A-Za-z0-9_]+)", text)
        _assert_set_match("vectors_ui.js globals", found, EXPECTED_VECTORS_UI_GLOBALS)
        _assert_subset("vectors_ui.js", found, REQUIRED_GLOBALS)

    def test_no_node_artifacts_in_web_tree(self) -> None:
        disallowed_hits: list[str] = []
        node_modules_hits: list[str] = []
        js_tool_hits: list[str] = []

        for root, dirs, files in os.walk(WEB_DIR):
            for name in files:
                if name in DISALLOWED_WEB_FILES:
                    disallowed_hits.append(str(Path(root, name).relative_to(ROOT_DIR)))
            for name in list(dirs):
                if name == "node_modules":
                    node_modules_hits.append(str(Path(root, name).relative_to(ROOT_DIR)))

        if WEB_TOOLS_DIR.exists():
            for root, _dirs, files in os.walk(WEB_TOOLS_DIR):
                for name in files:
                    if name.endswith(".js"):
                        js_tool_hits.append(str(Path(root, name).relative_to(ROOT_DIR)))

        if disallowed_hits or node_modules_hits or js_tool_hits:
            lines = ["node artifacts detected under clients/web:"]
            for path in sorted(disallowed_hits):
                lines.append(f"- {path}")
            for path in sorted(node_modules_hits):
                lines.append(f"- {path}")
            for path in sorted(js_tool_hits):
                lines.append(f"- {path}")
            raise AssertionError("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
