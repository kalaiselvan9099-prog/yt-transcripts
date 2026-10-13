from __future__ import annotations

import pytest

from yt_transcripts.backends import register
from yt_transcripts.backends.base import Backend
from yt_transcripts.config import load_settings
from yt_transcripts.errors import NeedsUpdate, NetworkError, NoCaptions, RateLimited
from yt_transcripts.models import PlaylistInfo, Segment, Transcript, VideoRef
from yt_transcripts.service import Service
from yt_transcripts.store import iso


class FakeBackend(Backend):
    """Programmable stand-in for YouTube. behaviour[vid] = list of outcomes consumed per call:
    'ok' | 'rate' | 'nocap' | 'broken' | 'kill'."""
    name = "fake"
    behaviour: dict[str, list[str]] = {}
    calls: list[str] = []
    playlist: list[str] = []

    def check(self):
        return True, "fake"

    def fetch(self, video_id: str) -> Transcript:
        FakeBackend.calls.append(video_id)
        plan = FakeBackend.behaviour.get(video_id, [])
        outcome = plan.pop(0) if plan else "ok"
        if outcome == "rate":
            raise RateLimited("HTTP Error 429: Too Many Requests")
        if outcome == "nocap":
            raise NoCaptions("no subs")
        if outcome == "broken":
            raise NeedsUpdate("PoTokenRequired")
        if outcome == "net":
            raise NetworkError("Unable to connect to proxy")
        if outcome == "kill":
            raise KeyboardInterrupt  # simulates the process dying mid-job
        segs = [Segment(i * 5.0, 5.0, f"{video_id} sentence {i} um about topic{i % 7}") for i in range(200)]
        return Transcript(video_id, "en", "auto", "fake", segs, title=f"Title {video_id}", channel="Chan",
                          duration=1000.0, fetched_at=iso())

    def list_collection(self, url: str) -> PlaylistInfo:
        return PlaylistInfo(url, "Fake Playlist",
                            [VideoRef(v, f"T{v}", 100, i + 1) for i, v in enumerate(FakeBackend.playlist)])


register(FakeBackend)


def vid(n: int) -> str:
    return f"vid{n:08d}"  # 11 chars


@pytest.fixture
def svc(tmp_path):
    FakeBackend.behaviour, FakeBackend.calls = {}, []
    FakeBackend.playlist = [vid(i) for i in range(1, 7)]
    s = load_settings(home=tmp_path, overrides=dict(
        backends=["fake"], min_delay_seconds=0.0, max_delay_seconds=0.0, batch_size=0,
        backoff_schedule_seconds=[0.05, 0.1, 0.2], heartbeat_seconds=1, worker_max_wait_seconds=5,
        export_markdown=True, hourly_cap=1000,
    ))
    return Service(s, isolate=False)
