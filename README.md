# MikroTik CDN Grabber

Mirrors the MikroTik RouterOS CDN (`download.mikrotik.com`) locally: every
architecture's core package, the combined `all_packages` bundle, CHR cloud
images, netinstall tooling, and installer ISOs, for every version it can
find - old and current - plus a daily check for new releases so the archive
stays current on its own.

One codebase, three ways to run it:
- **GUI** - desktop app for interactive use (Windows or Linux desktop)
- **Headless CLI** - `scan` / `watch` subcommands for servers, cron, systemd, Docker
- Runs natively on **Windows** (standalone `.exe` + Task Scheduler) and
  **CentOS** (systemd service + timer), Docker optional on either.

## Why not just guess every version.rc.beta combination?

The CDN has no browsable directory index (`GET` on a bare directory 403s),
and per-version folders 404 if the version doesn't exist. The reliable,
cheap signal is `HEAD .../<version>/CHANGELOG` - every real release has one,
so 200 means "exists", 404 means "doesn't". This tool uses that as the sole
existence probe, and only expands into rc/beta candidates when you pass
`--include-prerelease` - the earlier version of this tool multiplied every
patch into 5 rc + 5 beta variants by default (221 candidates per minor
version, nearly all dead ends). It also queries MikroTik's own lightweight
"what's current" endpoints (the stable/long-term RSS feed and the
`upgrade.mikrotik.com/routeros/LATEST.<channel>` pointer files) first, so
watch checks never need to brute-force anything at all.

## Install

```bash
pip install -r requirements.txt          # headless (CLI: scan/watch)
pip install -r requirements-gui.txt      # + GUI (adds sv_ttk for a modern look)
```

## Usage

```bash
# GUI (default with no subcommand)
python run.py
python run.py gui

# One-time historical crawl
python run.py scan --output ./mikrotik_archive --start 3.30 --end 7.99

# Recent versions only, faster
python run.py scan --output ./mikrotik_archive --start 7.0 --end 7.99

# Single daily-style check for new releases (cron/systemd friendly)
python run.py watch --once --output ./mikrotik_archive

# Or run the watch loop forever, checking every 24h
python run.py watch --interval-hours 24 --output ./mikrotik_archive

# Include release candidates / betas in a scan
python run.py scan --include-prerelease --output ./mikrotik_archive --start 7.15 --end 7.99

# Restrict architectures or file categories
python run.py scan --archs x86,arm64 --categories npk,all_packages,changelog
```

Run `python run.py --help` / `python run.py scan --help` / `python run.py watch --help`
for every flag.

## Deployment

### Windows - standalone .exe + daily scheduled task

```powershell
.\deploy\windows\build_exe.ps1              # -> dist\mikrotik-grabber.exe
.\deploy\windows\install_daily_task.ps1 -ArchiveDir "D:\mikrotik_archive" -Time "03:00"
```

The exe with no arguments opens the GUI; from a terminal, `mikrotik-grabber.exe scan ...`
/ `watch ...` behave exactly like `python run.py ...`. The install script
registers a Task Scheduler job that runs `watch --once` daily so new
releases download automatically without the GUI open.

### CentOS - native systemd service, no Docker required

```bash
sudo ./deploy/centos/install.sh
```

Installs to `/opt/mikrotik-grabber` under a dedicated `mikrotik-grabber`
system user, and enables `mikrotik-grabber-watch.timer` (daily at 03:00,
randomized by up to 15 min). Run the one-time historical backfill by hand
afterwards:

```bash
sudo systemctl start mikrotik-grabber-fullscan.service
sudo journalctl -u mikrotik-grabber-fullscan.service -f
```

### Docker (either OS)

```bash
docker compose run --rm mikrotik-fullscan   # one-time historical crawl
docker compose run --rm mikrotik-watch      # one daily-style check
```

Pair `mikrotik-watch` with a host cron job or systemd timer for daily runs,
or edit its `command:` in `docker-compose.yml` to use `watch --interval-hours 24`
and `restart: unless-stopped` to keep the container running continuously instead.

## Checking files already on disk

Every run checks what's already in the archive before downloading:

- A file the manifest recorded at the same size is trusted as-is.
- Anything else (copied in by hand, or left by an older version of this
  tool) is checked once against the CDN's file size. A short file means an
  interrupted download, so it's fetched again; a matching one is recorded
  in the manifest and never re-checked.
- Archives built by the older `mikrotik_master.py` / `centos_version`
  scrapers are recognized as-is, not downloaded a second time:
  CHANGELOG/ISO/CHR files under `<version>/x86/`, and v7 core packages
  under the v6-style name `routeros-<arch>-<version>.npk` (the CDN serves
  that as an alias of the same file).
- Downloads are written to `<file>.part` and only renamed once complete,
  so a crash, kill, or full disk never leaves a truncated file behind.

`watch` re-checks every currently-advertised release each run, not just
brand-new ones, so a file that failed the night it came out is picked up
the next night.

## Archive layout

```
mikrotik_archive/
├── manifest.json          # discovered versions, downloaded files (size/path), running stats
├── 7.16/
│   ├── x86/
│   │   ├── routeros-7.16.npk         # v7 core package; x86 drops the arch suffix, other archs get routeros-7.16-<arch>.npk
│   │   └── all_packages-x86-7.16.zip
│   ├── arm64/...
│   ├── CHANGELOG
│   └── chr-7.16.img.zip
├── 6.49.20/
│   ├── x86/
│   │   ├── routeros-x86-6.49.20.npk  # v6 branch uses the opposite filename order
│   │   └── all_packages-x86-6.49.20.zip
│   └── ...
└── ...
```

`manifest.json` replaces the old `found_versions.json` + `download_stats.json`
pair, is written atomically (temp file + rename, so a crash mid-write can't
corrupt it), and doubles as the resume/skip-if-already-downloaded record.

Every filename template in `catalog.py` was verified live against the CDN
rather than assumed - MikroTik isn't consistent about naming across major
branches (see the comment at the top of `FILE_CATEGORIES`), and a couple of
categories that turned out not to exist anywhere on the CDN (a per-version
"netinstall-6" variant, a bare CHR "raw" image, a separate `README` file)
were dropped rather than left in to silently 404 forever.

## A note on "devices"

MikroTik doesn't publish separate per-router-model firmware downloads on
this CDN - RouterBOARD firmware ships bundled inside the RouterOS install
packages themselves (that's how the core npk package covers every device
using that architecture). There's no separate device tree to crawl.

## Disk space

A full historical crawl across all architectures/categories is easily
500GB-1TB+ (roughly 300 real historical versions × up to 8 architectures ×
several formats each, including multiple CHR virtual-disk variants).
Narrow `--start`/`--end`, `--archs`, or `--categories` if you only need
recent x86/arm64 builds, for example.

## License

MIT
