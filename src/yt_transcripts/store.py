"""Durable state: SQLite (WAL, multi-process safe) + one JSON file per transcript (atomic writes).

Every app (Claude, Cursor, Codex, CLI, background workers) shares this store, so progress,
cache and rate-limit state are global on the PC.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Transcript

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE videos (
        video_id   TEXT PRIMARY KEY,
        title      TEXT DEFAULT '',
        channel    TEXT DEFAULT '',
        duration   REAL DEFAULT 0,
        status     TEXT NOT NULL DEFAULT 'pending',  -- ok | no_captions | unavailable | failed
        language   TEXT DEFAULT '',
        kind       TEXT DEFAULT '',
        backend    TEXT DEFAULT '',
        chars      INTEGER DEFAULT 0,
        attempts   INTEGER DEFAULT 0,
        error      TEXT DEFAULT '',
        error_kind TEXT DEFAULT '',
        fetched_at TEXT DEFAULT '',
        updated_at REAL DEFAULT 0
    );
    CREATE TABLE jobs (
        job_id       TEXT PRIMARY KEY,
        source_url   TEXT NOT NULL,
        title        TEXT DEFAULT '',
        status       TEXT NOT NULL DEFAULT 'pending', -- pending|running|paused|interrupted|done|cancelled
        pause_reason TEXT DEFAULT '',
        resume_after REAL DEFAULT 0,
        worker_pid   INTEGER DEFAULT 0,
        heartbeat_at REAL DEFAULT 0,
        created_at   REAL NOT NULL,
        updated_at   REAL NOT NULL,
        total        INTEGER DEFAULT 0
    );
    CREATE TABLE job_items (
        job_id       TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
        position     INTEGER NOT NULL,
        video_id     TEXT NOT NULL,
        title        TEXT DEFAULT '',
        status       TEXT NOT NULL DEFAULT 'pending', -- pending|done|skipped|failed
        reason       TEXT DEFAULT '',
        notes_status TEXT NOT NULL DEFAULT 'todo',    -- todo|done  (AI note-taking progress)
        notes_ref    TEXT DEFAULT '',
        updated_at   REAL DEFAULT 0,
        PRIMARY KEY (job_id, video_id)
    );
    CREATE INDEX idx_items_job ON job_items(job_id, position);
    CREATE TABLE throttle (
        key                TEXT PRIMARY KEY,
        next_allowed_at    REAL DEFAULT 0,
        batch_count        INTEGER DEFAULT 0,
        consecutive_blocks INTEGER DEFAULT 0,
        blocked_until      REAL DEFAULT 0,
        last_block_reason  TEXT DEFAULT ''
    );
    CREATE TABLE request_log (ts REAL NOT NULL);
    CREATE INDEX idx_reqlog_ts ON request_log(ts);
    CREATE TABLE events (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       REAL NOT NULL,
        level    TEXT NOT NULL,
        job_id   TEXT DEFAULT '',
        video_id TEXT DEFAULT '',
        message  TEXT NOT NULL
    );
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    INSERT INTO throttle(key) VALUES ('global');
    """,
]


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or now(), tz=timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path, transcripts_dir: Path):
        self.db_path = Path(db_path)
        self.transcripts_dir = Path(transcripts_dir)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self._migrate()

    # ---------- connection ----------
    @contextmanager
    def conn(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path, timeout=60, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=60000")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            c.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def _migrate(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(self.db_path, timeout=60, isolation_level=None)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            ver = c.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[ver:], start=ver + 1):
                c.execute("BEGIN IMMEDIATE")
                try:
                    # re-check inside the lock (another process may have migrated)
                    if c.execute("PRAGMA user_version").fetchone()[0] >= i:
                        c.execute("COMMIT")
                        continue
                    for stmt in [s for s in sql.split(";") if s.strip()]:
                        c.execute(stmt)
                    c.execute(f"PRAGMA user_version={i}")
                    c.execute("COMMIT")
                except BaseException:
                    c.execute("ROLLBACK")
                    raise
        finally:
            c.close()

    # ---------- events ----------
    def log(self, level: str, message: str, job_id: str = "", video_id: str = "") -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO events(ts,level,job_id,video_id,message) VALUES (?,?,?,?,?)",
                (now(), level, job_id, video_id, message[:2000]),
            )
            c.execute("DELETE FROM events WHERE id < (SELECT MAX(id) - 5000 FROM events)")

    def recent_events(self, limit: int = 20, job_id: str | None = None) -> list[dict[str, Any]]:
        with self.conn() as c:
            q = "SELECT * FROM events" + (" WHERE job_id=?" if job_id else "") + " ORDER BY id DESC LIMIT ?"
            rows = c.execute(q, ((job_id, limit) if job_id else (limit,))).fetchall()
        return [dict(r) | {"time": iso(r["ts"])} for r in rows]

    # ---------- meta ----------
    def get_meta(self, key: str, default: str = "") -> str:
        with self.conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, value))

    # ---------- transcripts ----------
    def transcript_path(self, video_id: str) -> Path:
        return self.transcripts_dir / f"{video_id}.json"

    def save_transcript(self, t: Transcript) -> Path:
        path = self.transcript_path(t.video_id)
        fd, tmp = tempfile.mkstemp(dir=self.transcripts_dir, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(t.to_dict(), f, ensure_ascii=False)
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written transcript
        with self.conn() as c:
            c.execute(
                """INSERT INTO videos(video_id,title,channel,duration,status,language,kind,backend,chars,
                                      attempts,error,error_kind,fetched_at,updated_at)
                   VALUES(?,?,?,?,'ok',?,?,?,?,0,'','',?,?)
                   ON CONFLICT(video_id) DO UPDATE SET title=excluded.title, channel=excluded.channel,
                     duration=excluded.duration, status='ok', language=excluded.language, kind=excluded.kind,
                     backend=excluded.backend, chars=excluded.chars, error='', error_kind='',
                     fetched_at=excluded.fetched_at, updated_at=excluded.updated_at""",
                (t.video_id, t.title, t.channel, t.duration, t.language, t.kind, t.backend, t.char_count,
                 t.fetched_at, now()),
            )
        return path

    def load_transcript(self, video_id: str) -> Transcript | None:
        p = self.transcript_path(video_id)
        if not p.exists():
            return None
        try:
            return Transcript.from_dict(json.loads(p.read_text("utf-8")))
        except (json.JSONDecodeError, TypeError, KeyError):
            return None  # corrupt -> treated as missing, will be re-fetched

    def record_video_failure(self, video_id: str, kind: str, error: str, permanent: bool) -> int:
        status = kind if permanent else "failed"
        with self.conn() as c:
            c.execute(
                """INSERT INTO videos(video_id,status,attempts,error,error_kind,updated_at) VALUES(?,?,1,?,?,?)
                   ON CONFLICT(video_id) DO UPDATE SET status=?, attempts=attempts+1, error=?, error_kind=?,
                   updated_at=?""",
                (video_id, status, error[:1000], kind, now(), status, error[:1000], kind, now()),
            )
            return c.execute("SELECT attempts FROM videos WHERE video_id=?", (video_id,)).fetchone()[0]

    def video_row(self, video_id: str) -> dict[str, Any] | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
        return dict(r) if r else None

    # ---------- jobs ----------
    def create_job(self, job_id: str, source_url: str, title: str, items: list[tuple[int, str, str]]) -> None:
        t = now()
        with self.conn(immediate=True) as c:
            c.execute(
                "INSERT INTO jobs(job_id,source_url,title,status,created_at,updated_at,total) VALUES(?,?,?,?,?,?,?)",
                (job_id, source_url, title, "pending", t, t, len(items)),
            )
            c.executemany(
                "INSERT OR IGNORE INTO job_items(job_id,position,video_id,title,updated_at) VALUES(?,?,?,?,?)",
                [(job_id, pos, vid, ttl, t) for pos, vid, ttl in items],
            )

    def find_job_by_source(self, source_url: str) -> dict[str, Any] | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM jobs WHERE source_url=? AND status!='cancelled' ORDER BY created_at DESC",
                          (source_url,)).fetchone()
        return dict(r) if r else None

    def add_job_items(self, job_id: str, items: list[tuple[int, str, str]]) -> int:
        """Append newly discovered videos (e.g. playlist grew). Returns count added."""
        with self.conn(immediate=True) as c:
            before = c.execute("SELECT COUNT(*) FROM job_items WHERE job_id=?", (job_id,)).fetchone()[0]
            c.executemany(
                "INSERT OR IGNORE INTO job_items(job_id,position,video_id,title,updated_at) VALUES(?,?,?,?,?)",
                [(job_id, pos, vid, ttl, now()) for pos, vid, ttl in items],
            )
            after = c.execute("SELECT COUNT(*) FROM job_items WHERE job_id=?", (job_id,)).fetchone()[0]
            c.execute("UPDATE jobs SET total=?, updated_at=? WHERE job_id=?", (after, now(), job_id))
        return after - before

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(r) if r else None

    def jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def update_job(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.conn() as c:
            c.execute(f"UPDATE jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id))

    def claim_job(self, job_id: str, pid: int, stale_after: float) -> bool:
        """Atomically become the job's single worker (prevents two workers doubling the request rate)."""
        with self.conn(immediate=True) as c:
            r = c.execute("SELECT status, worker_pid, heartbeat_at FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if r is None or r["status"] in ("done", "cancelled"):
                return False
            alive = r["worker_pid"] and r["worker_pid"] != pid and (now() - r["heartbeat_at"]) < stale_after
            if alive:
                return False
            c.execute("UPDATE jobs SET status='running', worker_pid=?, heartbeat_at=?, pause_reason='', updated_at=? "
                      "WHERE job_id=?", (pid, now(), now(), job_id))
            return True

    def heartbeat(self, job_id: str, pid: int) -> str:
        """Refresh liveness; returns current status so the worker can react to pause/cancel requests."""
        with self.conn() as c:
            c.execute("UPDATE jobs SET heartbeat_at=? WHERE job_id=? AND worker_pid=?", (now(), job_id, pid))
            r = c.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return r["status"] if r else "cancelled"

    def items(self, job_id: str, status: str | None = None) -> list[dict[str, Any]]:
        with self.conn() as c:
            if status:
                rows = c.execute("SELECT * FROM job_items WHERE job_id=? AND status=? ORDER BY position",
                                 (job_id, status)).fetchall()
            else:
                rows = c.execute("SELECT * FROM job_items WHERE job_id=? ORDER BY position", (job_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_item(self, job_id: str, video_id: str, **fields: Any) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.conn() as c:
            c.execute(f"UPDATE job_items SET {cols} WHERE job_id=? AND video_id=?", (*fields.values(), job_id, video_id))

    def counts(self, job_id: str) -> dict[str, int]:
        with self.conn() as c:
            rows = c.execute("SELECT status, COUNT(*) n FROM job_items WHERE job_id=? GROUP BY status",
                             (job_id,)).fetchall()
            notes = c.execute("SELECT COUNT(*) FROM job_items WHERE job_id=? AND notes_status='done'",
                              (job_id,)).fetchone()[0]
        d = {r["status"]: r["n"] for r in rows}
        d["notes_done"] = notes
        return d
