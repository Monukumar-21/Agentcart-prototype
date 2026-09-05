"""In-memory cart storage keyed by actor."""

import threading

_lock = threading.Lock()
_carts: dict[str, dict[str, int]] = {}  # actor -> {sku: qty}


def add_item(actor: str, sku: str, qty: int) -> dict[str, int]:
    with _lock:
        if actor not in _carts:
            _carts[actor] = {}
        _carts[actor][sku] = _carts[actor].get(sku, 0) + qty
        return _carts[actor].copy()


def get_cart(actor: str) -> dict[str, int]:
    with _lock:
        return _carts.get(actor, {}).copy()


def clear_cart(actor: str) -> None:
    with _lock:
        if actor in _carts:
            del _carts[actor]


def remove_item(actor: str, sku: str, qty: int) -> dict[str, int]:
    with _lock:
        if actor in _carts and sku in _carts[actor]:
            _carts[actor][sku] -= qty
            if _carts[actor][sku] <= 0:
                del _carts[actor][sku]
            if not _carts[actor]:
                del _carts[actor]
        return _carts.get(actor, {}).copy()
