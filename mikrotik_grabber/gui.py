"""Desktop GUI. Thin shell around Engine: the engine runs in a background
thread and pushes events onto a queue; this module only ever touches
tkinter widgets from the main thread via root.after polling.
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from .catalog import ARCHITECTURES, DEFAULT_CATEGORIES
from .engine import Engine

LOG_COLORS = {
    "INFO": "#9aa5b1",
    "SUCCESS": "#3fb950",
    "FOUND": "#58a6ff",
    "WARNING": "#d29922",
    "ERROR": "#f85149",
}


def _apply_modern_theme(root: tk.Tk):
    """Best-effort sleek theme. Falls back cleanly if sv_ttk isn't installed
    (it's an optional dependency; the tool must still run without it)."""
    try:
        import sv_ttk
        sv_ttk.set_theme("dark")
        return
    except ImportError:
        pass
    style = ttk.Style(root)
    for candidate in ("vista", "clam"):
        if candidate in style.theme_names():
            style.theme_use(candidate)
            break


class GrabberGUI:
    def __init__(self, root: tk.Tk, initial_output: str = None):
        self.root = root
        self.root.title("MikroTik CDN Grabber")
        self.root.geometry("1080x760")
        self.root.minsize(860, 600)

        _apply_modern_theme(root)

        self.event_q = queue.Queue()
        self.stats = {
            "versions_found": 0,
            "files_downloaded": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "bytes_downloaded": 0,
        }
        self.worker_thread = None
        self.stop_event = threading.Event()

        self._build_ui(initial_output)
        self._poll_events()

    # -- UI construction -------------------------------------------------
    def _build_ui(self, initial_output):
        root = self.root
        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="MikroTik CDN Grabber", font=("Segoe UI", 16, "bold")).pack(side="left")
        self.mode_label = ttk.Label(header, text="Idle", foreground="#9aa5b1")
        self.mode_label.pack(side="right")

        cfg = ttk.LabelFrame(outer, text="Configuration", padding=10)
        cfg.pack(fill="x")
        for col in range(6):
            cfg.columnconfigure(col, weight=1)

        ttk.Label(cfg, text="Output directory").grid(row=0, column=0, sticky="w")
        self.output_var = tk.StringVar(value=initial_output or str(Path.cwd() / "mikrotik_archive"))
        ttk.Entry(cfg, textvariable=self.output_var).grid(row=0, column=1, columnspan=4, sticky="ew", padx=6)
        ttk.Button(cfg, text="Browse...", command=self._browse_output).grid(row=0, column=5, sticky="ew")

        ttk.Label(cfg, text="Start version").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.start_var = tk.StringVar(value="3.30")
        ttk.Entry(cfg, textvariable=self.start_var, width=12).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(cfg, text="End version").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.end_var = tk.StringVar(value="7.99")
        ttk.Entry(cfg, textvariable=self.end_var, width=12).grid(row=1, column=3, sticky="w", pady=(8, 0))

        self.prerelease_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfg, text="Include rc/beta", variable=self.prerelease_var).grid(row=1, column=4, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(cfg, text="Test workers").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.test_workers_var = tk.IntVar(value=16)
        ttk.Spinbox(cfg, from_=1, to=64, textvariable=self.test_workers_var, width=8).grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Label(cfg, text="Download workers").grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.dl_workers_var = tk.IntVar(value=8)
        ttk.Spinbox(cfg, from_=1, to=64, textvariable=self.dl_workers_var, width=8).grid(row=2, column=3, sticky="w", pady=(8, 0))

        ttk.Label(cfg, text="Max retries").grid(row=2, column=4, sticky="w", pady=(8, 0))
        self.retries_var = tk.IntVar(value=3)
        ttk.Spinbox(cfg, from_=0, to=10, textvariable=self.retries_var, width=8).grid(row=2, column=5, sticky="w", pady=(8, 0))

        ttk.Label(cfg, text="Architectures").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.archs_var = tk.StringVar(value=",".join(ARCHITECTURES))
        ttk.Entry(cfg, textvariable=self.archs_var).grid(row=3, column=1, columnspan=5, sticky="ew", pady=(8, 0))

        ttk.Label(cfg, text="Watch interval (hours)").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.interval_var = tk.DoubleVar(value=24.0)
        ttk.Spinbox(cfg, from_=1, to=168, textvariable=self.interval_var, width=8).grid(row=4, column=1, sticky="w", pady=(8, 0))

        # Controls
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=10)
        self.scan_btn = ttk.Button(controls, text="Start Full Scan", command=self._start_full_scan)
        self.scan_btn.pack(side="left", padx=(0, 6))
        self.watch_btn = ttk.Button(controls, text="Start Daily Watch", command=self._start_watch)
        self.watch_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(controls, text="Stop", command=self._request_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        ttk.Button(controls, text="Save Log", command=self._save_log).pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 10))

        # Stats
        stats_frame = ttk.LabelFrame(outer, text="Stats", padding=8)
        stats_frame.pack(fill="x")
        self.stat_labels = {}
        cols = [
            ("versions_found", "Versions found"),
            ("files_downloaded", "Files downloaded"),
            ("files_skipped", "Files skipped"),
            ("files_failed", "Files failed"),
            ("bytes_downloaded", "Data downloaded"),
        ]
        for i, (key, label) in enumerate(cols):
            ttk.Label(stats_frame, text=label + ":").grid(row=0, column=2 * i, sticky="w", padx=(0 if i == 0 else 14, 4))
            val = ttk.Label(stats_frame, text="0", font=("Segoe UI", 10, "bold"))
            val.grid(row=0, column=2 * i + 1, sticky="w")
            self.stat_labels[key] = val

        # Log
        log_frame = ttk.LabelFrame(outer, text="Log", padding=6)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = scrolledtext.ScrolledText(log_frame, font=("Cascadia Mono", 10), bg="#0d1117", fg="#c9d1d9", insertbackground="#c9d1d9")
        self.log_text.pack(fill="both", expand=True)
        for level, color in LOG_COLORS.items():
            self.log_text.tag_configure(level, foreground=color)

    # -- helpers -----------------------------------------------------------
    def _browse_output(self):
        d = filedialog.askdirectory(initialdir=self.output_var.get() or ".")
        if d:
            self.output_var.set(d)

    def _save_log(self):
        fn = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if fn:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(self.log_text.get("1.0", "end"))

    def _append_log(self, message: str, level: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] ", "INFO")
        self.log_text.insert("end", f"{message}\n", level)
        self.log_text.see("end")

    def _running(self) -> bool:
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def _current_archs(self):
        raw = [a.strip() for a in self.archs_var.get().split(",") if a.strip()]
        return raw or ARCHITECTURES

    def _make_engine(self) -> Engine:
        return Engine(
            output_dir=self.output_var.get(),
            download_workers=self.dl_workers_var.get(),
            test_workers=self.test_workers_var.get(),
            max_retries=self.retries_var.get(),
            architectures=self._current_archs(),
            categories=DEFAULT_CATEGORIES,
            include_prerelease=self.prerelease_var.get(),
            on_event=self.event_q.put,
            stop_flag=self.stop_event.is_set,
        )

    # -- actions -------------------------------------------------------
    def _start_full_scan(self):
        if self._running():
            messagebox.showinfo("Busy", "A scan or watch is already running.")
            return
        self.stop_event.clear()
        engine = self._make_engine()
        self._set_running_ui("Full scan running...")

        def run():
            try:
                engine.full_scan(self.start_var.get(), self.end_var.get())
            except Exception as e:
                self.event_q.put({"type": "log", "level": "ERROR", "message": f"Fatal error: {e}"})
            finally:
                self.event_q.put({"type": "done"})

        self.worker_thread = threading.Thread(target=run, daemon=True)
        self.worker_thread.start()

    def _start_watch(self):
        if self._running():
            messagebox.showinfo("Busy", "A scan or watch is already running.")
            return
        self.stop_event.clear()
        engine = self._make_engine()
        self._set_running_ui("Daily watch running...")

        def run():
            try:
                engine.watch_loop(interval_hours=self.interval_var.get())
            except Exception as e:
                self.event_q.put({"type": "log", "level": "ERROR", "message": f"Fatal error: {e}"})
            finally:
                self.event_q.put({"type": "done"})

        self.worker_thread = threading.Thread(target=run, daemon=True)
        self.worker_thread.start()

    def _request_stop(self):
        self.stop_event.set()
        self.stop_btn.config(state="disabled")
        self.event_q.put({"type": "log", "level": "WARNING", "message": "Stop requested; finishing in-flight work..."})

    def _set_running_ui(self, mode_text: str):
        self.mode_label.config(text=mode_text)
        self.scan_btn.config(state="disabled")
        self.watch_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def _set_idle_ui(self):
        self.mode_label.config(text="Idle")
        self.scan_btn.config(state="normal")
        self.watch_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress["value"] = 0

    # -- event pump ------------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                evt = self.event_q.get_nowait()
                self._handle_event(evt)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _handle_event(self, evt: dict):
        kind = evt["type"]
        if kind == "log":
            self._append_log(evt["message"], evt.get("level", "INFO"))
        elif kind == "stat":
            self.stats[evt["key"]] = self.stats.get(evt["key"], 0) + evt["amount"]
            self._refresh_stats()
        elif kind == "progress":
            total = evt.get("total", 0)
            if total:
                self.progress["maximum"] = total
                self.progress["value"] = evt.get("done", 0)
        elif kind == "done":
            self._set_idle_ui()

    def _refresh_stats(self):
        for key, label in self.stat_labels.items():
            if key == "bytes_downloaded":
                gb = self.stats.get(key, 0) / (1024 ** 3)
                label.config(text=f"{gb:.2f} GB")
            else:
                label.config(text=str(self.stats.get(key, 0)))


def launch_gui(initial_output: str = None):
    root = tk.Tk()
    GrabberGUI(root, initial_output=initial_output)
    root.mainloop()
