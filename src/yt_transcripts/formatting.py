"""Compact, LLM-friendly rendering + size-safe pagination."""
from __future__ import annotations

import re

from .models import Transcript

_FILLERS = re.compile(
    # Only meaning-free sounds. Phrases like "you know" / "I mean" are kept: removing them can change meaning.
    r"\b(?:um+|uh+|erm+|hmm+|mhm|uh-huh)\b[,.]?\s*",
    re.IGNORECASE,
)
_DUP_WORD = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
_WS = re.compile(r"\s+")


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def parse_ts(value: str | float | int | None) -> float | None:
    """'39:30', '1:02:03', '90', 90 -> seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    secs = 0.0
    for p in str(value).strip().split(":"):
        secs = secs * 60 + float(p)
    return secs


def clean_text(text: str, remove_fillers: bool) -> str:
    if remove_fillers:
        text = _FILLERS.sub("", text)
        text = _DUP_WORD.sub(r"\1", text)
    return _WS.sub(" ", text).strip()


def render(
    t: Transcript,
    start: float | None = None,
    end: float | None = None,
    every: int = 30,
    remove_fillers: bool = True,
) -> str:
    """One line per `every`-second block: '[mm:ss] text'. Text appears exactly once (no duplication)."""
    lines: list[str] = []
    block_start: float | None = None
    buf: list[str] = []
    for seg in t.segments:
        if start is not None and seg.start + seg.duration <= start:
            continue
        if end is not None and seg.start > end:
            break
        if block_start is None or seg.start - block_start >= every:
            if buf:
                lines.append(f"[{fmt_ts(block_start)}] {clean_text(' '.join(buf), remove_fillers)}")
            block_start, buf = seg.start, []
        buf.append(seg.text)
    if buf and block_start is not None:
        lines.append(f"[{fmt_ts(block_start)}] {clean_text(' '.join(buf), remove_fillers)}")
    return "\n".join(ln for ln in lines if not ln.endswith("] "))


def paginate(text: str, offset: int, max_chars: int) -> tuple[str, int | None]:
    """Return (chunk, next_offset or None). Cuts on line boundaries so timestamps stay intact."""
    if offset >= len(text):
        return "", None
    end = offset + max_chars
    if end >= len(text):
        return text[offset:], None
    cut = text.rfind("\n", offset, end)
    if cut <= offset:  # single giant line: hard cut on a space
        cut = text.rfind(" ", offset, end)
        if cut <= offset:
            cut = end
    return text[offset:cut], cut + 1 if text[cut:cut + 1] in ("\n", " ") else cut


def search(text: str, query: str, context: int = 1, max_hits: int = 20) -> tuple[str, int]:
    """Return only rendered lines matching the query (+/- `context` lines), merged. Query: words are ANDed
    within a line; '|' separates alternatives. Returns (excerpt, hit_count)."""
    lines = text.splitlines()
    alts = [[w.lower() for w in a.split()] for a in query.split("|") if a.strip()]
    hits = [i for i, ln in enumerate(lines) if any(all(w in ln.lower() for w in words) for words in alts)]
    if not hits:
        return "", 0
    keep: list[tuple[int, int]] = []
    for i in hits[:max_hits]:
        lo, hi = max(0, i - context), min(len(lines) - 1, i + context)
        if keep and lo <= keep[-1][1] + 1:
            keep[-1] = (keep[-1][0], hi)
        else:
            keep.append((lo, hi))
    return "\n…\n".join("\n".join(lines[a:b + 1]) for a, b in keep), len(hits)


def outline(t: Transcript, section_seconds: int = 300, preview_words: int = 12) -> list[dict]:
    """Cheap map of the video (~10-20 tokens/section) so an AI can fetch only the parts it needs."""
    if t.chapters:
        spans = [(c["start"], c["end"] or t.duration, c["title"]) for c in t.chapters]
    else:
        total = t.duration or (t.segments[-1].start + t.segments[-1].duration if t.segments else 0)
        spans = [(s, min(s + section_seconds, total), "") for s in range(0, int(total) + 1, section_seconds)]
    out = []
    for start, end, title in spans:
        segs = [s for s in t.segments if start <= s.start < end]
        if not segs:
            continue
        words = " ".join(s.text for s in segs).split()
        out.append({
            "start": fmt_ts(start), "end": fmt_ts(end),
            "title": title or " ".join(words[:preview_words]) + "…",
            "chars": sum(len(s.text) + 1 for s in segs),
        })
    return out


def header(t: Transcript) -> str:
    return (
        f"# {t.title or t.video_id}\n"
        f"video_id: {t.video_id} | channel: {t.channel or '?'} | duration: {fmt_ts(t.duration)} | "
        f"captions: {t.language} ({t.kind}) via {t.backend}\n"
    )
