"""yt-dlp backend. yt-dlp is the most actively maintained YouTube client (fixes usually land within days
of a YouTube change); with the bgutil PO-token plugin installed it also solves the caption PO-token gate."""
from __future__ import annotations

import re
from importlib import metadata
from typing import Any

from ..captions import parse_any
from ..errors import NeedsUpdate, NoCaptions, VideoUnavailable, wrap
from ..ids import watch_url
from ..models import PlaylistInfo, Transcript, VideoRef
from ..store import iso
from .base import Backend, choose_track, pick_format


class _Logger:
    """Capture yt-dlp warnings so classification sees them (e.g. 'PO Token' hints)."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] [youtube] [pot]"):
            self.messages.append(msg)

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        self.messages.append(msg)

    def error(self, msg: str) -> None:
        self.messages.append(msg)


class YtDlpBackend(Backend):
    name = "ytdlp"

    def check(self) -> tuple[bool, str]:
        try:
            import yt_dlp  # noqa: F401
            ver = metadata.version("yt-dlp")
        except Exception as e:  # pragma: no cover
            return False, f"yt-dlp not installed: {e}"
        extras = []
        for dist in ("yt-dlp-ejs", "bgutil-ytdlp-pot-provider"):
            try:
                extras.append(f"{dist} {metadata.version(dist)}")
            except metadata.PackageNotFoundError:
                extras.append(f"{dist} MISSING")
        return True, f"yt-dlp {ver}; " + "; ".join(extras)

    def _opts(self, logger: _Logger, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        import yt_dlp

        opts: dict[str, Any] = {}
        if self.s.ytdlp_args:
            opts.update(yt_dlp.parse_options(list(self.s.ytdlp_args)).ydl_opts)
        opts.update({
            "quiet": True,
            "no_warnings": False,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "extractor_retries": 1,  # our job engine owns retries + backoff; don't hammer inside yt-dlp
            "logger": logger,
            "noprogress": True,
        })
        if self.s.proxy:
            opts["proxy"] = self.s.proxy
        if self.s.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.s.cookies_from_browser,)
        if extra:
            opts.update(extra)
        return opts

    def fetch(self, video_id: str) -> Transcript:
        import yt_dlp

        log = _Logger()
        try:
            with yt_dlp.YoutubeDL(self._opts(log)) as ydl:
                info = ydl.extract_info(watch_url(video_id), download=False)
                if info is None:
                    raise VideoUnavailable("yt-dlp returned no info")
                lang, kind, formats = choose_track(
                    info.get("subtitles") or {}, info.get("automatic_captions") or {},
                    self.s.languages, self.s.prefer_manual, self.s.allow_translated,
                )
                fmt = pick_format(formats)
                raw = ydl.urlopen(fmt["url"]).read()
        except (NoCaptions, VideoUnavailable):
            raise
        except Exception as e:
            err = wrap(Exception(f"{e} | {' | '.join(log.messages[-5:])}"))
            raise err from e
        if not raw or not raw.strip():
            raise NeedsUpdate(
                "empty caption response - YouTube served no caption data (usually the PO-token gate). "
                "Install/update the bgutil PO-token provider and run `ytt update`. "
                + " | ".join(log.messages[-3:])
            )
        segments = parse_any(raw, fmt.get("ext", ""))
        if not segments:
            raise NeedsUpdate(f"empty caption payload after parsing ({fmt.get('ext')}); run `ytt update`")
        return Transcript(
            video_id=video_id, language=lang, kind=kind, backend=self.name, segments=segments,
            title=info.get("title") or "", channel=info.get("channel") or info.get("uploader") or "",
            duration=float(info.get("duration") or 0), fetched_at=iso(),
            chapters=[{"start": float(c.get("start_time") or 0), "end": float(c.get("end_time") or 0),
                       "title": c.get("title") or ""} for c in (info.get("chapters") or [])],
        )

    def list_collection(self, url: str) -> PlaylistInfo:
        import yt_dlp

        url = _normalise_channel(url)
        log = _Logger()
        try:
            with yt_dlp.YoutubeDL(self._opts(log, {"extract_flat": "in_playlist", "noplaylist": False})) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise wrap(Exception(f"{e} | {' | '.join(log.messages[-5:])}")) from e
        refs: list[VideoRef] = []
        seen: set[str] = set()

        def walk(node: dict[str, Any]) -> None:
            for ent in node.get("entries") or []:
                if not ent:
                    continue
                if ent.get("entries"):
                    walk(ent)
                    continue
                vid = ent.get("id")
                if not vid or len(vid) != 11 or vid in seen:
                    continue  # tabs / nested playlists / duplicates
                seen.add(vid)
                refs.append(VideoRef(vid, ent.get("title") or "", float(ent.get("duration") or 0), len(refs) + 1))

        walk(info or {})
        return PlaylistInfo(url, (info or {}).get("title") or url, refs)


def _normalise_channel(url: str) -> str:
    """Channel root URLs expand to tabs; point at the Videos tab so we get actual uploads."""
    m = re.match(r"^(https?://(?:www\.)?youtube\.com/(?:@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+))/?$", url.strip())
    return m.group(1) + "/videos" if m else url
