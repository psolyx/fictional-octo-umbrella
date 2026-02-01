# gateway/src/gateway/__init__.py
from .cursors import CursorStore
from .hub import Subscription, SubscriptionHub
from .log import ConversationEvent, ConversationLog

def greet(*a, **kw):
    from .server import greet as _greet
    return _greet(*a, **kw)

def main(*a, **kw):
    from .server import main as _main
    return _main(*a, **kw)

def simulate(*a, **kw):
    from .server import simulate as _simulate
    return _simulate(*a, **kw)

__all__ = [
    "CursorStore",
    "Subscription",
    "SubscriptionHub",
    "ConversationEvent",
    "ConversationLog",
    "greet",
    "main",
    "simulate",
]


