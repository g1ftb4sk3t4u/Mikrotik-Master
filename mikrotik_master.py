#!/usr/bin/env python3
"""
MikroTik Master Scraper

Combines features from two earlier scripts into one stable tool:
- GUI (tkinter) with logging and stats
- Full CDN crawl to download files for discovered versions
- RSS polling and periodic changelog/readme checks for updates
- Persistent found_versions and stats (JSON)

Usage: run as script. GUI provides daemon toggles and options.
"""

import os
import re
import json
import time
import threading
import queue
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Configuration defaults
BASE_CDN_URL = "https://download.mikrotik.com/routeros"
ARCHITECTURES = [
    'arm', 'arm64', 'mipsbe', 'mmips', 'ppc', 'smips', 'tile', 'x86'
]

FILE_PATTERNS = [
    'routeros-{arch}-{version}.npk',
    'all_packages-{arch}-{version}.zip',
    'routeros-{arch}-{version}.zip',
    'mikrotik-{version}.iso',
    'cd-{version}.iso',
    'chr-{version}.ova',
    'chr-{version}.vdi', 
    'chr-{version}.vmdk',
    'chr-{version}.vhdx',
    'chr-{version}.img',
    'chr-{version}.zip',
    'routeros-{arch}-{version}.upgrade',
    'routeros-{version}.pdf',
    'CHANGELOG',
    'README',
]

RSS_URL = 'https://mikrotik.com/download.rss'


class MasterEngine:
    def __init__(self, output_dir: str, download_workers: int = 8, max_retries: int = 3, gui=None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_workers = max(1, int(download_workers))
        self.max_retries = max_retries
        self.gui = gui

        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'MikroTikScraper/1.0'})

        self.version_exists_cache = {}
        self.found_versions = set()
        self.lock = threading.Lock()

        # persistent files
        self.versions_file = self.output_dir / 'found_versions.json'
        self.stats_file = self.output_dir / 'download_stats.json'

        # load persisted if available
        self._load_persisted()

    def _load_persisted(self):
        if self.versions_file.exists():
            try:
                with open(self.versions_file, 'r') as f:
                    data = json.load(f)
                    for v in data.get('versions', []):
                        self.found_versions.add(v)
            except Exception:
                pass

    def log(self, message, level='INFO'):
        if self.gui:
            self.gui.log(message, level)
        else:
            print(f"[{level}] {message}")

    def increment_stat(self, key, amount=1):
        if self.gui:
            with self.gui.stats_lock:
                self.gui.stats[key] = self.gui.stats.get(key, 0) + amount

    def update_stat(self, key, value):
        if self.gui:
            with self.gui.stats_lock:
                self.gui.stats[key] = value

    def generate_all_version_numbers(self, start_major: int, start_minor: int, end_major: int, end_minor: int):
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
        if version in self.version_exists_cache:
            return self.version_exists_cache[version]

        test_url = f"{BASE_CDN_URL}/{version}/"
        try:
            resp = self.session.head(test_url, timeout=8, allow_redirects=True)
            exists = resp.status_code in (200, 301, 302, 403)
            if not exists:
                # try known file
                changelog = f"{BASE_CDN_URL}/{version}/CHANGELOG"
                resp = self.session.head(changelog, timeout=8)
                exists = resp.status_code == 200
            self.version_exists_cache[version] = exists
            return exists
        except Exception:
            self.version_exists_cache[version] = False
            return False

    def build_download_urls(self, version: str):
        urls = []
        for arch in ARCHITECTURES:
            for pattern in FILE_PATTERNS:
                if '{arch}' not in pattern and arch != 'x86':
                    continue

                if arch != 'x86' and any(x in pattern for x in ['chr-', 'mikrotik-', 'cd-']):
                    continue

                if '{arch}' in pattern:
                    filename = pattern.format(arch=arch, version=version)
                else:
                    filename = pattern.format(version=version)

                url = f"{BASE_CDN_URL}/{version}/{filename}"
                urls.append((url, arch, filename))
        return urls

    def download_file(self, url: str, version: str, arch: str, filename: str, retry_count: int = 0) -> bool:
        out_path = self.output_dir / version / arch / filename
        try:
            if out_path.exists() and out_path.stat().st_size > 0:
                self.log(f"[SKIP] {filename} exists", 'INFO')
                self.increment_stat('files_skipped')
                return True

            resp = self.session.get(url, timeout=30, stream=True)
            if resp.status_code == 404:
                return False
            resp.raise_for_status()

            out_path.parent.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            with open(out_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            self.increment_stat('files_downloaded')
            self.increment_stat('bytes_downloaded', downloaded)
            self.log(f"[DOWNLOAD] {filename} ({downloaded / 1024 / 1024:.2f} MB)", 'SUCCESS')
            return True
        except Exception as e:
            if retry_count < self.max_retries:
                backoff = 2 ** retry_count
                self.log(f"[RETRY {retry_count + 1}] {filename}: {e} (sleep {backoff}s)", 'WARNING')
                time.sleep(backoff)
                return self.download_file(url, version, arch, filename, retry_count + 1)
            else:
                self.log(f"[FAILED] {filename}: {e}", 'ERROR')
                self.increment_stat('files_failed')
                # remove partial
                try:
                    if out_path.exists():
                        out_path.unlink()
                except Exception:
                    pass
                return False

    def process_version(self, version: str):
        if not self.check_version_exists(version):
            return 0

        self.log(f"{'='*60}", 'INFO')
        self.log(f"VERSION {version} - FOUND", 'FOUND')
        self.log(f"{'='*60}", 'INFO')

        with self.lock:
            self.found_versions.add(version)

        self.increment_stat('versions_found')
        self.update_stat('current_version', version)

        urls = self.build_download_urls(version)
        with ThreadPoolExecutor(max_workers=self.download_workers) as ex:
            futures = {ex.submit(self.download_file, url, version, arch, fname): fname for url, arch, fname in urls}
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    pass

        return 1

    def save_found_versions(self):
        try:
            with open(self.versions_file, 'w') as f:
                json.dump({'versions': sorted(self.found_versions), 'saved': datetime.utcnow().isoformat()}, f, indent=2)
            self.log(f"Saved versions to {self.versions_file}", 'INFO')
        except Exception as e:
            self.log(f"Failed to save versions: {e}", 'WARNING')

    def save_stats(self):
        try:
            stats = self.gui.stats if self.gui else {}
            with open(self.stats_file, 'w') as f:
                json.dump({'stats': stats, 'found_versions': sorted(self.found_versions), 'saved': datetime.utcnow().isoformat()}, f, indent=2)
            self.log(f"Saved stats to {self.stats_file}", 'INFO')
        except Exception as e:
            self.log(f"Failed to save stats: {e}", 'WARNING')

    def scan_versions_range_and_download(self, start_version: str, end_version: str, test_workers: int = 12):
        start_parts = start_version.split('.')
        end_parts = end_version.split('.')
        start_major = int(start_parts[0])
        start_minor = int(start_parts[1]) if len(start_parts) > 1 else 0
        end_major = int(end_parts[0])
        end_minor = int(end_parts[1]) if len(end_parts) > 1 else 50

        all_versions = self.generate_all_version_numbers(start_major, start_minor, end_major, end_minor)
        self.log(f"Generated {len(all_versions)} candidate versions", 'INFO')

        existing = []
        with ThreadPoolExecutor(max_workers=test_workers) as ex:
            futures = {ex.submit(self.check_version_exists, v): v for v in all_versions}
            for fut in as_completed(futures):
                v = futures[fut]
                try:
                    self.increment_stat('versions_tested')
                    if fut.result():
                        existing.append(v)
                        self.log(f"Found version: {v}", 'FOUND')
                except Exception:
                    pass

        self.log(f"Found {len(existing)} versions in scan", 'SUCCESS')
        # persist
        with self.lock:
            self.found_versions.update(existing)
        self.save_found_versions()

        # download each
        for i, v in enumerate(sorted(existing), 1):
            if self.gui and self.gui.stop_requested:
                self.log("Stop requested; aborting downloads", 'WARNING')
                break
            self.log(f"Processing [{i}/{len(existing)}] {v}", 'INFO')
            self.process_version(v)

        self.save_stats()

    def scan_rss_for_versions(self):
        try:
            r = self.session.get(RSS_URL, timeout=10)
            # simple regex to extract versions like 7.16.2 or 7.16rc1
            vers = set(re.findall(r'RouterOS v?(\d+\.\d+(?:\.\d+)?(?:rc\d+)?(?:beta\d+)?)', r.text))
            new = [v for v in vers if v not in self.found_versions]
            for v in new:
                self.log(f"RSS discovered new version: {v}", 'FOUND')
            return new
        except Exception as e:
            self.log(f"RSS check failed: {e}", 'WARNING')
            return []


class MasterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title('MikroTik Master Scraper')
        self.root.geometry('1000x700')

        self.log_q = queue.Queue()
        self.stats_lock = threading.Lock()
        self.stats = {'versions_tested': 0, 'versions_found': 0, 'files_downloaded': 0, 'files_skipped': 0, 'files_failed': 0, 'bytes_downloaded': 0, 'current_version': ''}
        self.stop_requested = False

        self.setup_ui()

        self.engine = MasterEngine(output_dir=str(Path.cwd() / 'mikrotik_archive'), gui=self)

        self.update_log_loop()
        self.update_stats_loop()

        self.daemon_thread = None
        self.daemon_running = False

    def setup_ui(self):
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill='both', expand=True)

        # Top config
        cfg = ttk.Labelframe(frm, text='Configuration', padding=8)
        cfg.pack(fill='x')

        ttk.Label(cfg, text='Output Directory:').grid(row=0, column=0, sticky='w')
        self.output_var = tk.StringVar(value=str(Path.cwd() / 'mikrotik_archive'))
        ttk.Entry(cfg, textvariable=self.output_var, width=60).grid(row=0, column=1, sticky='w')
        ttk.Button(cfg, text='Browse', command=self.browse_output).grid(row=0, column=2)

        ttk.Label(cfg, text='Start Version:').grid(row=1, column=0, sticky='w')
        self.start_var = tk.StringVar(value='3.30')
        ttk.Entry(cfg, textvariable=self.start_var, width=15).grid(row=1, column=1, sticky='w')
        ttk.Label(cfg, text='End Version:').grid(row=1, column=2, sticky='w')
        self.end_var = tk.StringVar(value='7.50')
        ttk.Entry(cfg, textvariable=self.end_var, width=15).grid(row=1, column=3, sticky='w')

        ttk.Label(cfg, text='Test Workers:').grid(row=2, column=0, sticky='w')
        self.test_workers = tk.IntVar(value=16)
        ttk.Spinbox(cfg, from_=1, to=64, textvariable=self.test_workers, width=8).grid(row=2, column=1, sticky='w')

        ttk.Label(cfg, text='Download Workers:').grid(row=2, column=2, sticky='w')
        self.dl_workers = tk.IntVar(value=8)
        ttk.Spinbox(cfg, from_=1, to=64, textvariable=self.dl_workers, width=8).grid(row=2, column=3, sticky='w')

        ttk.Label(cfg, text='Max Retries:').grid(row=3, column=0, sticky='w')
        self.max_retries = tk.IntVar(value=3)
        ttk.Spinbox(cfg, from_=0, to=10, textvariable=self.max_retries, width=8).grid(row=3, column=1, sticky='w')

        # Control buttons
        btns = ttk.Frame(frm)
        btns.pack(fill='x', pady=6)
        self.start_btn = ttk.Button(btns, text='Start Full Scan', command=self.start_full_scan)
        self.start_btn.pack(side='left', padx=4)
        self.stop_btn = ttk.Button(btns, text='Stop', command=self.request_stop, state='disabled')
        self.stop_btn.pack(side='left', padx=4)

        self.daemon_btn = ttk.Button(btns, text='Start Daemon (RSS)', command=self.toggle_daemon)
        self.daemon_btn.pack(side='left', padx=4)

        ttk.Button(btns, text='Save Log', command=self.save_log).pack(side='right')

        # Log
        log_frame = ttk.Labelframe(frm, text='Log', padding=6)
        log_frame.pack(fill='both', expand=True)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, font=('Courier', 10))
        self.log_text.pack(fill='both', expand=True)

        # Stats
        stats_frame = ttk.Frame(frm)
        stats_frame.pack(fill='x', pady=6)
        self.stat_labels = {}
        keys = [('versions_tested', 'Versions Tested'), ('versions_found', 'Versions Found'), ('files_downloaded', 'Files Downloaded'), ('files_skipped', 'Files Skipped'), ('files_failed', 'Files Failed'), ('data_downloaded', 'Data Downloaded'), ('current_version', 'Current Version')]
        for i, (k, label) in enumerate(keys):
            ttk.Label(stats_frame, text=label+':').grid(row=0, column=2*i, sticky='w')
            lbl = ttk.Label(stats_frame, text='0')
            lbl.grid(row=0, column=2*i+1, sticky='w')
            self.stat_labels[k] = lbl

    def browse_output(self):
        d = filedialog.askdirectory(initialdir=self.output_var.get())
        if d:
            self.output_var.set(d)

    def log(self, message, level='INFO'):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log_q.put((f"[{ts}] {message}", level))

    def update_log_loop(self):
        try:
            while True:
                msg, lvl = self.log_q.get_nowait()
                self.log_text.insert('end', msg + '\n')
                self.log_text.see('end')
        except queue.Empty:
            pass
        self.root.after(200, self.update_log_loop)

    def update_stats_loop(self):
        with self.stats_lock:
            self.stat_labels['versions_tested'].config(text=str(self.stats.get('versions_tested', 0)))
            self.stat_labels['versions_found'].config(text=str(self.stats.get('versions_found', 0)))
            self.stat_labels['files_downloaded'].config(text=str(self.stats.get('files_downloaded', 0)))
            self.stat_labels['files_skipped'].config(text=str(self.stats.get('files_skipped', 0)))
            self.stat_labels['files_failed'].config(text=str(self.stats.get('files_failed', 0)))
            self.stat_labels['data_downloaded'].config(text=f"{self.stats.get('bytes_downloaded',0)/1024/1024/1024:.2f} GB")
            self.stat_labels['current_version'].config(text=self.stats.get('current_version',''))
        self.root.after(500, self.update_stats_loop)

    def save_log(self):
        fn = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text files','*.txt')])
        if fn:
            with open(fn, 'w', encoding='utf-8') as f:
                f.write(self.log_text.get('1.0', 'end'))
            self.log(f"Saved log to {fn}", 'SUCCESS')

    def request_stop(self):
        self.stop_requested = True
        self.stop_btn.config(state='disabled')
        self.log('Stop requested; waiting for tasks to finish', 'WARNING')

    def start_full_scan(self):
        if hasattr(self, 'worker') and self.worker and self.worker.is_alive():
            messagebox.showinfo('Already running', 'A scan is already in progress')
            return

        out = self.output_var.get()
        self.engine = MasterEngine(output_dir=out, download_workers=self.dl_workers.get(), max_retries=self.max_retries.get(), gui=self)
        self.engine.log = self.log
        self.stop_requested = False
        self.stop_btn.config(state='normal')
        self.worker = threading.Thread(target=self._run_scan_thread, daemon=True)
        self.worker.start()

    def _run_scan_thread(self):
        self.log('Starting full scan...', 'INFO')
        try:
            self.engine.scan_versions_range_and_download(self.start_var.get(), self.end_var.get(), test_workers=self.test_workers.get())
        except Exception as e:
            self.log(f'Fatal error during scan: {e}', 'ERROR')
        finally:
            self.log('Scan finished', 'INFO')
            self.stop_btn.config(state='disabled')

    def toggle_daemon(self):
        if self.daemon_running:
            self.daemon_running = False
            self.daemon_btn.config(text='Start Daemon (RSS)')
            self.log('Daemon stop requested', 'WARNING')
        else:
            self.daemon_running = True
            self.daemon_btn.config(text='Stop Daemon (RSS)')
            self.daemon_thread = threading.Thread(target=self._daemon_loop, daemon=True)
            self.daemon_thread.start()

    def _daemon_loop(self):
        self.log('Daemon started: checking RSS every 15 minutes', 'INFO')
        # reuse engine with persistent output
        self.engine = MasterEngine(output_dir=self.output_var.get(), download_workers=self.dl_workers.get(), max_retries=self.max_retries.get(), gui=self)
        while self.daemon_running:
            try:
                new = self.engine.scan_rss_for_versions()
                for v in new:
                    if not self.daemon_running:
                        break
                    self.log(f'Daemon downloading new version {v}', 'INFO')
                    self.engine.process_version(v)
                    self.engine.save_found_versions()
                    self.engine.save_stats()
            except Exception as e:
                self.log(f'Daemon error: {e}', 'ERROR')
            # sleep 15 minutes by default
            for _ in range(15 * 60 // 5):
                if not self.daemon_running:
                    break
                time.sleep(5)


def main():
    root = tk.Tk()
    app = MasterGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
