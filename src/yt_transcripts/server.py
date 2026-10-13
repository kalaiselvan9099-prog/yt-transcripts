"""MCP server (stdio by default). Token-lean by design:
- 7 tools with one-line descriptions (tool schemas are re-sent on every model turn)
- transcript text returned as plain text, not JSON-escaped; metadata only on page 1
- outline/search let the model fetch only what it needs
"""
from __future__ import annotations

import json
import threading
from typing import Annotated, Literal

from pydantic import Field

try:  # MCP Python SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK v1
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]
from mcp.types import ToolAnnotations

from .service import Service

INSTRUCTIONS = (
    "YouTube transcripts (cached locally, rate-limited). One video: yt_outline first if long, then yt_transcript "
    "with start/end or search. Many videos/playlist: yt_start_job (background, resumable), then loop "
    "yt_notes next -> yt_transcript -> write notes -> yt_notes done. Never retry rate-limit errors in a loop."
)

mcp = _Server("yt_transcripts_mcp", instructions=INSTRUCTIONS)
_svc: Service | None = None
_lock = threading.Lock()


def svc() -> Service:
    global _svc
    with _lock:
        if _svc is None:
            _svc = Service()
    return _svc


def _j(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _text_result(r: dict) -> str:
    """Meta as one compact JSON line, then raw text (cheaper than escaping text inside JSON)."""
    if "text" not in r or r.get("error"):
        return _j(r)
    text = r.pop("text")
    return _j(r) + "\n" + text


def _tool(**kw):
    """structured_output=False: otherwise the SDK returns every result twice (text + structuredContent),
    doubling token cost in clients that forward both."""
    try:
        return mcp.tool(structured_output=False, **kw)
    except TypeError:  # very old SDK without the flag
        return mcp.tool(**kw)


RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
RW = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)


@_tool(name="yt_transcript", annotations=RO,
          description="Transcript of one video. Paged by next_offset. Use start/end ('39:30') or search to save tokens.")
def yt_transcript(
    video: Annotated[str, Field(description="video URL or id")],
    start: Annotated[str, Field(description="e.g. '39:30'")] = "",
    end: Annotated[str, Field(description="e.g. '52:00'")] = "",
    search: Annotated[str, Field(description="words ANDed, '|' = OR; returns matching passages only")] = "",
    offset: int = 0,
    timestamps: Annotated[int, Field(description="seconds between timestamps; 0 = none; -1 = default")] = -1,
    max_chars: Annotated[int, Field(description="page size; 0 = default")] = 0,
) -> str:
    return _text_result(svc().get_transcript(video, start or None, end or None, offset, max_chars or None, search,
                                             None if timestamps < 0 else timestamps))


@_tool(name="yt_outline", annotations=RO,
          description="Chapters/5-min sections with char sizes (~200 tokens). Call before reading long videos.")
def yt_outline(video: Annotated[str, Field(description="video URL or id")]) -> str:
    r = svc().get_outline(video)
    if "sections" in r:  # compact table instead of verbose JSON objects
        rows = [f"{s['start']}-{s['end']} {s['chars']}c {s['title']}" for s in r.pop("sections")]
        return _j(r) + "\n" + "\n".join(rows)
    return _j(r)


@_tool(name="yt_start_job", annotations=RW,
          description="Fetch a playlist/channel/list of videos in the background (resumable, rate-limited). "
                      "Re-running on the same source resumes it.")
def yt_start_job(
    source: Annotated[str, Field(description="playlist/channel URL, or comma-separated video ids/URLs")],
    title: str = "",
) -> str:
    r = svc().create_job(source, title)
    if "job_id" in r:
        r.update(svc().start_job(r["job_id"]))
    return _j(r)


@_tool(name="yt_job", annotations=RW,
          description="Job control: status (omit job_id = list jobs), pause, resume, cancel, export (markdown files).")
def yt_job(
    action: Literal["status", "pause", "resume", "cancel", "export"] = "status",
    job_id: str = "",
    verbose: bool = False,
) -> str:
    s = svc()
    if action == "status" or not job_id:
        return _j(s.job_status(job_id or None, verbose))
    return _j({"pause": s.pause_job, "resume": s.start_job, "cancel": s.cancel_job,
               "export": s.export_job}[action](job_id))


@_tool(name="yt_notes", annotations=RW,
          description="Note-taking resume point: 'next' = fetched videos not yet noted; 'done' = mark video_ids noted.")
def yt_notes(
    job_id: str,
    action: Literal["next", "done"] = "next",
    video_ids: list[str] = [],  # noqa: B006 (never mutated)
    n: int = 1,
    ref: Annotated[str, Field(description="optional pointer to where notes were saved")] = "",
) -> str:
    s = svc()
    if action == "done":
        return _j(s.mark_notes(job_id, video_ids or [], ref))
    return _j(s.next_for_notes(job_id, n))


@_tool(name="yt_import", annotations=RW,
          description="Save captions captured elsewhere (json3/vtt/srt/xml text or file path) into the cache.")
def yt_import(video: str, content: str, format: str = "", title: str = "") -> str:
    return _j(svc().import_captions(video, content, format, title))


@_tool(name="yt_maintenance", annotations=RW,
          description="doctor (health check; live_video = real test), update (YouTube layer), config, throttle_reset.")
def yt_maintenance(
    action: Literal["doctor", "update", "config", "throttle_reset"] = "doctor",
    live_video: str = "",
) -> str:
    s = svc()
    if action == "update":
        return _j(s.update())
    if action == "config":
        return _j(s.s.public_dict())
    if action == "throttle_reset":
        s.throttle.reset()
        return _j(s.throttle.status())
    return _j(s.doctor(live_video or None))


def _recover_in_background() -> None:
    def work() -> None:
        try:
            svc().recover()
        except Exception as e:  # never let recovery break the server
            try:
                svc().store.log("error", f"recover failed: {e}")
            except Exception:
                pass
    threading.Thread(target=work, daemon=True).start()


def run(http_port: int | None = None) -> None:
    _recover_in_background()
    if http_port:
        try:
            mcp.run(transport="streamable-http", host="127.0.0.1", port=http_port)
        except TypeError:  # SDK v1 configures host/port via settings
            mcp.settings.host, mcp.settings.port = "127.0.0.1", http_port  # type: ignore[attr-defined]
            mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
