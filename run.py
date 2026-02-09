#!/usr/bin/env python3
"""
MikroTik Master Scraper - CLI Launcher
Run with --help for usage options
"""

import argparse
import sys
from pathlib import Path
from mikrotik_master import MasterEngine, MasterGUI
import tkinter as tk

def cli_mode(args):
    """Run in headless/script mode"""
    print(f"CLI Mode: Scanning {args.start} to {args.end}")
    print(f"Output: {args.output}")
    
    engine = MasterEngine(
        output_dir=args.output,
        download_workers=args.dl_workers,
        max_retries=args.retries
    )
    
    engine.scan_versions_range_and_download(
        start_version=args.start,
        end_version=args.end,
        test_workers=args.test_workers
    )
    
    print("Scan complete")

def gui_mode(args):
    """Run in GUI mode"""
    root = tk.Tk()
    gui = MasterGUI(root)
    if args.output:
        gui.output_var.set(args.output)
    if args.start:
        gui.start_var.set(args.start)
    if args.end:
        gui.end_var.set(args.end)
    root.mainloop()

def main():
    parser = argparse.ArgumentParser(
        description='MikroTik Master Scraper - Download all RouterOS CDN files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # GUI mode (default, interactive)
  python run.py

  # Headless full scan
  python run.py --cli --output ./archive --start 3.30 --end 7.50

  # Quick recent versions only
  python run.py --cli --output ./archive --start 7.0 --end 7.50

  # Custom worker counts for faster scanning
  python run.py --cli --test-workers 32 --dl-workers 12
        """
    )
    
    parser.add_argument('--cli', action='store_true', help='Run in headless CLI mode (default: GUI)')
    parser.add_argument('--output', default='./mikrotik_archive', help='Output directory (default: ./mikrotik_archive)')
    parser.add_argument('--start', default='3.30', help='Start version (default: 3.30)')
    parser.add_argument('--end', default='7.50', help='End version (default: 7.50)')
    parser.add_argument('--test-workers', type=int, default=16, help='Test workers for version scan (default: 16)')
    parser.add_argument('--dl-workers', type=int, default=8, help='Download workers (default: 8)')
    parser.add_argument('--retries', type=int, default=3, help='Max retries per file (default: 3)')
    
    args = parser.parse_args()
    
    if args.cli:
        cli_mode(args)
    else:
        gui_mode(args)

if __name__ == '__main__':
    main()
