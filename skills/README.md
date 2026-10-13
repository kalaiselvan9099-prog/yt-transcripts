# Agent Skills

Portable skills in the open Agent Skills format (one folder per skill, each with a `SKILL.md`).
They work in Claude (desktop, claude.ai, Claude Code), Codex, Cursor and GitHub Copilot / VS Code.

| Skill | Use it for |
|---|---|
| `structured-note-making` | Any source → organised topic → subtopic notes built for recall (concept template, recall questions, cheat sheet, verification) |
| `youtube-transcript-notes` | YouTube videos/playlists → notes via this repo's `yt_transcripts` MCP tools or `ytt` CLI (resumable, token-efficient, full coverage). Loads `structured-note-making` for the format |

## Install

| Where | How |
|---|---|
| Windows (all agents) | `powershell -ExecutionPolicy Bypass -File .\skills\install.ps1` (also run by `setup.ps1`) |
| macOS / Linux | `sh skills/install.sh` |
| Claude desktop / claude.ai | upload each folder as a skill in Claude's skills settings (account skills sync to all your Claude apps) |
| One project only | copy the folders into that project's `.agents/skills/` (Codex, Cursor, Copilot) or `.claude/skills/` (Claude Code) |

Discovery locations: `~/.agents/skills` (Codex, Cursor, Copilot), `~/.claude/skills` (Claude Code; Cursor also reads it).

## Adding a skill

New folder `skills/<name>/SKILL.md`. Frontmatter: `name` = folder name (lowercase, digits, hyphens; at most 64 chars),
`description` = what it does and when to use it (at most 1024 chars, quoted if it contains `:`). CI validates both.
