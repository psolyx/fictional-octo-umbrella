from __future__ import annotations

import asyncio
import os
import sys

from cli_app.phase5_2_smoke_lite import PHASE5_2_SMOKE_LITE_END, run_smoke_lite_http


def main() -> int:
    base_url = os.environ.get("BASE_URL", "http://127.0.0.1:8788")
    try:
        return asyncio.run(run_smoke_lite_http(base_url, out=sys.stdout))
    except Exception:
        sys.stdout.write("step=0 FAIL smoke_lite_main reason=unhandled_exception\n")
        sys.stdout.write(PHASE5_2_SMOKE_LITE_END + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
