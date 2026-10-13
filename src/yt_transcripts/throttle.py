"""Global, cross-process rate limiter (state lives in SQLite, so Claude + Cursor + Codex + workers
all share one budget and YouTube sees a single, polite client).

Layers (all must pass):
  1. Backoff window after a YouTube block signal (429 / bot check) - escalating schedule.
  2. Rolling hourly cap.
  3. Randomised gap between requests (jitter) + a longer random break every `batch_size` requests.
"""
from __future__ import annotations

import random
import time
from typing import Callable

from .config import Settings
from .errors import Throttled
from .store import Store, now


class Throttle:
    def __init__(self, store: Store, settings: Settings, rng: random.Random | None = None,
                 clock: Callable[[], float] = now, sleep: Callable[[float], None] = time.sleep):
        self.store, self.s = store, settings
        self.rng = rng or random.Random()
        self.clock, self.sleep = clock, sleep

    # ---- core ----
    def try_reserve(self) -> tuple[float, str]:
        """Reserve a request slot if allowed now. Returns (wait_seconds, reason); wait 0 => reserved."""
        t = self.clock()
        with self.store.conn(immediate=True) as c:
            row = c.execute("SELECT * FROM throttle WHERE key='global'").fetchone()
            if row["blocked_until"] > t:
                return row["blocked_until"] - t, f"backing off after YouTube block ({row['last_block_reason']})"
            c.execute("DELETE FROM request_log WHERE ts < ?", (t - 86400,))
            window = c.execute("SELECT COUNT(*), MIN(ts) FROM request_log WHERE ts > ?", (t - 3600,)).fetchone()
            if window[0] >= self.s.hourly_cap:
                return window[1] + 3600 - t + 1, f"hourly cap {self.s.hourly_cap} reached"
            if row["next_allowed_at"] > t:
                return row["next_allowed_at"] - t, "pacing gap"
            batch = row["batch_count"] + 1
            gap = self.rng.uniform(self.s.min_delay_seconds, self.s.max_delay_seconds)
            if self.s.batch_size and batch % self.s.batch_size == 0:
                lo, hi = (list(self.s.batch_pause_seconds) + [0, 0])[:2]
                gap += self.rng.uniform(lo, max(lo, hi))
            c.execute("INSERT INTO request_log(ts) VALUES (?)", (t,))
            c.execute("UPDATE throttle SET next_allowed_at=?, batch_count=? WHERE key='global'", (t + gap, batch))
        return 0.0, "reserved"

    def acquire(self, max_wait: float, on_wait: Callable[[float, str], None] | None = None,
                tick: float = 15.0) -> None:
        """Block until a slot is reserved. Raises Throttled if it would take longer than max_wait."""
        waited = 0.0
        while True:
            wait, reason = self.try_reserve()
            if wait <= 0:
                return
            if waited + wait > max_wait:
                raise Throttled(wait, reason)
            step = min(wait, tick)
            if on_wait:
                on_wait(wait, reason)
            self.sleep(step)
            waited += step

    # ---- feedback from fetch results ----
    def record_block(self, kind: str, detail: str = "") -> tuple[int, float]:
        """YouTube pushed back. Escalate backoff. Returns (consecutive_blocks, blocked_until)."""
        t = self.clock()
        sched = list(self.s.backoff_schedule_seconds) or [600]
        with self.store.conn(immediate=True) as c:
            row = c.execute("SELECT consecutive_blocks FROM throttle WHERE key='global'").fetchone()
            n = row["consecutive_blocks"] + 1
            dur = sched[min(n - 1, len(sched) - 1)]
            if kind == "bot_check":  # bot challenges are a stronger signal -> never less than step 2
                dur = max(dur, sched[min(1, len(sched) - 1)])
            dur *= self.rng.uniform(1.0, 1.2)  # jitter so multiple clients don't resume in lockstep
            until = t + dur
            c.execute("UPDATE throttle SET consecutive_blocks=?, blocked_until=?, last_block_reason=? WHERE key='global'",
                      (n, until, f"{kind}: {detail[:200]}"))
        return n, until

    def record_success(self) -> None:
        with self.store.conn() as c:
            c.execute("UPDATE throttle SET consecutive_blocks=0 WHERE key='global'")

    def status(self) -> dict:
        t = self.clock()
        with self.store.conn() as c:
            row = dict(c.execute("SELECT * FROM throttle WHERE key='global'").fetchone())
            last_hour = c.execute("SELECT COUNT(*) FROM request_log WHERE ts > ?", (t - 3600,)).fetchone()[0]
        return {
            "requests_last_hour": last_hour,
            "hourly_cap": self.s.hourly_cap,
            "consecutive_blocks": row["consecutive_blocks"],
            "blocked_for_seconds": max(0, int(row["blocked_until"] - t)),
            "last_block_reason": row["last_block_reason"],
            "next_request_in_seconds": max(0, int(row["next_allowed_at"] - t)),
        }

    def reset(self) -> None:
        with self.store.conn() as c:
            c.execute("UPDATE throttle SET consecutive_blocks=0, blocked_until=0, next_allowed_at=0 WHERE key='global'")
