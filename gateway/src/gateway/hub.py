from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from .log import ConversationEvent


Callback = Callable[[ConversationEvent], None]


@dataclass
class Subscription:
    device_id: str
    conv_id: str
    callback: Callback

    def deliver(self, event: ConversationEvent) -> None:
        self.callback(event)


class SubscriptionHub:
    """Registers subscriptions and broadcasts events to all listeners."""

    def __init__(self) -> None:
        self._subscriptions: Dict[str, List[Subscription]] = {}

    def subscribe(self, device_id: str, conv_id: str, callback: Callback) -> Subscription:
        subscription = Subscription(device_id=device_id, conv_id=conv_id, callback=callback)
        self._subscriptions.setdefault(conv_id, []).append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        subs = self._subscriptions.get(subscription.conv_id)
        if not subs:
            return
        try:
            subs.remove(subscription)
        except ValueError:
            return
        if not subs:
            self._subscriptions.pop(subscription.conv_id, None)

    def broadcast(self, event: ConversationEvent) -> None:
        for subscription in list(self._subscriptions.get(event.conv_id, [])):
            subscription.deliver(event)
