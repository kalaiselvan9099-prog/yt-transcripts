import asyncio
import time

import pytest
from conftest import FakeBackend, vid

from yt_transcripts.config import load_settings
from yt_transcripts.errors import Throttled
from yt_transcripts.store import Store
from yt_transcripts.throttle import Throttle

PL = "https://www.youtube.com/playlist?list=PLtest1234567890"


def test_throttle_is_shared_across_processes(tmp_path):
    s = load_settings(home=tmp_path, overrides=dict(min_delay_seconds=5, max_delay_seconds=5, batch_size=0))
    a = Throttle(Store(s.db_path, s.transcripts_dir), s)
    b = Throttle(Store(s.db_path, s.transcripts_dir), s)  # e.g. Cursor + Claude at the same time
    assert a.try_reserve()[0] == 0
    wait, reason = b.try_reserve()
    assert 4 < wait <= 5 and reason == "pacing gap"
    with pytest.raises(Throttled):
        b.acquire(max_wait=1)


def test_hourly_cap_and_block_escalation(tmp_path):
    s = load_settings(home=tmp_path, overrides=dict(min_delay_seconds=0, max_delay_seconds=0, hourly_cap=3,
                                                    batch_size=0, backoff_schedule_seconds=[10, 20, 40]))
    th = Throttle(Store(s.db_path, s.transcripts_dir), s)
    for _ in range(3):
        assert th.try_reserve()[0] == 0
    wait, reason = th.try_reserve()
    assert reason.startswith("hourly cap") and wait > 3500
    th.reset()
    n1, u1 = th.record_block("rate_limited")
    n2, u2 = th.record_block("rate_limited")
    assert (n1, n2) == (1, 2) and (u2 - time.time()) > (u1 - time.time())
    th.record_success()
    assert th.status()["consecutive_blocks"] == 0


def test_job_runs_to_completion_and_exports(svc):
    r = svc.create_job(PL)
    assert r["total"] == 6 and not r["existing"]
    assert svc.run_job(r["job_id"]) == "done"
    st = svc.job_status(r["job_id"])
    assert st["done"] == 6 and st["status"] == "done"
    folder = svc.s.exports_dir / r["job_id"]
    assert (folder / "index.md").exists() and len(list(folder.glob("0*.md"))) == 6


def test_resume_after_crash_never_refetches(svc):
    FakeBackend.behaviour = {vid(4): ["kill"]}
    job = svc.create_job(PL)["job_id"]
    with pytest.raises(KeyboardInterrupt):
        svc.run_job(job)  # process "dies" at video 4
    assert svc.job_status(job)["done"] == 3
    # simulate: worker gone, heartbeat stale -> recover() marks interrupted and restarts
    svc.store.update_job(job, worker_pid=999999, heartbeat_at=0)
    started = []
    svc.start_job = lambda j: started.append(j) or {"job_id": j}
    svc.recover()
    assert started == [job] and svc.store.job(job)["status"] == "interrupted"
    calls_before = list(FakeBackend.calls)
    assert svc.run_job(job) == "done"
    new_calls = FakeBackend.calls[len(calls_before):]
    assert new_calls == [vid(4), vid(5), vid(6)]  # 1-3 were not fetched again
    # starting the same playlist again is idempotent (resume, not duplicate)
    again = svc.create_job(PL)
    assert again["existing"] and again["job_id"] == job and again["added"] == 0


def test_playlist_growth_is_picked_up(svc):
    job = svc.create_job(PL)["job_id"]
    svc.run_job(job)
    FakeBackend.playlist.append(vid(7))
    again = svc.create_job(PL)
    assert again["added"] == 1 and svc.store.job(job)["status"] == "pending"
    svc.run_job(job)
    assert svc.job_status(job)["done"] == 7


def test_rate_limit_backs_off_then_continues(svc):
    FakeBackend.behaviour = {vid(2): ["rate"], vid(3): ["rate"]}
    job = svc.create_job(PL)["job_id"]
    t0 = time.time()
    assert svc.run_job(job) == "done"
    assert svc.job_status(job)["done"] == 6
    assert time.time() - t0 >= 0.05  # waited out the backoff instead of hammering
    assert FakeBackend.calls.count(vid(2)) == 2


def test_persistent_block_pauses_job_with_resume_time(svc):
    svc.s.worker_max_wait_seconds = 0  # can't sleep it out -> must pause and hand over to recover()
    svc.s.backoff_schedule_seconds = [30, 60, 120]
    FakeBackend.behaviour = {vid(1): ["rate"]}
    job = svc.create_job(PL)["job_id"]
    assert svc.run_job(job) == "paused"
    j = svc.store.job(job)
    assert j["status"] == "paused" and j["pause_reason"].startswith("auto:") and j["resume_after"] > time.time()
    assert svc.job_status(job)["done"] == 0


def test_youtube_change_pauses_with_update_instruction(svc):
    FakeBackend.behaviour = {vid(i): ["broken"] * 5 for i in range(1, 7)}
    job = svc.create_job(PL)["job_id"]
    assert svc.run_job(job) == "needs_update"
    j = svc.store.job(job)
    assert j["status"] == "paused" and "ytt update" in j["pause_reason"]


def test_no_captions_skipped_and_notes_flow(svc):
    FakeBackend.behaviour = {vid(2): ["nocap"]}
    job = svc.create_job(PL)["job_id"]
    svc.run_job(job)
    st = svc.job_status(job, verbose=True)
    assert st["skipped"] == 1 and st["done"] == 5 and st["problems"][0]["video_id"] == vid(2)
    nxt = svc.next_for_notes(job, 2)
    assert [n["video_id"] for n in nxt["next"]] == [vid(1), vid(3)]
    svc.mark_notes(job, [vid(1), vid(3)], ref="doc#lec1")
    nxt = svc.next_for_notes(job, 1)
    assert nxt["next"][0]["video_id"] == vid(4) and nxt["notes_done"] == 2


def test_user_pause_stops_worker(svc):
    job = svc.create_job(PL)["job_id"]
    orig = svc.fetch_video

    def fetch_then_pause(v, **kw):
        t = orig(v, **kw)
        if v == vid(2):
            svc.pause_job(job)
        return t
    svc.fetch_video = fetch_then_pause
    svc.s.heartbeat_seconds = 0
    assert svc.run_job(job) == "stopped"
    assert svc.store.job(job)["status"] == "paused" and svc.job_status(job)["done"] == 2


def test_get_transcript_paging_search_and_tokens(svc):
    r = svc.get_transcript(vid(1), max_chars=2000)
    assert r["title"] == f"Title {vid(1)}" and "next_offset" in r and len(r["text"]) <= 2000
    r2 = svc.get_transcript(vid(1), offset=r["next_offset"], max_chars=2000)
    assert "title" not in r2  # metadata only on page 1
    s = svc.get_transcript(vid(1), search="sentence 150")
    assert s["hits"] == 1 and len(s["text"]) < 1000
    nots = svc.get_transcript(vid(1), timestamps=0, max_chars=10**6)
    assert "[" not in nots["text"]
    assert FakeBackend.calls.count(vid(1)) == 1  # everything after the first call came from cache
    o = svc.get_outline(vid(1))
    assert len(o["sections"]) == 4


def test_import_captions(svc, tmp_path):
    f = tmp_path / "c.vtt"
    f.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nimported line\n")
    assert svc.import_captions("https://youtu.be/ml50y4RjGiY", str(f))["segments"] == 1
    assert "imported line" in svc.get_transcript("ml50y4RjGiY")["text"]


def test_mcp_tools_end_to_end(svc, monkeypatch):
    from mcp.client import Client
    from yt_transcripts import server

    monkeypatch.setattr(server, "_svc", svc)
    svc.get_transcript(vid(1))  # warm cache

    async def go():
        async with Client(server.mcp) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert names == {"yt_transcript", "yt_outline", "yt_start_job", "yt_job", "yt_notes", "yt_import",
                             "yt_maintenance"}
            res = await c.call_tool("yt_transcript", {"video": vid(1), "start": "0:30", "end": "1:00"})
            text = res.content[0].text
            assert text.splitlines()[0].startswith('{"video_id"') and "[0:30]" in text
            assert not res.structured_content  # no duplicated payload
            res = await c.call_tool("yt_outline", {"video": vid(1)})
            assert "0:00-5:00" in res.content[0].text
            res = await c.call_tool("yt_job", {"action": "status"})
            assert '"jobs"' in res.content[0].text
    asyncio.run(go())


def test_offline_waits_without_burning_attempts(svc, monkeypatch):
    import yt_transcripts.service as S
    FakeBackend.behaviour = {vid(3): ["net"] * 4}  # more than max_attempts_per_video (3)
    monkeypatch.setattr(S, "now", lambda: time.time())
    slept = []
    job = svc.create_job(PL)["job_id"]
    # 60s/120s/240s/480s waits would exceed worker_max_wait (5s) -> job auto-pauses, video NOT marked failed
    assert svc.run_job(job, sleep=slept.append) == "paused"
    assert svc.store.job(job)["pause_reason"].startswith("auto:offline")
    items = {i["video_id"]: i["status"] for i in svc.store.items(job)}
    assert items[vid(3)] == "pending"


def test_real_detached_worker_and_cli(tmp_path):
    """Spawns a genuine background worker process via the CLI path (no network: items pre-cached)."""
    import os
    import subprocess
    import sys

    from yt_transcripts.models import Segment, Transcript
    from yt_transcripts.service import Service
    env = dict(os.environ, YTT_HOME=str(tmp_path), YTT_HEARTBEAT_SECONDS="1")
    os.environ["YTT_HOME"] = str(tmp_path)
    try:
        svc = Service(load_settings(home=tmp_path))
        ids = ["aaaaaaaaaaa", "bbbbbbbbbbb"]
        for v in ids:
            svc.store.save_transcript(Transcript(v, "en", "manual", "test", [Segment(0, 1, "hi")], title=v))
        out = subprocess.run([sys.executable, "-m", "yt_transcripts", "job", "start", ",".join(ids)],
                             capture_output=True, text=True, env=env, timeout=60).stdout
        assert '"status": "starting"' in out
        job = svc.store.jobs()[0]["job_id"]
        for _ in range(100):
            if svc.store.job(job)["status"] == "done":
                break
            time.sleep(0.1)
        assert svc.job_status(job)["done"] == 2
        assert (svc.s.exports_dir / job / "index.md").exists()
    finally:
        os.environ.pop("YTT_HOME", None)
