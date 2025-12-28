"""Minimal aiohttp compatibility layer for offline test environments."""

from .web import WSMsgType, WebSocketResponse, Response, Application, Request, web
from . import test_utils

__all__ = [
    "WSMsgType",
    "WebSocketResponse",
    "Response",
    "Application",
    "Request",
    "web",
    "test_utils",
]
