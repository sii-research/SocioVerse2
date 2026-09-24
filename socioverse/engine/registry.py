"""Component registry — resolves bundle `*_ref` strings to concrete classes.

A study's model.py registers its providers/decision model/collector under string keys;
the bundles reference those keys, so the engine can wire a study with no hard imports.
"""

from __future__ import annotations

from typing import Callable, Type

_KINDS = ("environment", "population", "decision", "collector", "store", "reporter")
_REGISTRY: dict[str, dict[str, type]] = {k: {} for k in _KINDS}


def register(kind: str, key: str) -> Callable[[Type], Type]:
    """Class decorator: register(kind, key)(cls). kind in _KINDS."""
    if kind not in _REGISTRY:
        raise KeyError(f"Unknown registry kind '{kind}'. Valid: {_KINDS}")

    def _decorator(cls: Type) -> Type:
        _REGISTRY[kind][key] = cls
        return cls

    return _decorator


def resolve(kind: str, key: str) -> type:
    if kind not in _REGISTRY:
        raise KeyError(f"Unknown registry kind '{kind}'. Valid: {_KINDS}")
    if key not in _REGISTRY[kind]:
        raise KeyError(
            f"No {kind} registered under '{key}'. Available: {sorted(_REGISTRY[kind])}"
        )
    return _REGISTRY[kind][key]


def available(kind: str) -> list[str]:
    return sorted(_REGISTRY.get(kind, {}))


def clear() -> None:
    """Test helper: wipe all registrations."""
    for k in _REGISTRY:
        _REGISTRY[k].clear()
