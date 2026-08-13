"""Persistent state: which versions/files we've already got, written atomically."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


class Manifest:
    """Single JSON manifest tracking discovered versions, downloaded files, and stats.

    Replaces the old found_versions.json + download_stats.json pair with one
    file, written via write-to-temp-then-replace so a crash mid-write can't
    corrupt it (the old version could, since json.dump wrote in place).
    """

    def __init__(self, output_dir: Path):
        self.path = Path(output_dir) / "manifest.json"
        self._lock = threading.Lock()
        self.data = {
            "versions": {},   # version -> {"discovered_at": iso, "files": {filename: {size, path}}}
            "stats": {
                "versions_found": 0,
                "files_downloaded": 0,
                "files_skipped": 0,
                "files_failed": 0,
                "bytes_downloaded": 0,
            },
            "last_full_scan": None,
            "last_watch_check": None,
        }
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        with self._lock:
            tmp_path = self.path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp_path, self.path)

    def has_version(self, version: str) -> bool:
        return version in self.data["versions"]

    def record_version(self, version: str):
        with self._lock:
            if version not in self.data["versions"]:
                self.data["versions"][version] = {
                    "discovered_at": _now(),
                    "files": {},
                }
                self.data["stats"]["versions_found"] += 1

    def has_file(self, version: str, filename: str, expected_size: int = None) -> bool:
        entry = self.data["versions"].get(version, {}).get("files", {}).get(filename)
        if not entry:
            return False
        if expected_size is not None and entry.get("size") != expected_size:
            return False
        return True

    def record_file(self, version: str, filename: str, size: int, rel_path: str):
        with self._lock:
            self.data["versions"].setdefault(version, {"discovered_at": _now(), "files": {}})
            self.data["versions"][version]["files"][filename] = {
                "size": size,
                "path": rel_path,
                "downloaded_at": _now(),
            }

    def bump_stat(self, key: str, amount=1):
        with self._lock:
            self.data["stats"][key] = self.data["stats"].get(key, 0) + amount

    def mark_full_scan(self):
        with self._lock:
            self.data["last_full_scan"] = _now()

    def mark_watch_check(self):
        with self._lock:
            self.data["last_watch_check"] = _now()

    def known_versions(self):
        return set(self.data["versions"].keys())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
