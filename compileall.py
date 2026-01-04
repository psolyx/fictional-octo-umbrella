"""Wrapper to skip VCS and virtualenv directories during bulk byte-compilation."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import sysconfig
from types import ModuleType
from typing import Sequence

_SKIP_REGEX = r"(^|/)\.git(/|$)|(^|/)\.venv(/|$)"


def _load_stdlib_compileall() -> ModuleType:
    stdlib_path = pathlib.Path(sysconfig.get_path("stdlib")) / "compileall.py"
    spec = importlib.util.spec_from_file_location("_stdlib_compileall", stdlib_path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"Unable to locate stdlib compileall at {stdlib_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[call-arg]
    return module


_stdlib_compileall = _load_stdlib_compileall()
compile_dir = _stdlib_compileall.compile_dir
compile_file = _stdlib_compileall.compile_file
compile_path = _stdlib_compileall.compile_path


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    injection = ["-x", _SKIP_REGEX]
    argv[1:1] = injection
    sys.argv = argv
    return _stdlib_compileall.main()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
