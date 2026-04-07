#!/usr/bin/env python3
"""
CentOS-friendly MikroTik scraper (CLI only).

This variant intentionally has no tkinter/GUI imports so it runs cleanly on
headless CentOS servers.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

BASE_CDN_URL = "https://download.mikrotik.com/routeros"
RSS_URL = "https://mikrotik.com/download.rss"

ARCHITECTURES = ["arm", "arm64", "mipsbe", "mmips", "ppc", "smips", "tile", "x86"]

FILE_PATTERNS = [
    "routeros-{arch}-{version}.npk",
    "all_packages-{arch}-{version}.zip",
    "routeros-{arch}-{version}.zip",
    "routeros-{arch}-{version}.upgrade",
    "mikrotik-{version}.iso",
    "cd-{version}.iso",
    "chr-{version}.ova",
    "chr-{version}.vdi",
    "chr-{version}.vmdk",
    "chr-{version}.vhdx",
    "chr-{version}.img",
    "chr-{version}.zip",
    "routeros-{version}.pdf",
    "CHANGELOG",
    "README",
]


class CentOSEngine:
    def __init__(self, output_dir: str, download_workers: int = 8, max_retries: int = 3):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.download_workers = max(1, int(download_workers))
        self.max_retries = max(0, int(max_retries))

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MikroTikScraper-CentOS/1.0"})

        self.version_exists_cache = {}
        self.found_versions = set()
        self.stats = {
            "versions_tested": 0,
            "versions_found": 0,
            "files_downloaded": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "bytes_downloaded": 0,
        }

        self.versions_file = self.output_dir / "found_versions.json"
        self.stats_file = self.output_dir / "download_stats.json"
        self._load_persisted_versions()

    def log(self, message: str):
        print(f"[{datetime.utcnow().isoformat()}Z] {message}")

    def _load_persisted_versions(self):
        if not self.versions_file.exists():
            return
        try:
            data = json.loads(self.versions_file.read_text(encoding="utf-8"))
            for v in data.get("versions", []):
                self.found_versions.add(v)
        except Exception:
            self.log("Warning: failed to load existing found_versions.json")

    def save_found_versions(self):
        payload = {
            "versions": sorted(self.found_versions),
            "saved": datetime.utcnow().isoformat() + "Z",
        }
        self.versions_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save_stats(self):
        payload = {
            "stats": self.stats,
            "found_versions": sorted(self.found_versions),
            "saved": datetime.utcnow().isoformat() + "Z",
        }
        self.stats_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def generate_versions(start_version: str, end_version: str):
        start_parts = start_version.split(".")
        end_parts = end_version.split(".")

        start_major = int(start_parts[0])
        start_minor = int(start_parts[1]) if len(start_parts) > 1 else 0
        end_major = int(end_parts[0])
        end_minor = int(end_parts[1]) if len(end_parts) > 1 else 50

        versions = []
        for major in range(start_major, end_major + 1):
            min_minor = start_minor if major == start_major else 0
            max_minor = end_minor if major == end_major else 99
            for minor in range(min_minor, max_minor + 1):
                base = f"{major}.{minor}"
                versions.append(base)
                for patch in range(1, 21):
                    versions.append(f"{base}.{patch}")
                    for rc in range(1, 6):
                        versions.append(f"{base}.{patch}rc{rc}")
                    for beta in range(1, 6):
                        versions.append(f"{base}.{patch}beta{beta}")
        return versions

    def check_version_exists(self, version: str) -> bool:
        cached = self.version_exists_cache.get(version)
        if cached is not None:
            return cached

        try:
            test_url = f"{BASE_CDN_URL}/{version}/"
            resp = self.session.head(test_url, timeout=10, allow_redirects=True)
            exists = resp.status_code in (200, 301, 302, 403)
            if not exists:
                fallback = f"{BASE_CDN_URL}/{version}/CHANGELOG"
                fallback_resp = self.session.head(fallback, timeout=10)
                exists = fallback_resp.status_code == 200
        except Exception:
            exists = False

        self.version_exists_cache[version] = exists
        return exists

    def build_download_urls(self, version: str):
        urls = []
        for arch in ARCHITECTURES:
            for pattern in FILE_PATTERNS:
                if "{arch}" not in pattern and arch != "x86":
                    continue

                if arch != "x86" and any(x in pattern for x in ["chr-", "mikrotik-", "cd-"]):
                    continue

                filename = pattern.format(arch=arch, version=version) if "{arch}" in pattern else pattern.format(version=version)
                urls.append((f"{BASE_CDN_URL}/{version}/{filename}", arch, filename))
        return urls

    def download_file(self, url: str, version: str, arch: str, filename: str, retry_count: int = 0):
        out_path = self.output_dir / version / arch / filename
        try:
            if out_path.exists() and out_path.stat().st_size > 0:
                self.stats["files_skipped"] += 1
                return True

            response = self.session.get(url, timeout=60, stream=True)
            if response.status_code == 404:
                return False
            response.raise_for_status()

            out_path.parent.mkdir(parents=True, exist_ok=True)
            total_bytes = 0
            with out_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        total_bytes += len(chunk)

            self.stats["files_downloaded"] += 1
            self.stats["bytes_downloaded"] += total_bytes
            return True
        except Exception as exc:
            if retry_count < self.max_retries:
                sleep_for = 2 ** retry_count
                self.log(f"Retry {retry_count + 1} for {filename} after error: {exc}")
                time.sleep(sleep_for)
                return self.download_file(url, version, arch, filename, retry_count + 1)

            self.stats["files_failed"] += 1
            try:
                if out_path.exists():
                    out_path.unlink()
            except Exception:
                pass
            return False

    def process_version(self, version: str):
        if not self.check_version_exists(version):
            return 0

        self.log(f"FOUND version {version}")
        self.found_versions.add(version)
        self.stats["versions_found"] += 1

        urls = self.build_download_urls(version)
        with ThreadPoolExecutor(max_workers=self.download_workers) as pool:
            futures = [pool.submit(self.download_file, url, version, arch, filename) for url, arch, filename in urls]
            for future in as_completed(futures):
                future.result()

        self.save_found_versions()
        self.save_stats()
        return 1

    def scan_range_and_download(self, start_version: str, end_version: str, test_workers: int = 16):
        versions = self.generate_versions(start_version, end_version)
        self.log(f"Generated {len(versions)} candidate versions")

        existing = []
        with ThreadPoolExecutor(max_workers=max(1, int(test_workers))) as pool:
            future_map = {pool.submit(self.check_version_exists, v): v for v in versions}
            for future in as_completed(future_map):
                version = future_map[future]
                self.stats["versions_tested"] += 1
                if future.result():
                    existing.append(version)

        existing = sorted(set(existing), key=lambda s: [int(n) if n.isdigit() else n for n in re.split(r"(\d+)", s)])
        self.log(f"Discovered {len(existing)} existing versions")

        for version in existing:
            self.process_version(version)

        self.save_found_versions()
        self.save_stats()
        self.log("Range scan complete")

    def scan_rss_for_versions(self):
        try:
            response = self.session.get(RSS_URL, timeout=20)
            response.raise_for_status()
            rss_text = response.text
        except Exception as exc:
            self.log(f"RSS fetch failed: {exc}")
            return []

        candidates = set(re.findall(r"\b\d+\.\d+(?:\.\d+)?(?:rc\d+|beta\d+)?\b", rss_text))
        new_versions = sorted([v for v in candidates if v not in self.found_versions])
        return new_versions

    def poll_rss_forever(self, interval_seconds: int = 900):
        interval_seconds = max(60, int(interval_seconds))
        self.log(f"Starting RSS polling every {interval_seconds} seconds")
        while True:
            new_versions = self.scan_rss_for_versions()
            if new_versions:
                self.log(f"RSS found {len(new_versions)} new version(s): {', '.join(new_versions)}")
                for version in new_versions:
                    self.process_version(version)
            else:
                self.log("RSS: no new versions")
            time.sleep(interval_seconds)
