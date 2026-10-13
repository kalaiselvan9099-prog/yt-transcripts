"""Error taxonomy + message classifier driven by editable patterns.toml."""
from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from importlib import resources
from pathlib import Path


class YttError(Exception):
    """Base error. `kind` is stored in the DB and drives job behaviour."""
    kind = "error"
    retryable = True


class RateLimited(YttError):
    kind = "rate_limited"


class BotCheck(RateLimited):
    kind = "bot_check"


class VideoUnavailable(YttError):
    kind = "unavailable"
    retryable = False


class NoCaptions(YttError):
    kind = "no_captions"
    retryable = False


class NetworkError(YttError):
    """This PC can't reach YouTube right now (offline, proxy, DNS). Retry later; not the video's fault."""
    kind = "network"


class NeedsUpdate(YttError):
    """YouTube changed something the current YouTube layer can't handle."""
    kind = "needs_update"


class BackendUnavailable(YttError):
    """Backend not installed / misconfigured on this machine."""
    kind = "backend_unavailable"


class Throttled(YttError):
    """Our own limiter says wait; carries seconds until allowed."""
    kind = "throttled"

    def __init__(self, wait_seconds: float, reason: str):
        super().__init__(f"{reason}; retry in {int(wait_seconds)}s")
        self.wait_seconds = wait_seconds
        self.reason = reason


# Order matters: most specific / most dangerous first.
_ORDER: list[tuple[str, type[YttError]]] = [
    ("bot_check", BotCheck),
    ("rate_limited", RateLimited),
    ("unavailable", VideoUnavailable),
    ("no_captions", NoCaptions),
    ("network", NetworkError),
    ("needs_update", NeedsUpdate),
]


@lru_cache(maxsize=8)
def _compiled(user_patterns_path: str | None) -> dict[str, list[re.Pattern[str]]]:
    data = tomllib.loads(resources.files("yt_transcripts").joinpath("patterns.toml").read_text("utf-8"))
    if user_patterns_path and Path(user_patterns_path).exists():
        user = tomllib.loads(Path(user_patterns_path).read_text("utf-8"))
        for k, v in user.items():
            data.setdefault(k, [])
            data[k] = list(data[k]) + list(v)
    return {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in data.items()}


_USER_PATTERNS: str | None = None


def set_user_patterns(path: str | None) -> None:
    """Point the classifier at <YTT_HOME>/patterns.toml (user additions, no code change needed)."""
    global _USER_PATTERNS
    _USER_PATTERNS = path


def classify(message: str, user_patterns_path: str | None = None) -> type[YttError]:
    pats = _compiled(user_patterns_path or _USER_PATTERNS)
    for key, cls in _ORDER:
        if any(p.search(message) for p in pats.get(key, [])):
            return cls
    return YttError


def wrap(exc: BaseException, user_patterns_path: str | None = None) -> YttError:
    if isinstance(exc, YttError):
        return exc
    msg = f"{type(exc).__name__}: {exc}"
    return classify(msg, user_patterns_path)(msg)
