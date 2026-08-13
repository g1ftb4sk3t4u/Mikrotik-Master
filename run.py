#!/usr/bin/env python3
"""Entry point. `python run.py --help` for all subcommands.

Examples:
  python run.py                                   # launch GUI
  python run.py gui
  python run.py scan --output ./mikrotik_archive --start 3.30 --end 7.99
  python run.py watch --once                       # single daily-style check, good for cron/systemd
  python run.py watch --interval-hours 24           # run forever, checking daily
"""

from mikrotik_grabber.cli import main

if __name__ == "__main__":
    main()
