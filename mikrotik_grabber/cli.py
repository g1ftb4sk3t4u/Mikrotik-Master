"""Headless CLI. `mikrotik-grabber gui` launches the desktop UI; every other
subcommand is fully headless and safe to run under systemd / Task Scheduler /
Docker with no display available.
"""

from __future__ import annotations

import argparse
import sys

from .catalog import ARCHITECTURES, DEFAULT_CATEGORIES
from .engine import Engine


def _console_event_handler(verbose: bool):
    def handler(evt):
        if evt["type"] == "log":
            if evt["level"] == "INFO" and not verbose:
                return
            print(f"[{evt['level']}] {evt['message']}", flush=True)
        elif evt["type"] == "progress" and verbose:
            print(f"[SCAN] {evt['done']}/{evt['total']}", flush=True)
    return handler


def _build_engine(args) -> Engine:
    archs = args.archs.split(",") if args.archs else ARCHITECTURES
    cats = args.categories.split(",") if args.categories else DEFAULT_CATEGORIES
    return Engine(
        output_dir=args.output,
        download_workers=args.dl_workers,
        test_workers=args.test_workers,
        max_retries=args.retries,
        architectures=archs,
        categories=cats,
        include_prerelease=args.include_prerelease,
        on_event=_console_event_handler(args.verbose),
    )


def cmd_scan(args):
    engine = _build_engine(args)
    engine.full_scan(args.start, args.end)
    print("Scan complete.")


def cmd_watch(args):
    engine = _build_engine(args)
    if args.once:
        new = engine.watch_once()
        print(f"Watch check complete. {len(new)} new version(s).")
    else:
        try:
            engine.watch_loop(interval_hours=args.interval_hours)
        except KeyboardInterrupt:
            print("Stopped.")


def cmd_gui(args):
    # Imported lazily: tkinter isn't available/needed in headless deployments
    # (e.g. a slim CentOS container), so importing it eagerly would break
    # `--help` and every other subcommand on those hosts.
    from .gui import launch_gui
    launch_gui(initial_output=args.output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mikrotik-grabber",
        description="Crawl the MikroTik RouterOS CDN and mirror firmware/packages locally.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output", default="./mikrotik_archive", help="Archive output directory")
    common.add_argument("--dl-workers", type=int, default=8, help="Concurrent download workers")
    common.add_argument("--test-workers", type=int, default=16, help="Concurrent version-probe workers")
    common.add_argument("--retries", type=int, default=3, help="Max retries per file")
    common.add_argument("--archs", default=None, help=f"Comma-separated architectures (default: {','.join(ARCHITECTURES)})")
    common.add_argument("--categories", default=None, help=f"Comma-separated file categories (default: all: {','.join(DEFAULT_CATEGORIES)})")
    common.add_argument("--include-prerelease", action="store_true", help="Also probe rc/beta releases during a scan")
    common.add_argument("-v", "--verbose", action="store_true", help="Show INFO-level logs, not just findings/errors")

    sub = parser.add_subparsers(dest="command")

    p_scan = sub.add_parser("scan", parents=[common], help="One-time full crawl of a version range")
    p_scan.add_argument("--start", default="3.30", help="Earliest version to probe")
    p_scan.add_argument("--end", default="7.99", help="Latest version to probe")
    p_scan.set_defaults(func=cmd_scan)

    p_watch = sub.add_parser("watch", parents=[common], help="Daily-style check for new releases (RSS + channel pointers)")
    p_watch.add_argument("--interval-hours", type=float, default=24.0, help="Hours between checks (default: 24, i.e. daily)")
    p_watch.add_argument("--once", action="store_true", help="Run a single check-and-download pass then exit (good for cron/systemd timers)")
    p_watch.set_defaults(func=cmd_watch)

    p_gui = sub.add_parser("gui", parents=[common], help="Launch the desktop GUI")
    p_gui.set_defaults(func=cmd_gui)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        # No subcommand: behave like a double-clicked desktop app.
        from .gui import launch_gui
        launch_gui()
        return
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
