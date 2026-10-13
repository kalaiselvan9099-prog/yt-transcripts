"""Self-maintenance: update the YouTube-facing layer (yt-dlp, EJS solver, PO-token plugin + its
server build, youtube-transcript-api) without touching the stable core."""
from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from .store import Store, iso, now

YOUTUBE_LAYER = ["yt-dlp[default]", "yt-dlp-ejs", "bgutil-ytdlp-pot-provider", "youtube-transcript-api"]
BGUTIL_REPO = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"


def bgutil_home() -> Path:
    return Path.home() / "bgutil-ytdlp-pot-provider"  # plugin's default script-mode location


def versions() -> dict[str, str]:
    out = {}
    for d in ("yt-dlp", "yt-dlp-ejs", "bgutil-ytdlp-pot-provider", "youtube-transcript-api", "mcp", "yt-transcripts"):
        try:
            out[d] = metadata.version(d)
        except metadata.PackageNotFoundError:
            out[d] = "missing"
    return out


def js_runtimes() -> dict[str, str]:
    found = {}
    for name in ("deno", "node"):
        exe = shutil.which(name)
        if not exe:
            continue
        try:
            v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
            found[name] = v.splitlines()[0] if v else "?"
        except (OSError, subprocess.SubprocessError):
            found[name] = "error"
    return found


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           shell=(sys.platform == "win32" and cmd[0] in ("npm", "npx")))
        return p.returncode, (p.stdout + p.stderr)[-2000:]
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def update_bgutil_server(log: list[str]) -> None:
    """Keep the PO-token script server in lock-step with the pip plugin version (mismatch = silent failure)."""
    try:
        want = metadata.version("bgutil-ytdlp-pot-provider")
    except metadata.PackageNotFoundError:
        log.append("bgutil plugin not installed - skipping server build")
        return
    if not shutil.which("git") or not shutil.which("node"):
        log.append("git/node not on PATH - cannot build bgutil server (install: scoop install git nodejs-lts)")
        return
    home = bgutil_home()
    if not home.exists():
        code, out = _run(["git", "clone", BGUTIL_REPO, str(home)])
        log.append(f"clone bgutil: exit {code}")
        if code:
            log.append(out)
            return
    _run(["git", "fetch", "--tags", "--force"], cwd=home)
    code, out = _run(["git", "checkout", "--force", want], cwd=home)
    log.append(f"bgutil checkout {want}: exit {code}")
    if code:
        log.append(out)
        return
    server = home / "server"
    for cmd in (["npm", "ci", "--no-audit", "--no-fund"], ["npx", "tsc"]):
        code, out = _run(cmd, cwd=server)
        log.append(f"{' '.join(cmd)}: exit {code}")
        if code:
            log.append(out)
            return


def update(store: Store | None = None) -> dict:
    log: list[str] = []
    before = versions()
    code, out = _run([sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", *YOUTUBE_LAYER])
    log.append(f"pip upgrade: exit {code}")
    if code:
        log.append(out)
    update_bgutil_server(log)
    if shutil.which("scoop") and shutil.which("deno"):
        c2, _ = _run(["scoop", "update", "deno"], timeout=600)
        log.append(f"scoop update deno: exit {c2}")
    after = versions()
    if store is not None:
        store.set_meta("last_update", str(now()))
        store.log("info", f"update: {before} -> {after}")
    changed = {k: f"{before[k]} -> {after[k]}" for k in after if before.get(k) != after[k]}
    return {"ok": code == 0, "changed": changed, "versions": after, "log": log, "at": iso()}


def update_due(store: Store, days: int) -> bool:
    last = float(store.get_meta("last_update", "0") or 0)
    return (now() - last) > days * 86400
