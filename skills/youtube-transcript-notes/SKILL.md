---
name: youtube-transcript-notes
description: "Make organised notes from YouTube videos or playlists using the yt_transcripts MCP tools or ytt CLI: resumable, token-efficient, full coverage."
license: MIT
compatibility: "Needs the yt-transcripts tool (MCP server yt_transcripts or the ytt CLI) installed locally."
---

# YouTube → Notes with the yt_transcripts tool

This skill covers the **tool workflow**: getting transcripts, reading them cheaply and completely, and
surviving session limits. The **note format** comes from the `structured-note-making` skill; load it
before writing any notes.

## 0. Check which interface is available

1. **MCP tools** `yt_transcript`, `yt_outline`, `yt_start_job`, `yt_job`, `yt_notes`, `yt_import`,
   `yt_maintenance`: preferred.
2. **CLI** `ytt` in a shell (Cursor / Codex / Claude Code agent mode), with the same commands:
   `ytt job start URL`, `ytt job status ID -v`, `ytt notes next ID -n 1`, `ytt outline VIDEO`,
   `ytt get VIDEO --start 0:00 --end 10:00`, `ytt notes done ID VIDEO_ID --ref "..."`.
3. **Neither:** tell the user the tool isn't installed or registered here. Fix: run `setup.ps1` from the
   yt-transcripts folder, then restart the app. Don't fall back to scraping YouTube another way.

If any call errors at the start, run `yt_maintenance action=doctor` and act on `warnings`.

## 1. Start or resume

- **Playlist, channel or several videos:** `yt_start_job source=<URL>`. Running it again on the same
  URL resumes the same job and picks up newly added videos, so it's safe on every new session.
  Record the `job_id` at the top of the notes document (e.g. a "Source & progress" line).
- **Single video:** no job needed. Use `yt_outline`, then `yt_transcript` directly.
- Downloading happens in the background, independent of this chat. Don't wait for the whole playlist:
  start notes as soon as `yt_notes next` returns a video.

## 2. The per-video loop (repeat until done)

```
yt_notes action=next job_id=J           -> next downloaded video without notes (title, duration, chars)
  empty "next" + still_downloading > 0  -> yt_job status: report the ETA; stop or wait. Don't poll in a tight loop.
  empty "next" + nothing downloading    -> all done: go to step 4 (synthesis)
yt_outline video=V                      -> chapters or 5-min sections with char sizes
Read the WHOLE video in ranges           -> yt_transcript video=V start=a end=b (one call per section or a group of sections)
Write notes (structured-note-making)     -> save them to the destination NOW
yt_notes action=done job_id=J video_ids=[V] ref="<doc section / file path>"
```

Rules:
- **Full coverage is mandatory for notes.** Keep a range ledger per video (e.g. `0:00–15:00 ✓, 15:00–30:00 ✓ …`)
  and confirm it reaches the video's duration before marking it done. `search` is for targeted lookups and
  gap-fills, never a substitute for reading the video.
- **Size ranges to the page cap:** about 40k chars per call by default. Use outline `chars` to group sections into
  calls of at most ~35k. If a response has `next_offset`, continue with `offset=` before moving on.
- **Save after every video**, then mark it done. Never batch several videos in memory: a session limit
  would lose them.
- **Never request the same range twice.** Re-read only to fix a specific, named gap.

## 3. Token discipline

- Outline first, about 200 tokens. It decides the ranges and the topic map for the video.
- Keep the default timestamps (30s) when writing notes, because they become source refs `[mm:ss]`.
  Use `timestamps=0` only for pure summarising where refs aren't needed.
- Don't paste transcript text into chat or into the notes. Write processed notes only.
- Use status calls sparingly (`yt_job status` without verbose). Use `verbose=true` only when diagnosing.
- For a gap in one video (e.g. "after 39:30 is missing"): `yt_transcript start="39:30"`. Don't re-read the whole video.

## 4. Synthesis across the playlist (after the last video)

1. Build the **course-level overview**: topic map across videos, coverage table
   (video | duration | ranges read ✓ | notes ref), and the official weighting if this is exam prep.
2. Merge concepts repeated across videos into one place, cross-referencing the other lectures.
3. Add the cheat sheet, traps / confusables table, glossary and recall questions (structured-note-making step 4).
4. Run the structured-note-making verification (coverage, even depth, accuracy, exclusions).
5. Optional: `yt_job action=export` writes Markdown transcripts to `%LOCALAPPDATA%\ytt\exports\<job>`,
   for apps that read files directly or for sharing.

## 5. Transcript quality fixes

Auto-generated captions (`captions: en/auto`) contain speech-recognition errors.
- Fix domain terms silently when certain (e.g. "sales force" → Salesforce, "sock well" → SOQL,
  "apex trigger" casing). If unsure, keep the term and add `⚠️ verify`.
- Speakers make mistakes or go out of date. For changeable facts (limits, retirements, release timing,
  feature names), check official docs when tools allow and add a `Correction:` line. Never silently rewrite.
- If the captions came from a translation, or `kind` is `imported`, mention it in the coverage table.

## 6. Errors: what to do (never retry in a loop)

| Response | Action |
|---|---|
| `throttled` / `retry_in_s` | Work on already-downloaded videos instead; tell the user the wait if nothing is left |
| `rate_limited` / `bot_check`, or job `pause_reason: auto:...` | The tool backs off and resumes by itself. Don't reset the throttle. Continue with downloaded videos |
| `network` / `auto:offline` | The user's connection is down; it resumes automatically |
| `needs_update` / pause `needs_update` | Ask the user to run `ytt update` (or `yt_maintenance action=update`), then `yt_job action=resume` |
| `no_captions` / `unavailable` | Record it in the coverage table as "no transcript"; move on |
| Tools missing | See section 0 |

## 7. Resuming in a new chat (after a session limit)

The user pastes the same request. Then:
1. `yt_start_job` with the same URL (returns the existing job), or `yt_job status` to find the job_id.
2. `yt_notes next` gives the exact video to continue with. The notes already written are referenced in `ref`.
3. Read the notes document's overview / progress section, not the whole doc, to recover the context
   needed (topic map, naming conventions), then continue the loop.

## Final checklist

- [ ] Every downloaded video is either marked done with a `ref`, or listed with its reason (no captions, etc.)
- [ ] A range ledger reached the full duration for each noted video
- [ ] Notes follow structured-note-making (hierarchy, concept shape, recall layer, verification)
- [ ] Course overview, coverage table, cheat sheet, traps table and glossary exist
- [ ] No raw transcript pasted; ASR errors fixed or flagged; corrections sourced