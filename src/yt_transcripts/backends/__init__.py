"""Backend registry. Add a new backend = one module + one line here + its name in config `backends`."""
from __future__ import annotations

from ..config import Settings
from .base import Backend

_REGISTRY: dict[str, type[Backend]] = {}
_loaded = False


def register(cls: type[Backend]) -> type[Backend]:
    _REGISTRY[cls.name] = cls
    return cls


def _load_builtin() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from .transcript_api_backend import TranscriptApiBackend
    from .ytdlp_backend import YtDlpBackend

    register(YtDlpBackend)
    register(TranscriptApiBackend)


def get_backends(settings: Settings) -> list[Backend]:
    _load_builtin()
    out = []
    for name in settings.backends:
        cls = _REGISTRY.get(name)
        if cls is not None:
            out.append(cls(settings))
    return out


def all_names() -> list[str]:
    _load_builtin()
    return list(_REGISTRY)
