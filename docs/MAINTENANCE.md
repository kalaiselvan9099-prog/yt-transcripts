# Maintenance runbook — when YouTube changes something

YouTube changes its player every few weeks. The design keeps that blast radius small:
only the **YouTube layer** (yt-dlp, yt-dlp-ejs, bgutil PO-token provider, youtube-transcript-api) ever needs
updating. Jobs, cache, progress, rate limiting, the MCP server and the CLI do not.

## Symptoms → action

| You see | Meaning | Do |
|---|---|---|
| Job paused: `needs_update: YouTube changed something` | 3 videos in a row failed with a "changed" signature | `ytt update`, then `ytt job resume <id>` |
| `error: needs_update` with "empty caption response" | PO-token gate: captions served empty | `ytt doctor` → fix PO-token warning → `ytt update` |
| Job paused: `auto:YouTube blocked 3x…` + `resumes_at` | YouTube throttled this IP | Nothing. It resumes by itself (scheduled task / next app start). Don't reset. |
| `error: network` / `auto:offline` | PC can't reach YouTube (Wi-Fi, VPN, proxy) | Fix the connection; job resumes by itself |
| `bot_check` | "confirm you're not a bot" | Wait hours; lower `hourly_cap`; avoid VPN exits; cookies only as last resort |
| A new error wording is misclassified | YouTube changed message text | Add a regex to `%LOCALAPPDATA%\ytt\patterns.toml` (no code change) |

## Commands

```text
ytt doctor                 # versions, JS runtime, PO-token server build, warnings
ytt doctor --live VIDEO    # real end-to-end fetch (counts against the rate limit)
ytt update                 # pip upgrade YouTube layer + rebuild matching PO-token server + scoop update deno
ytt throttle-reset         # only if you are sure a block has expired
```

A weekly `ytt-update` scheduled task (Sundays 11:00) keeps the YouTube layer fresh automatically.
Set `auto_update = "auto"` in `config.toml` to also update immediately when a job detects breakage.

## Escape hatches (no code change needed)

1. **yt-dlp flags** — any workaround the yt-dlp community publishes goes in `config.toml`:
   `ytdlp_args = ["--extractor-args", "youtube:player_client=default,-web"]`
2. **Backend order** — `backends = ["transcript_api", "ytdlp"]` if one library breaks first.
3. **Error wording** — `patterns.toml` (categories: `rate_limited`, `bot_check`, `unavailable`, `no_captions`,
   `network`, `needs_update`).
4. **Manual capture** — if every backend is broken, open the video in a real browser and capture the
   caption request the player makes (json3), then `ytt import VIDEO file.json` or the `yt_import` tool.
   In a browser console on the watch page, after turning captions on:

   ```js
   const u = performance.getEntriesByType('resource').map(e => e.name).find(n => n.includes('timedtext') && n.includes('pot='));
   copy(await fetch(u).then(r => r.text()));   // paste into a .json file
   ```

## Updating the tool itself

The core is installed in editable mode from this folder. Replace the folder (or `git pull` if you keep it in a
repo) and re-run `setup.ps1`. Database schema upgrades are applied automatically (versioned migrations).
