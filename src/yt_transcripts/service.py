"""Core application service. The CLI and the MCP server are thin shells over this class."""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from . import formatting as F
from . import errors, procs, updater
from .backends import get_backends
from .captions import parse_any
from .config import Settings, load_settings
from .errors import (BotCheck, NeedsUpdate, NetworkError, NoCaptions, RateLimited, Throttled,
                     VideoUnavailable, YttError)
from .ids import is_collection, playlist_id, video_id
from .models import PlaylistInfo, Transcript, VideoRef
from .store import Store, iso, now
from .throttle import Throttle

ERROR_TYPES: dict[str, type[YttError]] = {
    c.kind: c for c in (YttError, RateLimited, BotCheck, VideoUnavailable, NoCaptions, NeedsUpdate, NetworkError)
}
AUTO_PAUSE = "auto:"  # pause reasons with this prefix are resumed automatically when their time comes


class Service:
    def __init__(self, settings: Settings | None = None, isolate: bool = True):
        self.s = settings or load_settings()
        self.store = Store(self.s.db_path, self.s.transcripts_dir)
        self.throttle = Throttle(self.store, self.s)
        self.isolate = isolate  # tests run fetches in-process
        errors.set_user_patterns(str(self.s.home / "patterns.toml"))

    # ======================================================================
    # Single video
    # ======================================================================
    def fetch_live(self, vid: str) -> Transcript:
        """Backend fallback chain. No throttling here (caller owns it)."""
        last: YttError | None = None
        for be in get_backends(self.s):
            ok, detail = be.check()
            if not ok:
                last = last or YttError(f"{be.name}: {detail}")
                continue
            try:
                return be.fetch(vid)
            except (RateLimited, NetworkError):
                raise  # same IP/connection for every backend: trying another one doesn't help
            except (NoCaptions, VideoUnavailable):
                raise  # definitive answer about the video itself
            except YttError as e:
                self.store.log("warn", f"{be.name} failed: {e}", video_id=vid)
                if not isinstance(last, NeedsUpdate):
                    last = e
            except Exception as e:  # defensive: unknown library error
                self.store.log("warn", f"{be.name} crashed: {type(e).__name__}: {e}", video_id=vid)
                last = last or YttError(f"{be.name}: {type(e).__name__}: {e}")
        raise last or YttError("no backends configured")

    def fetch_video(self, vid: str, max_wait: float = 30, refresh: bool = False,
                    on_wait: Callable[[float, str], None] | None = None) -> Transcript:
        """Cache -> throttle -> fetch -> save. Raises YttError subclasses."""
        if not refresh and (t := self.store.load_transcript(vid)):
            return t
        self.throttle.acquire(max_wait=max_wait, on_wait=on_wait)
        if self.isolate:
            res = procs.run_isolated(["_fetch", vid], timeout=self.s.fetch_timeout_seconds)
            if not res.get("ok"):
                err = ERROR_TYPES.get(res.get("error_kind", "error"), YttError)(res.get("message", ""))
                self._after_failure(vid, err)
                raise err
            t = self.store.load_transcript(vid)
            if t is None:
                raise YttError("fetch reported success but transcript file is missing")
            self.throttle.record_success()
            return t
        try:
            t = self.fetch_live(vid)
        except YttError as e:
            self._after_failure(vid, e)
            raise
        self.store.save_transcript(t)
        self.throttle.record_success()
        return t

    def _after_failure(self, vid: str, e: YttError) -> None:
        if isinstance(e, RateLimited):
            n, until = self.throttle.record_block(e.kind, str(e))
            self.store.log("warn", f"YouTube block signal #{n}: {e}; backing off until {iso(until)}", video_id=vid)
        self.store.record_video_failure(vid, e.kind, str(e), permanent=not e.retryable)

    def fetch_child(self, vid: str) -> dict[str, Any]:
        """Entry point of the isolated fetch process. Prints one JSON line."""
        try:
            t = self.fetch_live(vid)
            self.store.save_transcript(t)
            return {"ok": True, "video_id": vid, "chars": t.char_count}
        except YttError as e:
            return {"ok": False, "error_kind": e.kind, "message": str(e)[:1500]}
        except Exception as e:
            return {"ok": False, "error_kind": "error", "message": f"{type(e).__name__}: {e}"[:1500]}

    def get_transcript(self, video: str, start: str | float | None = None, end: str | float | None = None,
                       offset: int = 0, max_chars: int | None = None, search: str = "",
                       timestamps: int | None = None, refresh: bool = False, max_wait: float = 20) -> dict[str, Any]:
        vid = video_id(video)
        if not vid:
            return {"error": f"not a YouTube video id/URL: {video!r}"}
        try:
            t = self.fetch_video(vid, max_wait=max_wait, refresh=refresh)
        except Throttled as e:
            return {"error": "throttled", "retry_in_s": int(e.wait_seconds), "why": e.reason,
                    "hint": "Cached videos still work. For many videos use yt_start_job (runs in background)."}
        except YttError as e:
            return {"error": e.kind, "detail": str(e)[:500], "hint": _hint(e)}
        every = self.s.timestamp_every_seconds if timestamps is None else timestamps
        text = F.render(t, F.parse_ts(start), F.parse_ts(end), every=max(every, 1) if every else 10**9,
                        remove_fillers=self.s.remove_fillers)
        if not every:
            text = re.sub(r"^\[[\d:]+\] ", "", text, flags=re.M).replace("\n", " ")
        out: dict[str, Any] = {"video_id": vid}
        if search:
            excerpt, hits = F.search(text, search)
            out.update(hits=hits, text=excerpt or "(no matches)")
            return out
        cap = max_chars or self.s.response_max_chars
        chunk, nxt = F.paginate(text, offset, cap)
        if offset == 0:  # metadata only on the first page (saves tokens on later pages)
            out.update(title=t.title, channel=t.channel, duration=F.fmt_ts(t.duration),
                       captions=f"{t.language}/{t.kind}", total_chars=len(text))
        out["text"] = chunk
        if nxt is not None:
            out["next_offset"] = nxt
        return out

    def get_outline(self, video: str, max_wait: float = 20) -> dict[str, Any]:
        vid = video_id(video)
        if not vid:
            return {"error": f"not a YouTube video id/URL: {video!r}"}
        try:
            t = self.fetch_video(vid, max_wait=max_wait)
        except Throttled as e:
            return {"error": "throttled", "retry_in_s": int(e.wait_seconds), "why": e.reason}
        except YttError as e:
            return {"error": e.kind, "detail": str(e)[:500], "hint": _hint(e)}
        return {"video_id": vid, "title": t.title, "duration": F.fmt_ts(t.duration),
                "chapters": bool(t.chapters), "sections": F.outline(t)}

    def import_captions(self, video: str, content: str, fmt: str = "", title: str = "") -> dict[str, Any]:
        """Last-resort path: captions captured elsewhere (e.g. a browser) -> same cache as fetched ones."""
        vid = video_id(video)
        if not vid:
            return {"error": f"not a YouTube video id/URL: {video!r}"}
        p = Path(content)
        raw = p.read_text("utf-8") if len(content) < 1024 and p.exists() else content
        segs = parse_any(raw, fmt)
        if not segs:
            return {"error": "no caption cues found in content"}
        t = Transcript(video_id=vid, language="?", kind="imported", backend="import", segments=segs,
                       title=title, duration=segs[-1].start + segs[-1].duration, fetched_at=iso())
        self.store.save_transcript(t)
        return {"video_id": vid, "segments": len(segs), "chars": t.char_count}

    # ======================================================================
    # Jobs (playlists / channels / lists) - run by detached workers
    # ======================================================================
    def create_job(self, source: str | list[str], title: str = "") -> dict[str, Any]:
        if isinstance(source, list) or ("," in source and not is_collection(source)):
            ids = source if isinstance(source, list) else source.split(",")
            refs = [VideoRef(v, position=i + 1) for i, v in enumerate(filter(None, (video_id(x) for x in ids)))]
            info = PlaylistInfo(",".join(r.video_id for r in refs), title or f"{len(refs)} videos", refs)
        elif is_collection(source) or playlist_id(source):
            info = self._list_collection(source)
            if title:
                info.title = title
        elif vid := video_id(source):
            info = PlaylistInfo(source, title or vid, [VideoRef(vid, position=1)])
        else:
            return {"error": f"unrecognised source: {source!r}"}
        if not info.entries:
            return {"error": "no videos found", "source": info.source_url}
        items = [(r.position, r.video_id, r.title) for r in info.entries]
        existing = self.store.find_job_by_source(info.source_url)
        if existing:  # idempotent: same playlist again = resume + pick up newly added videos
            added = self.store.add_job_items(existing["job_id"], items)
            if added and existing["status"] == "done":
                self.store.update_job(existing["job_id"], status="pending")
            return {"job_id": existing["job_id"], "existing": True, "added": added, "total": existing["total"] + added}
        job_id = _slug(info.title) + "-" + hashlib.sha1(info.source_url.encode()).hexdigest()[:6]
        self.store.create_job(job_id, info.source_url, info.title, items)
        self.store.log("info", f"job created with {len(items)} videos", job_id=job_id)
        return {"job_id": job_id, "existing": False, "total": len(items)}

    def _list_collection(self, url: str) -> PlaylistInfo:
        for be in get_backends(self.s):
            try:
                if be.check()[0]:
                    self.throttle.acquire(max_wait=120)
                    return be.list_collection(url)
            except NotImplementedError:
                continue
        raise YttError("no backend can expand playlists (is yt-dlp installed?)")

    def start_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.job(job_id)
        if not job:
            return {"error": f"unknown job {job_id}"}
        if job["status"] in ("done", "cancelled") and not self.store.items(job_id, "pending"):
            return {"job_id": job_id, "status": job["status"], "note": "nothing to do"}
        if self._worker_alive(job):
            return {"job_id": job_id, "status": "running", "note": "worker already active"}
        if job["status"] in ("paused", "cancelled", "interrupted", "done"):
            self.store.update_job(job_id, status="pending", pause_reason="", resume_after=0)
        pid = procs.spawn_detached(["_work", job_id], self.s.logs_dir / f"{job_id}.log")
        self.store.log("info", f"worker started pid={pid}", job_id=job_id)
        return {"job_id": job_id, "status": "starting", "pid": pid}

    def _worker_alive(self, job: dict) -> bool:
        return (job["status"] == "running" and job["worker_pid"] and
                now() - job["heartbeat_at"] < self.s.heartbeat_seconds * 4 and procs.pid_alive(job["worker_pid"]))

    def pause_job(self, job_id: str) -> dict[str, Any]:
        self.store.update_job(job_id, status="paused", pause_reason="user")
        return {"job_id": job_id, "status": "paused"}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        self.store.update_job(job_id, status="cancelled", pause_reason="user")
        return {"job_id": job_id, "status": "cancelled"}

    def run_job(self, job_id: str, sleep: Callable[[float], None] = time.sleep) -> str:
        """Worker loop. Safe to kill at ANY point: progress is committed per video."""
        pid = os.getpid()
        if not self.store.claim_job(job_id, pid, stale_after=self.s.heartbeat_seconds * 4):
            return "not-claimed"
        log = lambda lvl, msg, vid="": self.store.log(lvl, msg, job_id=job_id, video_id=vid)  # noqa: E731
        last_hb = [0.0]

        def heartbeat(*_: Any) -> None:
            if now() - last_hb[0] >= self.s.heartbeat_seconds:
                last_hb[0] = now()
                if self.store.heartbeat(job_id, pid) != "running":
                    raise _Stop()

        def sleep_until(ts: float) -> None:
            while now() < ts:
                heartbeat()
                sleep(min(self.s.heartbeat_seconds, max(0.0, ts - now())))

        attempts: dict[str, int] = {}
        broken_streak, auto_updated, offline_streak = 0, False, 0
        try:
            while True:
                heartbeat()
                pending = [i for i in self.store.items(job_id, "pending")
                           if attempts.get(i["video_id"], 0) < self.s.max_attempts_per_video]
                if not pending:
                    break
                # first-pass items before retries
                pending.sort(key=lambda i: (attempts.get(i["video_id"], 0), i["position"]))
                item = pending[0]
                vid = item["video_id"]
                if self.store.load_transcript(vid):  # already cached (other job/app) -> free
                    self.store.set_item(job_id, vid, status="done", reason="cached")
                    continue
                row = self.store.video_row(vid)
                if row and row["status"] in ("no_captions", "unavailable"):
                    self.store.set_item(job_id, vid, status="skipped", reason=row["status"])
                    continue
                try:
                    self.fetch_video(vid, max_wait=self.s.worker_max_wait_seconds, on_wait=heartbeat)
                    self.store.set_item(job_id, vid, status="done", reason="")
                    broken_streak = offline_streak = 0
                    log("info", "fetched", vid)
                except Throttled as e:  # wait exceeds what this worker is allowed to sleep
                    self.store.update_job(job_id, status="paused", pause_reason=f"{AUTO_PAUSE}{e.reason}",
                                          resume_after=now() + e.wait_seconds, worker_pid=0)
                    log("warn", f"paused: {e}")
                    return "paused"
                except RateLimited as e:
                    blocks = self.throttle.status()["consecutive_blocks"]
                    if blocks >= self.s.max_consecutive_blocks:
                        until = now() + self.throttle.status()["blocked_for_seconds"]
                        reason = f"{AUTO_PAUSE}YouTube blocked {blocks}x in a row ({e.kind})"
                        log("warn", reason)
                        if until - now() > self.s.worker_max_wait_seconds:
                            self.store.update_job(job_id, status="paused", pause_reason=reason, resume_after=until,
                                                  worker_pid=0)
                            return "paused"
                        # sleep it out ourselves; status stays 'running' so heartbeats keep working
                        self.store.update_job(job_id, pause_reason=reason, resume_after=until)
                        sleep_until(until)
                        self.store.update_job(job_id, pause_reason="", resume_after=0)
                    # otherwise: next acquire() waits out the escalating backoff window
                except NetworkError as e:  # PC offline/proxy: wait with growing delay, never burn attempts
                    offline_streak += 1
                    wait = min(60 * 2 ** (offline_streak - 1), 1800)
                    log("warn", f"network problem #{offline_streak}, retry in {wait}s: {str(e)[:200]}", vid)
                    if wait > self.s.worker_max_wait_seconds or offline_streak > 12:
                        self.store.update_job(job_id, status="paused", worker_pid=0, resume_after=now() + wait,
                                              pause_reason=f"{AUTO_PAUSE}offline / cannot reach YouTube")
                        return "paused"
                    self.store.update_job(job_id, pause_reason=f"{AUTO_PAUSE}offline, retrying", resume_after=now() + wait)
                    sleep_until(now() + wait)
                    self.store.update_job(job_id, pause_reason="", resume_after=0)
                except (NoCaptions, VideoUnavailable) as e:
                    self.store.set_item(job_id, vid, status="skipped", reason=f"{e.kind}: {str(e)[:200]}")
                    log("info", f"skipped ({e.kind})", vid)
                except NeedsUpdate as e:
                    broken_streak += 1
                    attempts[vid] = attempts.get(vid, 0) + 1
                    log("error", f"needs update ({broken_streak}): {e}", vid)
                    if broken_streak >= self.s.broken_streak_to_pause:
                        if self.s.auto_update == "auto" and not auto_updated:
                            log("info", "auto-updating YouTube layer")
                            res = updater.update(self.store)
                            auto_updated, broken_streak = True, 0
                            attempts.clear()
                            log("info", f"auto-update done: {res['changed'] or 'no changes'}")
                            continue
                        self.store.update_job(job_id, status="paused", worker_pid=0,
                                              pause_reason="needs_update: YouTube changed something. Run `ytt update` "
                                                           "then resume the job.")
                        return "needs_update"
                except YttError as e:
                    attempts[vid] = attempts.get(vid, 0) + 1
                    log("warn", f"attempt {attempts[vid]} failed: {e}", vid)
                    if attempts[vid] >= self.s.max_attempts_per_video:
                        self.store.set_item(job_id, vid, status="failed", reason=str(e)[:300])
            # finished the pass
            left = self.store.items(job_id, "pending")
            if left:  # only items that exhausted attempts in this run remain
                for i in left:
                    self.store.set_item(job_id, i["video_id"], status="failed", reason="max attempts")
            self.store.update_job(job_id, status="done", worker_pid=0, pause_reason="")
            log("info", "job finished")
            if self.s.export_markdown:
                self.export_job(job_id)
            return "done"
        except _Stop:
            log("info", "worker stopped (pause/cancel requested)")
            self.store.update_job(job_id, worker_pid=0)
            return "stopped"

    def recover(self) -> list[dict[str, Any]]:
        """Called on every MCP/CLI start: restart jobs a crash, reboot or session end left behind."""
        started = []
        for job in self.store.jobs(limit=200):
            st = job["status"]
            stale = now() - job["heartbeat_at"] > self.s.heartbeat_seconds * 4
            due_auto = st == "paused" and job["pause_reason"].startswith(AUTO_PAUSE) and job["resume_after"] <= now()
            very_stale = now() - job["heartbeat_at"] > 600  # PID may have been reused by another process
            if st == "running" and stale and (very_stale or not procs.pid_alive(job["worker_pid"])):
                self.store.update_job(job["job_id"], status="interrupted", worker_pid=0)
                st = "interrupted"
            if (st in ("interrupted", "pending") or due_auto) and self.s.auto_resume_on_start:
                if self.store.items(job["job_id"], "pending"):
                    started.append(self.start_job(job["job_id"]))
        return started

    # ---------- status / progress ----------
    def job_status(self, job_id: str | None = None, verbose: bool = False) -> dict[str, Any]:
        if not job_id:
            return {"jobs": [self._job_summary(j) for j in self.store.jobs(limit=10)], "throttle": self.throttle.status()}
        job = self.store.job(job_id)
        if not job:
            return {"error": f"unknown job {job_id}"}
        out = self._job_summary(job)
        out["throttle"] = self.throttle.status()
        if verbose:
            out["problems"] = [{"video_id": i["video_id"], "status": i["status"], "reason": i["reason"][:120]}
                               for i in self.store.items(job_id) if i["status"] in ("failed", "skipped")][:30]
            out["events"] = [f"{e['time']} {e['level']} {e['video_id']} {e['message'][:160]}"
                             for e in self.store.recent_events(10, job_id)]
        return out

    def _job_summary(self, job: dict) -> dict[str, Any]:
        c = self.store.counts(job["job_id"])
        pending = c.get("pending", 0)
        per_video = (self.s.min_delay_seconds + self.s.max_delay_seconds) / 2 + 4
        per_video = max(per_video, 3600 / max(1, self.s.hourly_cap))
        d: dict[str, Any] = {
            "job_id": job["job_id"], "title": job["title"][:80], "status": job["status"],
            "total": job["total"], "done": c.get("done", 0), "pending": pending,
            "skipped": c.get("skipped", 0), "failed": c.get("failed", 0), "notes_done": c.get("notes_done", 0),
        }
        if pending and job["status"] in ("running", "pending"):
            d["eta_min"] = round(pending * per_video / 60)
        if job["pause_reason"]:
            d["pause_reason"] = job["pause_reason"]
        if job["resume_after"] and job["resume_after"] > now():
            d["resumes_at"] = iso(job["resume_after"])
        return d

    def next_for_notes(self, job_id: str, limit: int = 1) -> dict[str, Any]:
        """Resume point for AI note-taking: next fetched video(s) whose notes aren't done yet."""
        rows = [i for i in self.store.items(job_id, "done") if i["notes_status"] != "done"][:limit]
        out = []
        for i in rows:
            t = self.store.load_transcript(i["video_id"])
            out.append({"position": i["position"], "video_id": i["video_id"],
                        "title": (t.title if t else i["title"])[:100],
                        "chars": t.char_count if t else 0, "duration": F.fmt_ts(t.duration) if t else "?"})
        c = self.store.counts(job_id)
        return {"job_id": job_id, "next": out, "notes_done": c.get("notes_done", 0), "fetched": c.get("done", 0),
                "still_downloading": c.get("pending", 0)}

    def mark_notes(self, job_id: str, video_ids: list[str], ref: str = "") -> dict[str, Any]:
        for v in video_ids:
            self.store.set_item(job_id, v, notes_status="done", notes_ref=ref[:300])
        return {"marked": len(video_ids), **{k: v for k, v in self.next_for_notes(job_id, 1).items() if k != "job_id"}}

    # ---------- export ----------
    def export_job(self, job_id: str, every: int | None = None) -> dict[str, Any]:
        job = self.store.job(job_id)
        if not job:
            return {"error": f"unknown job {job_id}"}
        folder = self.s.exports_dir / job_id
        folder.mkdir(parents=True, exist_ok=True)
        index = [f"# {job['title']}\n", f"Source: {job['source_url']}\n", "| # | Title | Duration | Status | File |",
                 "|---|---|---|---|---|"]
        written = 0
        for i in self.store.items(job_id):
            t = self.store.load_transcript(i["video_id"]) if i["status"] == "done" else None
            title = (t.title if t and t.title else i["title"]) or i["video_id"]
            fname = ""
            if t:
                fname = f"{i['position']:03d} - {_safe(title)[:80]}.md"
                body = F.header(t) + "\n" + F.render(t, every=every or self.s.timestamp_every_seconds,
                                                      remove_fillers=self.s.remove_fillers) + "\n"
                (folder / fname).write_text(body, encoding="utf-8")
                written += 1
            index.append(f"| {i['position']} | {title} | {F.fmt_ts(t.duration) if t else ''} | {i['status']} | "
                         f"{fname} |")
        (folder / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
        return {"folder": str(folder), "files": written}

    # ---------- maintenance ----------
    def doctor(self, live_video: str | None = None) -> dict[str, Any]:
        rep: dict[str, Any] = {"home": str(self.s.home), "versions": updater.versions(),
                               "js_runtimes": updater.js_runtimes() or "NONE (install deno: scoop install deno)",
                               "backends": {}, "throttle": self.throttle.status()}
        for be in get_backends(self.s):
            rep["backends"][be.name] = be.check()[1]
        bg = updater.bgutil_home() / "server" / "build" / "main.js"
        rep["pot_provider_server_built"] = bg.exists()
        rep["update_due"] = updater.update_due(self.store, self.s.update_check_days)
        warnings = []
        if rep["versions"].get("bgutil-ytdlp-pot-provider") == "missing" or not bg.exists():
            warnings.append("PO-token provider not fully installed: captions may come back empty. Run setup.ps1 / `ytt update`.")
        if isinstance(rep["js_runtimes"], str):
            warnings.append("No JavaScript runtime: yt-dlp cannot solve YouTube challenges.")
        if rep["update_due"]:
            warnings.append(f"YouTube layer not updated in {self.s.update_check_days}+ days: run `ytt update`.")
        rep["warnings"] = warnings
        if live_video:
            vid = video_id(live_video)
            try:
                t = self.fetch_video(vid, max_wait=120, refresh=True) if vid else None
                rep["live_test"] = f"OK {vid}: {t.char_count} chars via {t.backend} ({t.language}/{t.kind})" if t else "bad id"
            except YttError as e:
                rep["live_test"] = f"FAILED {e.kind}: {str(e)[:300]}"
        return rep

    def update(self) -> dict[str, Any]:
        return updater.update(self.store)


class _Stop(Exception):
    pass


def _hint(e: YttError) -> str:
    return {
        "rate_limited": "YouTube is throttling this PC. Wait (tool backs off automatically); don't retry in a loop.",
        "bot_check": "YouTube bot check. Tool is backing off. Avoid cookies unless necessary.",
        "no_captions": "Video has no usable captions.",
        "unavailable": "Video is private/removed/restricted.",
        "network": "This PC can't reach YouTube (offline/proxy/VPN). Check the connection and retry.",
        "needs_update": "YouTube changed something: run `ytt update` (or yt_maintenance action=update).",
    }.get(e.kind, "Check `ytt doctor`.")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "job"


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
