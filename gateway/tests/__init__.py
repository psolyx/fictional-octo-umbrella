"""Test package for gateway unit and integration tests."""

import logging
import warnings

warnings.filterwarnings(
    "ignore",
    message=r".*recommended to use web\.AppKey.*",
    category=Warning,
)
warnings.filterwarnings(
    "ignore",
    message=r".*drain.*deprecated.*",
    category=DeprecationWarning,
)

logging.getLogger("asyncio").setLevel(logging.ERROR)
