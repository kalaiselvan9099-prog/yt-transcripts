from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1  # bump when the on-disk transcript JSON changes shape


@dataclass
class Segment:
    start: float  # seconds
    duration: float
    text: str


@dataclass
class Transcript:
    video_id: str
    language: str
    kind: str  # "manual" | "auto" | "imported"
    backend: str
    segments: list[Segment]
    title: str = ""
    channel: str = ""
    duration: float = 0.0
    fetched_at: str = ""
    chapters: list[dict[str, Any]] = field(default_factory=list)  # [{start, end, title}]
    schema: int = SCHEMA_VERSION

    @property
    def char_count(self) -> int:
        return sum(len(s.text) + 1 for s in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transcript":
        d = dict(d)
        d["segments"] = [Segment(**s) for s in d.get("segments", [])]
        d.setdefault("schema", 1)
        return cls(**d)


@dataclass
class VideoRef:
    video_id: str
    title: str = ""
    duration: float = 0.0
    position: int = 0


@dataclass
class PlaylistInfo:
    source_url: str
    title: str
    entries: list[VideoRef] = field(default_factory=list)
