"""Backend contract. Everything YouTube-specific lives behind this interface, so when YouTube
changes, only a backend (or its upstream library) changes - never the job engine, store or server."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from ..config import Settings
from ..errors import NoCaptions
from ..models import PlaylistInfo, Transcript


class Backend(ABC):
    name: str = "base"

    def __init__(self, settings: Settings):
        self.s = settings

    @abstractmethod
    def check(self) -> tuple[bool, str]:
        """Is this backend installed/usable here? (ok, detail). Must not hit the network."""

    @abstractmethod
    def fetch(self, video_id: str) -> Transcript:
        """Fetch one transcript or raise a YttError subclass."""

    def list_collection(self, url: str) -> PlaylistInfo:
        raise NotImplementedError(f"{self.name} cannot expand playlists/channels")


def _base(lang: str) -> str:
    return lang.split("-")[0].lower()


def choose_track(manual: dict[str, list], auto: dict[str, list], languages: list[str],
                 prefer_manual: bool, allow_translated: bool) -> tuple[str, str, list]:
    """Pick (language, kind, formats).

    yt-dlp exposes the original speech-recognition track as '<lang>-orig'; bare '<lang>' auto keys can be
    machine translations. Rule: preferred language (manual > original ASR) -> original ASR in any language
    -> translation only if allowed.
    """
    manual = {k: v for k, v in (manual or {}).items() if k != "live_chat" and v}
    auto = {k: v for k, v in (auto or {}).items() if v}
    orig_keys = [k for k in auto if k.endswith("-orig")]
    orig_lang = _base(orig_keys[0]) if orig_keys else None

    def manual_for(lang: str):
        for k in manual:
            if k.lower() == lang.lower() or _base(k) == _base(lang):
                return k
        return None

    def auto_orig_for(lang: str):
        for k in orig_keys:
            if _base(k) == _base(lang):
                return k
        if not orig_keys:  # older layout: no -orig marker -> bare key is the native track
            for k in auto:
                if k.lower() == lang.lower() or _base(k) == _base(lang):
                    return k
        return None

    for lang in languages:
        m, a = manual_for(lang), auto_orig_for(lang)
        order = [(m, "manual", manual), (a, "auto", auto)]
        if not prefer_manual:
            order.reverse()
        for key, kind, src in order:
            if key:
                return re.sub(r"-orig$", "", key), kind, src[key]
    if orig_keys:  # nothing in preferred languages: native track beats a translation
        return orig_lang or orig_keys[0], "auto", auto[orig_keys[0]]
    if manual:
        k = next(iter(manual))
        return k, "manual", manual[k]
    if allow_translated:
        for lang in languages:
            for k in auto:
                if _base(k) == _base(lang):
                    return k, "auto-translated", auto[k]
    raise NoCaptions(f"no usable captions (manual: {sorted(manual)[:8]}, auto originals: {orig_keys})")


FORMAT_PREFERENCE = ["json3", "srv3", "srv1", "vtt", "srt", "ttml"]


def pick_format(formats: list[dict]) -> dict:
    by_ext = {f.get("ext"): f for f in formats if f.get("url")}
    for ext in FORMAT_PREFERENCE:
        if ext in by_ext:
            return by_ext[ext]
    if not by_ext:
        raise NoCaptions("caption track has no downloadable formats")
    return next(iter(by_ext.values()))
