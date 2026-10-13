"""Settings: packaged defaults -> <YTT_HOME>/config.toml -> YTT_* environment variables."""
from __future__ import annotations

import json
import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from importlib import resources
from pathlib import Path
from typing import Any


def default_home() -> Path:
    if env := os.environ.get("YTT_HOME"):
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ytt"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ytt"


@dataclass
class Settings:
    home: Path = field(default_factory=default_home)
    languages: list[str] = field(default_factory=lambda: ["en"])
    prefer_manual: bool = True
    allow_translated: bool = False
    backends: list[str] = field(default_factory=lambda: ["ytdlp", "transcript_api"])
    ytdlp_args: list[str] = field(default_factory=list)
    cookies_from_browser: str = ""
    proxy: str = ""
    fetch_timeout_seconds: int = 180
    min_delay_seconds: float = 8.0
    max_delay_seconds: float = 15.0
    hourly_cap: int = 120
    batch_size: int = 25
    batch_pause_seconds: list[float] = field(default_factory=lambda: [60, 180])
    backoff_schedule_seconds: list[float] = field(default_factory=lambda: [600, 1800, 7200])
    max_consecutive_blocks: int = 3
    max_attempts_per_video: int = 3
    broken_streak_to_pause: int = 3
    auto_resume_on_start: bool = True
    worker_max_wait_seconds: int = 14400
    heartbeat_seconds: int = 20
    export_markdown: bool = True
    response_max_chars: int = 40000
    timestamp_every_seconds: int = 30
    remove_fillers: bool = True
    auto_update: str = "warn"
    update_check_days: int = 7

    # ---- derived paths ----
    @property
    def db_path(self) -> Path:
        return self.home / "ytt.sqlite3"

    @property
    def transcripts_dir(self) -> Path:
        return self.home / "transcripts"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    def ensure_dirs(self) -> None:
        for p in (self.home, self.transcripts_dir, self.exports_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

    def public_dict(self) -> dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["home"] = str(self.home)
        if d.get("proxy"):
            d["proxy"] = "***"
        return d


def _coerce(value: str, current: Any) -> Any:
    """Convert an env-var string to the type of the current value."""
    if isinstance(current, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, list):
        value = value.strip()
        if value.startswith("["):
            return json.loads(value)
        items = [v.strip() for v in value.split(",") if v.strip()]
        if current and isinstance(current[0], (int, float)):
            return [float(v) for v in items]
        return items
    return value


def load_settings(home: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    s = Settings()
    if home is not None:
        s.home = Path(home)
    names = {f.name for f in fields(Settings)}

    def apply(data: dict[str, Any]) -> None:
        for k, v in data.items():
            if k in names and k != "home":
                setattr(s, k, v)

    apply(tomllib.loads(resources.files("yt_transcripts").joinpath("default_config.toml").read_text("utf-8")))
    user_cfg = s.home / "config.toml"
    if user_cfg.exists():
        apply(tomllib.loads(user_cfg.read_text("utf-8")))
    for name in names - {"home"}:
        env = os.environ.get(f"YTT_{name.upper()}")
        if env is not None and env != "":
            setattr(s, name, _coerce(env, getattr(s, name)))
    if overrides:
        apply(overrides)
    if s.min_delay_seconds > s.max_delay_seconds:
        s.max_delay_seconds = s.min_delay_seconds
    s.ensure_dirs()
    return s
