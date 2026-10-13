"""Register the MCP server in AI apps (Claude desktop, Cursor, Codex, VS Code) - idempotent, with backups.

All apps point at the SAME python + the SAME data folder, so cache, job progress and rate limiting are shared.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

NAME = "yt_transcripts"
ARGS = ["-m", "yt_transcripts", "serve"]


def _home() -> Path:
    return Path.home()


def claude_desktop_paths() -> list[Path]:
    paths = []
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))
        paths.append(appdata / "Claude" / "claude_desktop_config.json")
        pk = Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")) / "Packages"
        if pk.exists():  # Microsoft Store (MSIX) install keeps a virtualised copy
            paths += list(pk.glob("Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json"))
    elif sys.platform == "darwin":
        paths.append(_home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    else:
        paths.append(_home() / ".config" / "Claude" / "claude_desktop_config.json")
    return paths


def vscode_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming")) / "Code" / "User" / "mcp.json"
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    return _home() / ".config" / "Code" / "User" / "mcp.json"


def _backup(p: Path) -> None:
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"))


def _merge_json(p: Path, root_key: str, entry: dict) -> str:
    data = {}
    if p.exists() and p.read_text("utf-8").strip():
        try:
            data = json.loads(p.read_text("utf-8"))
        except json.JSONDecodeError:
            return f"SKIPPED {p}: not valid JSON (fix it by hand; nothing changed)"
    if data.get(root_key, {}).get(NAME) == entry:
        return f"unchanged {p}"
    _backup(p)
    data.setdefault(root_key, {})[NAME] = entry
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f"updated {p}"


def _toml_str(s: str) -> str:
    return json.dumps(s)  # TOML basic strings use the same escaping as JSON for our needs


def install_codex(python: str) -> str:
    p = _home() / ".codex" / "config.toml"
    block = (
        f"[mcp_servers.{NAME}]\n"
        f"command = {_toml_str(python)}\n"
        f"args = [{', '.join(_toml_str(a) for a in ARGS)}]\n"
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 300\n"
    )
    text = p.read_text("utf-8") if p.exists() else ""
    pattern = re.compile(rf"^\[mcp_servers\.{NAME}\]\n(?:(?!^\[).*\n?)*", re.M)
    if pattern.search(text):
        new = pattern.sub(block + "\n", text, count=1)
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else "") + block
    if new.strip() == text.strip():
        return f"unchanged {p}"
    _backup(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new, encoding="utf-8")
    return f"updated {p}"


def install(targets: list[str], python: str | None = None) -> list[str]:
    python = python or sys.executable
    std = {"command": python, "args": ARGS}
    out = []
    if "claude" in targets:
        paths = claude_desktop_paths()
        existing = [p for p in paths if p.exists()] or paths[:1]
        out += [_merge_json(p, "mcpServers", std) for p in existing]
    if "cursor" in targets:
        out.append(_merge_json(_home() / ".cursor" / "mcp.json", "mcpServers", std))
    if "vscode" in targets:
        out.append(_merge_json(vscode_path(), "servers", {"type": "stdio", **std}))
    if "codex" in targets:
        out.append(install_codex(python))
    if "claude-code" in targets:
        cmd = f'claude mcp add --scope user {NAME} -- "{python}" ' + " ".join(ARGS)
        out.append(f"run this once in a terminal: {cmd}")
    out.append("restart each app so it loads the server")
    return out
