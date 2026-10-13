# Ready-to-paste prompts (token-optimised)

## Whole playlist → lecture notes (works across session limits)

```
Use the yt_transcripts tools.
1. yt_start_job source="<PLAYLIST URL>". Note the job_id.
2. Loop: yt_notes action=next job_id=<id>.
   - If "next" is empty and still_downloading > 0: yt_job status, tell me the ETA, and stop.
   - Else for that video: yt_outline, then read it with yt_transcript in ranges (start/end per section),
     write structured lecture notes into <DOC/FILE>, then yt_notes action=done video_ids=[...] ref="<where>".
3. Continue until done. Never re-read a video already marked done.
```

Starting a new chat after a limit? Paste the same prompt with the same playlist URL. The job resumes and
`yt_notes next` returns the first video without notes.

## Fill a gap in one video

```
yt_transcript video=<URL> start="39:30" — summarise only this part and add it to <section>.
```

## Find a topic across a video without reading all of it

```
yt_transcript video=<URL> search="escalation rule|SLA" — explain what they say about it, with timestamps.
```
