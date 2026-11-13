"""CPAH package.

Heavy application modules are loaded on demand so read-only CLI commands do not
initialize logging, Qt, screen capture, or input support.
"""

from __future__ import annotations

import importlib

__all__ = ["constants", "logic", "models"]


def __getattr__(name: str):
    if name in __all__:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(name)
