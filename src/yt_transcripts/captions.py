"""Caption format parsers -> list[Segment]. Formats: json3, vtt, srv1/2/3 (xml), srt."""
from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET

from .models import Segment

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub("", text))).strip()


def parse_json3(raw: str | bytes) -> list[Segment]:
    data = json.loads(raw)
    out: list[Segment] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = _clean("".join(s.get("utf8", "") for s in segs))
        if not text:
            continue
        out.append(Segment(ev.get("tStartMs", 0) / 1000, ev.get("dDurationMs", 0) / 1000, text))
    return out


def _ts(t: str) -> float:
    t = t.strip().replace(",", ".")
    parts = t.split(":")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


_CUE = re.compile(r"(?P<a>\d{1,2}:?\d{2}:\d{2}[.,]\d{3}|\d{2}:\d{2}[.,]\d{3})\s+-->\s+(?P<b>[\d:.,]+)")


def parse_vtt(raw: str | bytes) -> list[Segment]:
    """WebVTT/SRT. Auto-caption VTT repeats rolling lines; we de-duplicate them."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    out: list[Segment] = []
    blocks = re.split(r"\r?\n\r?\n", raw)
    prev_lines: list[str] = []
    for b in blocks:
        lines = b.strip().splitlines()
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        m = _CUE.search(lines[idx])
        if not m:
            continue
        start, end = _ts(m["a"]), _ts(m["b"])
        body = [_clean(ln) for ln in lines[idx + 1:]]
        body = [ln for ln in body if ln]
        new = [ln for ln in body if ln not in prev_lines]
        prev_lines = body
        if new:
            out.append(Segment(start, max(0.0, end - start), " ".join(new)))
    return out


def parse_xml(raw: str | bytes) -> list[Segment]:
    root = ET.fromstring(raw)
    out: list[Segment] = []
    for el in root.iter():
        if el.tag == "text":  # srv1
            t = _clean("".join(el.itertext()))
            if t:
                out.append(Segment(float(el.get("start", 0)), float(el.get("dur", 0)), t))
        elif el.tag == "p":  # srv3 (ms)
            t = _clean("".join(el.itertext()))
            if t:
                out.append(Segment(int(el.get("t", 0)) / 1000, int(el.get("d", 0)) / 1000, t))
    return out


def parse_any(raw: str | bytes, hint: str = "") -> list[Segment]:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    s = text.lstrip()
    hint = hint.lower()
    if hint == "json3" or s.startswith("{"):
        return parse_json3(text)
    if hint in {"vtt", "srt"} or s.startswith("WEBVTT") or "-->" in s[:500]:
        return parse_vtt(text)
    if s.startswith("<"):
        return parse_xml(text)
    raise ValueError("Unrecognised caption format (expected json3, vtt, srt or xml)")
