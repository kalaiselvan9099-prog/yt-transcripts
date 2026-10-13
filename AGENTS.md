# Instructions for AI agents (Codex, Cursor, Copilot, Claude Code)

- This repo is **yt-transcripts**: a resumable, rate-limited YouTube transcript downloader with an MCP server
  (`python -m yt_transcripts serve`) and a CLI (`ytt`). Architecture: `docs/ARCHITECTURE.md`.
- Making notes from YouTube: follow `skills/youtube-transcript-notes/SKILL.md`, which uses
  `skills/structured-note-making/SKILL.md` for the note format.
- Never call YouTube in a loop, and never bypass the throttle. Use `ytt job start` for more than a few videos.
- Changing code: run `python -m pytest -q` (all must pass). YouTube-specific code lives only in
  `src/yt_transcripts/backends/`. Error wording belongs in `patterns.toml`, not code.
