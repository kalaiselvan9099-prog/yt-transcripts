"""Process helpers: detached background workers + isolated, time-limited fetch subprocesses (Windows-aware)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WIN = sys.platform == "win32"


def python_exe(background: bool = False) -> str:
    exe = Path(sys.executable)
    if WIN and background:
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            return str(pyw)  # no console window flashes up
    return str(exe)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def spawn_detached(args: list[str], log_file: Path) -> int:
    """Start `python -m yt_transcripts <args>` fully detached so it outlives the AI app / MCP server."""
    cmd = [python_exe(background=True), "-m", "yt_transcripts", *args]
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as out:  # child keeps its own handle; parent closes its copy
        kw: dict = dict(stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=_env(), close_fds=True)
        if WIN:
            base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            # Escape the app's Windows job object so closing Claude/Cursor doesn't kill the worker.
            for flags in (base | subprocess.CREATE_BREAKAWAY_FROM_JOB, base):
                try:
                    return subprocess.Popen(cmd, creationflags=flags, **kw).pid
                except OSError:
                    continue
            raise RuntimeError("could not start background worker")
        return subprocess.Popen(cmd, start_new_session=True, **kw).pid


def run_isolated(args: list[str], timeout: float) -> dict:
    """Run `python -m yt_transcripts <args>` and parse the last JSON line of stdout.

    Isolation buys: a hung/crashed YouTube library can't freeze the MCP server, and every fetch
    imports the *current* yt-dlp - so `ytt update` takes effect immediately, even mid-job.
    """
    cmd = [python_exe(), "-m", "yt_transcripts", *args]
    kw: dict = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", env=_env())
    if WIN:
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        p = subprocess.run(cmd, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_kind": "error", "message": f"fetch timed out after {int(timeout)}s"}
    for line in reversed((p.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    tail = ((p.stderr or "") + (p.stdout or ""))[-1500:]
    return {"ok": False, "error_kind": "error", "message": f"fetch process failed (exit {p.returncode}): {tail}"}


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if WIN:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return str(pid) in out
        except OSError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
