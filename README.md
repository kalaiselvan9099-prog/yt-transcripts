# yt-transcripts

Download YouTube transcripts **once**, at a pace YouTube tolerates, and read them cheaply from any AI app:
Claude (desktop/Code), Cursor, Codex, VS Code Copilot — or plain terminal (`ytt`).

- **Resumable:** progress is committed per video; crashes, reboots and AI session limits lose nothing.
- **Polite to YouTube:** one shared rate limiter for every app on the PC, escalating backoff, auto-pause.
- **Token-lean:** outline → targeted ranges/search, plain-text output, 7 small tools.
- **Survives YouTube changes:** the YouTube layer updates independently (`ytt update`, weekly task).
- **Free:** runs locally; no cloud, no API keys, no database server.

## Install (Windows)

```powershell
# from the unzipped folder
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

It installs Python/git/Deno/Node via scoop if missing, creates a private venv in `%LOCALAPPDATA%\ytt`,
installs the PO-token provider, registers the MCP server in Claude, Cursor, Codex and VS Code
(existing configs are backed up), and adds two scheduled tasks (auto-resume every 30 min, weekly update).
Restart your AI apps afterwards. Check with `ytt doctor --live CXGGF4ls1JU`.

Re-running `setup.ps1` is safe (repairs/upgrades). Register only some apps: `-Clients "claude,cursor"`.

## Use from an AI app

> Fetch the playlist https://youtube.com/playlist?list=... with yt_start_job, then make lecture notes video by video
> using yt_notes next → yt_outline → yt_transcript → write notes → yt_notes done.

| Tool | What it does |
|---|---|
| `yt_transcript` | One video. `start`/`end` ("39:30"), `search` ("escalation rules\|SLA"), paged via `next_offset`, `timestamps` (s, 0 = none) |
| `yt_outline` | Chapters / 5-min sections with sizes (~200 tokens) — read before long videos |
| `yt_start_job` | Playlist / channel / list of ids → background download. Re-run = resume + pick up new videos |
| `yt_job` | `status` / `pause` / `resume` / `cancel` / `export` (Markdown files) |
| `yt_notes` | `next` = next downloaded video without notes; `done` = mark noted (resume point for new chats) |
| `yt_import` | Save captions captured elsewhere (json3/vtt/srt/xml) |
| `yt_maintenance` | `doctor`, `update`, `config`, `throttle_reset` |

## Use from a terminal

```text
ytt job start "https://youtube.com/playlist?list=PL..."     # background; returns job_id
ytt job status [job_id] [-v]
ytt get CXGGF4ls1JU --start 39:30 --end 52:00
ytt get CXGGF4ls1JU --search "knowledge|omni"
ytt outline CXGGF4ls1JU
ytt job export <job_id>                                     # -> %LOCALAPPDATA%\ytt\exports\<job_id>\*.md
ytt doctor [--live VIDEO] | ytt update | ytt recover | ytt config
```

## Where things live

`%LOCALAPPDATA%\ytt\` — `transcripts\<id>.json` (canonical cache), `exports\<job>\` (Markdown + index),
`ytt.sqlite3` (jobs, progress, rate-limit state), `logs\`, optional `config.toml` and `patterns.toml`.

## Configuration

Copy keys from `src/yt_transcripts/default_config.toml` into `%LOCALAPPDATA%\ytt\config.toml`, or set env vars
`YTT_<KEY>`. Most useful:

| Key | Default | Why change it |
|---|---|---|
| `languages` | `["en"]` | e.g. `["en", "ta"]` |
| `response_max_chars` | 40000 (~10k tokens) | raise if your AI apps raise tool-output limits |
| `min_delay_seconds` / `max_delay_seconds` | 8 / 15 | slower = safer |
| `hourly_cap` | 120 | YouTube guest limit is ~300 videos/h; stay well below |
| `auto_update` | `warn` | `auto` = update the YouTube layer by itself when breakage is detected |
| `ytdlp_args` | `[]` | any yt-dlp flag, e.g. `["--extractor-args", "youtube:player_client=default,-web"]` |

Using cookies (`cookies_from_browser`) raises limits but **risks your Google account**; keep it off unless needed.

See `docs/MAINTENANCE.md` (what to do when YouTube changes) and `docs/ARCHITECTURE.md`.
