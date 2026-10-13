"""youtube-transcript-api backend (fallback). Light and fast; no PO-token solver of its own."""
from __future__ import annotations

from importlib import metadata

from ..errors import NoCaptions, VideoUnavailable, wrap
from ..models import Segment, Transcript
from ..store import iso
from .base import Backend


class TranscriptApiBackend(Backend):
    name = "transcript_api"

    def check(self) -> tuple[bool, str]:
        try:
            return True, f"youtube-transcript-api {metadata.version('youtube-transcript-api')}"
        except metadata.PackageNotFoundError:
            return False, "youtube-transcript-api not installed"

    def fetch(self, video_id: str) -> Transcript:
        import youtube_transcript_api as yta
        from youtube_transcript_api import YouTubeTranscriptApi

        proxy_cfg = None
        if self.s.proxy:
            from youtube_transcript_api.proxies import GenericProxyConfig
            proxy_cfg = GenericProxyConfig(http_url=self.s.proxy, https_url=self.s.proxy)
        api = YouTubeTranscriptApi(proxy_config=proxy_cfg)
        try:
            tl = api.list(video_id)
            tr = None
            finders = [tl.find_manually_created_transcript, tl.find_generated_transcript]
            if not self.s.prefer_manual:
                finders.reverse()
            for find in finders:
                try:
                    tr = find(self.s.languages)
                    break
                except yta.NoTranscriptFound:
                    continue
            if tr is None:  # fall back to the native track in any language (never a translation)
                tr = next(iter(tl), None)
                if tr is None:
                    raise NoCaptions("no transcripts listed")
            fetched = tr.fetch()
        except (yta.TranscriptsDisabled, yta.NoTranscriptFound) as e:
            raise NoCaptions(f"{type(e).__name__}") from e
        except (yta.VideoUnavailable, yta.VideoUnplayable, yta.InvalidVideoId) as e:
            raise VideoUnavailable(type(e).__name__) from e
        except (NoCaptions, VideoUnavailable):
            raise
        except Exception as e:  # IpBlocked / RequestBlocked / PoTokenRequired / parse errors -> classifier
            raise wrap(e) from e
        segs = [Segment(float(s.start), float(s.duration), s.text.replace("\n", " ")) for s in fetched]
        if not segs:
            raise NoCaptions("empty transcript")
        return Transcript(
            video_id=video_id, language=tr.language_code, kind="auto" if tr.is_generated else "manual",
            backend=self.name, segments=segs, fetched_at=iso(),
            duration=segs[-1].start + segs[-1].duration,
        )
