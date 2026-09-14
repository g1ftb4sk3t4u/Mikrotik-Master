"""Core scan/download engine. No UI dependency - emits events to a callback so
CLI and GUI front ends can render them however they like.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from . import catalog, discovery
from .state import Manifest

DEFAULT_USER_AGENT = "MikrotikCdnGrabber/2.0 (+headless/gui archival tool)"


class Engine:
    def __init__(self, output_dir: str, download_workers: int = 8, test_workers: int = 16,
                 max_retries: int = 3, architectures=None, categories=None,
                 include_prerelease: bool = False, on_event=None, stop_flag=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_workers = max(1, download_workers)
        self.test_workers = max(1, test_workers)
        self.max_retries = max_retries
        self.architectures = architectures or catalog.ARCHITECTURES
        self.categories = categories or catalog.DEFAULT_CATEGORIES
        self.include_prerelease = include_prerelease
        self._on_event = on_event or (lambda evt: None)
        # callable returning True when the caller wants us to bail out early
        self._stop_flag = stop_flag or (lambda: False)

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        # Default pool_maxsize is 10; with test_workers/download_workers
        # commonly set well above that, extra threads would silently block
        # waiting for a free pooled connection instead of erroring - not a
        # hang, but it defeats the point of raising worker counts.
        pool_size = max(20, self.test_workers, self.download_workers)
        adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.manifest = Manifest(self.output_dir)

    # -- eventing -----------------------------------------------------
    def _emit(self, kind: str, **payload):
        self._on_event({"type": kind, **payload})

    def log(self, message: str, level: str = "INFO"):
        self._emit("log", message=message, level=level)

    def _stopped(self) -> bool:
        try:
            return bool(self._stop_flag())
        except Exception:
            return False

    # -- discovery ------------------------------------------------------
    def discover_known_versions(self) -> set:
        """Cheap, authoritative: RSS + official per-channel LATEST pointers."""
        found = set()
        found |= discovery.fetch_channel_pointers(self.session)
        found |= discovery.fetch_rss_versions(self.session)
        if found:
            self.log(f"Authoritative sources report {len(found)} current version(s): {sorted(found)}", "INFO")
        return found

    def full_scan(self, start_version: str, end_version: str):
        """Discover every version in range via bounded brute force + authoritative
        sources, downloading each version as soon as it's confirmed rather than
        waiting for the whole candidate sweep to finish first.

        A full default-range sweep is ~8,000 candidate version strings; probing
        all of them before starting a single download meant a run could spend
        a long time looking "stuck" with nothing landing on disk, and a crash
        or interruption during that phase left the archive completely empty
        even though real versions had already been confirmed. Downloading
        inline as each probe future completes fixes both: files start
        appearing within seconds, and progress survives an interruption.
        """
        known = self.discover_known_versions()
        for v in known:
            self.manifest.record_version(v)
            if not self._stopped():
                self.download_version(v)
        self.manifest.save()

        candidates = discovery.generate_candidates(start_version, end_version, self.include_prerelease)
        self.log(f"Probing {len(candidates)} candidate version strings ({self.test_workers} workers)...", "INFO")

        found_versions = set(known)
        probed = 0
        total = len(candidates)
        with ThreadPoolExecutor(max_workers=self.test_workers) as ex:
            futures = {ex.submit(discovery.probe_version_exists, self.session, v): v for v in candidates}
            for fut in as_completed(futures):
                v = futures[fut]
                probed += 1
                if probed % 200 == 0 or probed == total:
                    self._emit("progress", phase="scan", done=probed, total=total)

                if self._stopped():
                    continue  # let remaining probe futures drain; skip downloads

                try:
                    exists = fut.result()
                except Exception:
                    exists = False
                if not exists or v in found_versions:
                    continue

                found_versions.add(v)
                self.log(f"Found version: {v} - downloading now", "FOUND")
                self.manifest.record_version(v)
                self.manifest.save()
                self.download_version(v)

        self.log(f"Scan complete: {len(found_versions)} version(s) present on the CDN.", "SUCCESS")
        self.manifest.mark_full_scan()
        self.manifest.save()
        return sorted(found_versions, key=_version_sort_key)

    def watch_once(self):
        """One check-for-new-versions pass, suitable for a daily scheduled run."""
        known = self.discover_known_versions()
        new = [v for v in known if not self.manifest.has_version(v)]
        if not new:
            self.log("No new versions since last check.", "INFO")
        for v in new:
            if self._stopped():
                break
            self.log(f"New version detected: {v}", "FOUND")
            self.manifest.record_version(v)
            self.download_version(v)
        self.manifest.mark_watch_check()
        self.manifest.save()
        return new

    def watch_loop(self, interval_hours: float = 24.0):
        self.log(f"Watch mode: checking every {interval_hours}h for new versions.", "INFO")
        while not self._stopped():
            try:
                self.watch_once()
            except Exception as e:
                self.log(f"Watch check failed: {e}", "ERROR")
            sleep_seconds = max(60.0, interval_hours * 3600)
            slept = 0.0
            while slept < sleep_seconds and not self._stopped():
                chunk = min(5.0, sleep_seconds - slept)
                time.sleep(chunk)
                slept += chunk

    # -- download ---------------------------------------------------------
    def download_version(self, version: str):
        files = catalog.build_file_list(version, self.architectures, self.categories)
        with ThreadPoolExecutor(max_workers=self.download_workers) as ex:
            futures = {
                ex.submit(self._download_file, version, category, arch, filename, url): filename
                for category, arch, filename, url in files
            }
            for fut in as_completed(futures):
                if self._stopped():
                    break
                try:
                    fut.result()
                except Exception as e:
                    self.log(f"Unexpected download error: {e}", "ERROR")

    def _download_file(self, version: str, category: str, arch, filename: str, url: str, retry: int = 0) -> bool:
        subdir = self.output_dir / version / (arch or "")
        out_path = subdir / filename

        if out_path.exists() and out_path.stat().st_size > 0:
            # A file already on disk is trusted on its own - requiring a
            # matching manifest entry too would mean pointing this at an
            # archive built by an older version of this tool (or one with a
            # deleted/corrupted manifest.json) re-downloads everything it
            # already has instead of recognizing it. Backfill the manifest
            # from what's actually there so future runs stay consistent.
            if not self.manifest.has_file(version, filename):
                size = out_path.stat().st_size
                rel_path = str(out_path.relative_to(self.output_dir))
                self.manifest.record_file(version, filename, size, rel_path)
            self._emit("stat", key="files_skipped", amount=1)
            self.manifest.bump_stat("files_skipped")
            return True

        try:
            resp = self.session.get(url, timeout=30, stream=True)
            if resp.status_code == 404:
                return False
            resp.raise_for_status()

            out_path.parent.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            with open(out_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if self._stopped():
                        break

            rel_path = str(out_path.relative_to(self.output_dir))
            self.manifest.record_file(version, filename, downloaded, rel_path)
            self.manifest.bump_stat("files_downloaded")
            self.manifest.bump_stat("bytes_downloaded", downloaded)
            self._emit("stat", key="files_downloaded", amount=1)
            self._emit("stat", key="bytes_downloaded", amount=downloaded)
            self.log(f"[{category}] {filename} ({downloaded / 1024 / 1024:.2f} MB)", "SUCCESS")
            return True
        except requests.RequestException as e:
            if retry < self.max_retries:
                backoff = 2 ** retry
                self.log(f"Retry {retry + 1}/{self.max_retries} for {filename}: {e} (sleeping {backoff}s)", "WARNING")
                time.sleep(backoff)
                return self._download_file(version, category, arch, filename, url, retry + 1)
            self.log(f"Failed: {filename}: {e}", "ERROR")
            self.manifest.bump_stat("files_failed")
            self._emit("stat", key="files_failed", amount=1)
            try:
                if out_path.exists():
                    out_path.unlink()
            except OSError:
                pass
            return False


def _version_sort_key(version: str):
    import re
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not m:
        return (0, 0, 0, version)
    major, minor, patch = m.groups()
    return (int(major), int(minor), int(patch or 0), version)
