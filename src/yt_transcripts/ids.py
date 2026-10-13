"""Parse YouTube URLs / ids."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_VID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id(value: str) -> str | None:
    """Return the 11-char video id from an id or any common YouTube URL form, else None."""
    value = value.strip()
    if _VID.match(value):
        return value
    try:
        u = urlparse(value if "://" in value else "https://" + value)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if host.endswith("youtu.be"):
        cand = u.path.lstrip("/").split("/")[0]
        return cand if _VID.match(cand) else None
    if "youtube" in host:
        q = parse_qs(u.query)
        if "v" in q and _VID.match(q["v"][0]):
            return q["v"][0]
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v", "e"} and _VID.match(parts[1]):
            return parts[1]
    return None


def playlist_id(value: str) -> str | None:
    value = value.strip()
    if re.match(r"^(PL|UU|LL|FL|OL|RD)[A-Za-z0-9_-]{10,}$", value):
        return value
    try:
        q = parse_qs(urlparse(value if "://" in value else "https://" + value).query)
    except ValueError:
        return None
    return q.get("list", [None])[0]


def is_collection(value: str) -> bool:
    """Playlist / channel / handle URL (something that expands to many videos)."""
    v = value.strip()
    if playlist_id(v) and not video_id(v):
        return True
    if playlist_id(v) and "playlist" in v:
        return True
    return bool(re.search(r"youtube\.com/(@|channel/|c/|user/)", v))


def watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"
