# MikroTik Master Scraper

Complete MikroTik RouterOS CDN scraper with GUI, daemon mode, and full automation.

## Features

- **Full CDN Crawl**: Discovers and downloads all RouterOS versions from the MikroTik CDN (3.30 to current)
- **Multi-Architecture Support**: Downloads for arm, arm64, mipsbe, mmips, ppc, smips, tile, x86
- **GUI Mode**: Beautiful tkinter interface with live progress, stats, and logging
- **CLI/Daemon Mode**: Can be run as a background daemon for continuous updates
- **RSS Polling**: Automatically checks MikroTik RSS feed for new releases every 15 minutes
- **Persistence**: Saves found versions and stats to JSON for resume and tracking
- **Retry Logic**: Exponential backoff retry on download failures
- **Thread-Safe**: Concurrent version checking and downloads with configurable workers

## Installation

### Docker (Recommended for production/scheduled scans)

See [DOCKER_README.md](DOCKER_README.md) for full Docker documentation.

**Quick start:**
```bash
# Build and run
docker-compose up

# Or with Docker directly
docker build -t mikrotik-scraper .
docker run -v $(pwd)/mikrotik_archive:/app/mikrotik_archive mikrotik-scraper
```

### Local Python Installation

#### Requirements
- Python 3.8+
- `requests` library

### Setup

```bash
pip install -r requirements.txt
```

## Usage

### GUI Mode (Recommended for interactive use)

```bash
python mikrotik_master.py
```

This launches the GUI where you can:
- Set output directory and version range (default: 3.30 to 7.50)
- Configure worker threads for parallel downloads
- Start a full scan to discover and download all versions
- Toggle RSS daemon mode to auto-download new releases
- View real-time logs and download statistics
- Save logs to file

### Headless/Script Mode

For automation without GUI, create a script:

```python
from mikrotik_master import MasterEngine

# Initialize engine
engine = MasterEngine(
    output_dir='/path/to/archive',
    download_workers=8,
    max_retries=3
)

# Full scan and download
engine.scan_versions_range_and_download(
    start_version='3.30',
    end_version='7.50',
    test_workers=16
)
```

Or check for RSS updates only:

```python
new_versions = engine.scan_rss_for_versions()
for v in new_versions:
    engine.process_version(v)
    engine.save_found_versions()
```

## Architecture

### MasterEngine
Core scraper engine handling:
- Version number generation (major.minor.patch combinations)
- CDN availability checks (HEAD requests)
- Parallel file downloads with retry logic
- Persistence (JSON: `found_versions.json`, `download_stats.json`)

### MasterGUI
Tkinter interface providing:
- Configuration panel (output dir, version range, worker counts)
- Live statistics display
- Colored log viewer
- RSS daemon toggle
- Stop/pause capability

### Daemon Mode
Runs continuously checking RSS feed and downloading new versions:
- Polls RSS every 15 minutes (configurable)
- Downloads new versions automatically
- Persists found versions and stats
- Runs independently from GUI (can leave running)

## File Organization

Downloaded files are organized as:
```
mikrotik_archive/
├── 7.10/
│   ├── arm/
│   │   ├── routeros-arm-7.10.npk
│   │   ├── all_packages-arm-7.10.zip
│   │   └── ...
│   ├── arm64/
│   ├── x86/
│   └── CHANGELOG, README (in version root)
├── 7.11/
├── found_versions.json
├── download_stats.json
└── ...
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| Output Directory | `./mikrotik_archive` | Where files are saved |
| Start Version | 3.30 | Earliest version to scan |
| End Version | 7.50 | Latest version to scan |
| Test Workers | 16 | Threads for version checking |
| Download Workers | 8 | Threads for file downloads |
| Max Retries | 3 | Retry attempts per failed file |

## Performance Tips

- **Test Workers**: Increase to 20-32 for faster initial scan (discovers all versions)
- **Download Workers**: Keep at 8-12 to avoid overwhelming the server
- **Version Range**: Narrow the range if you only need recent versions (e.g., 7.0 to 7.50)

## Output

- **Logs**: Real-time display in GUI or console; saveable to `.txt`
- **Persistence**: 
  - `found_versions.json`: All discovered versions
  - `download_stats.json`: Download count, skipped, failed, bytes
- **Downloaded Files**: Organized by version and architecture

## Examples

### Download only recent versions (faster)
Set Start Version: `7.0`, End Version: `7.50`

### Run daemon indefinitely
Start GUI, toggle "Start Daemon (RSS)", leave window open

### Scripted full crawl with progress
```python
from mikrotik_master import MasterEngine, MasterGUI
import tkinter as tk

root = tk.Tk()
gui = MasterGUI(root)
# GUI handles threading and updates automatically
root.mainloop()
```

## Troubleshooting

**No versions found**: Check network access to `https://download.mikrotik.com/routeros`

**Slow downloads**: Reduce `Download Workers` if getting connection resets; increase `Test Workers` if version scan is slow

**Daemon not finding new versions**: Ensure RSS URL is accessible and version format matches regex in `scan_rss_for_versions()`

**Out of disk space**: Downloads can be 100GB+; check available space before starting large scans

## License

MIT

## Author

Generated by Claude (merged from two earlier implementations)
