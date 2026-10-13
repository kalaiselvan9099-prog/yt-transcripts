# Architecture

```
 AI apps (Claude / Cursor / Codex / VS Code)        Terminal
        │  MCP stdio (each app spawns server.py)        │ ytt CLI
        └──────────────┬────────────────────────────────┘
                       ▼
                 service.py  ── core use-cases (stable)
        ┌──────────────┼──────────────────┬──────────────────┐
        ▼              ▼                  ▼                  ▼
   throttle.py     store.py           procs.py           updater.py
   global rate     SQLite (WAL) +     isolated fetch     YouTube-layer
   limiter         transcript JSON    subprocess +       updates +
   (shared by all  (atomic writes)    detached workers   PO-token build
   processes)
                       ▲
                 backends/  ── the ONLY YouTube-specific code
                 ytdlp_backend.py  →  yt-dlp (+ yt-dlp-ejs, bgutil PO-token plugin)
                 transcript_api_backend.py → youtube-transcript-api
```

## Key decisions

| Decision | Why |
|---|---|
| Downloads run in a **detached worker**, never inside an AI tool call | AI sessions/limits/timeouts can't interrupt a 100-video job |
| Progress committed **per video**; transcripts written atomically | Kill at any moment → resume loses at most the in-flight video |
| Each fetch runs in a **fresh subprocess** with a hard timeout | A hung library can't freeze the server; `ytt update` applies instantly |
| **One SQLite rate limiter** for every process | Claude + Cursor + worker together still look like one polite client |
| Rate-limit/network errors **stop the backend chain** | Same IP for every backend; trying another only deepens a block |
| Error classification via **editable regex file** | YouTube rewording an error needs no code change |
| Captions: manual > original-language auto > (opt-in) translation | Avoids silently getting a machine translation |
| Output: plain text, metadata on page 1 only, no structured duplicate | Lowest tokens per useful character |
| MCP SDK pinned `<3`, code supports v1 and v2 | SDK rewrites can't silently break the server |

## Job state machine

`pending → running → done`
`running → paused (user | auto:<reason> with resume_after | needs_update)`
`running → interrupted` (worker died; detected by stale heartbeat) `→ pending` via `recover()`
`recover()` runs on every MCP server start and every 30 min (scheduled task).

## Extending

New backend: subclass `backends.base.Backend` (`check`, `fetch`, optional `list_collection`), register it in
`backends/__init__.py`, add its name to `backends` in config. Tests use a fake backend (`tests/conftest.py`).
