#!/usr/bin/env python3
"""CLI launcher for the CentOS MikroTik scraper variant."""

import argparse

from mikrotik_centos_scraper import CentOSEngine


def main():
    parser = argparse.ArgumentParser(
        description="MikroTik scraper (CentOS/headless variant)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_centos.py --mode range --output ./mikrotik_archive --start 7.0 --end 7.50
  python run_centos.py --mode rss --output ./mikrotik_archive --rss-interval 900
        """,
    )

    parser.add_argument("--mode", choices=["range", "rss"], default="range", help="range: scan version range, rss: poll RSS forever")
    parser.add_argument("--output", default="./mikrotik_archive", help="Output directory")
    parser.add_argument("--start", default="3.30", help="Start version for range mode")
    parser.add_argument("--end", default="7.50", help="End version for range mode")
    parser.add_argument("--test-workers", type=int, default=16, help="Workers for version existence checks")
    parser.add_argument("--dl-workers", type=int, default=8, help="Workers for file downloads")
    parser.add_argument("--retries", type=int, default=3, help="Retry attempts per file")
    parser.add_argument("--rss-interval", type=int, default=900, help="Seconds between RSS polls in rss mode")

    args = parser.parse_args()

    engine = CentOSEngine(
        output_dir=args.output,
        download_workers=args.dl_workers,
        max_retries=args.retries,
    )

    if args.mode == "rss":
        engine.poll_rss_forever(interval_seconds=args.rss_interval)
    else:
        engine.scan_range_and_download(
            start_version=args.start,
            end_version=args.end,
            test_workers=args.test_workers,
        )


if __name__ == "__main__":
    main()
