# MikroTik Scraper - Docker Deployment Guide

## Quick Start

### 1. Build the Image

```bash
docker build -t mikrotik-scraper .
```

### 2. Run One-Time Full Scan

Scan and download all versions from 3.30 to 7.50:

```bash
docker run -v $(pwd)/mikrotik_archive:/app/mikrotik_archive mikrotik-scraper
```

### 3. Run with Custom Range

Download only recent versions (7.0 to 7.50):

```bash
docker run -v $(pwd)/mikrotik_archive:/app/mikrotik_archive \
  mikrotik-scraper \
  --cli --output /app/mikrotik_archive --start 7.0 --end 7.50 --test-workers 32 --dl-workers 12
```

### 4. Use Docker Compose

```bash
# Run full scan
docker-compose up

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Configuration

### Environment Variables

Set in `docker-compose.yml` or via `-e` flags:

- `START_VERSION` - Starting version to scan (default: 3.30)
- `END_VERSION` - Ending version to scan (default: 7.50)
- `TEST_WORKERS` - Parallel workers for version checking (default: 16)
- `DL_WORKERS` - Parallel download workers (default: 8)
- `MAX_RETRIES` - Retry attempts per file (default: 3)

### Command Line Arguments

Override in `docker-compose.yml` or pass to `docker run`:

```bash
--cli                 # Run in headless CLI mode (required for Docker)
--output DIR          # Output directory (default: /app/mikrotik_archive)
--start VERSION       # Start version (e.g., 3.30)
--end VERSION         # End version (e.g., 7.50)
--test-workers N      # Version scan workers (higher = faster discovery)
--dl-workers N        # Download workers (higher = faster downloads)
--retries N           # Max retries per file
```

## Usage Examples

### Example 1: Quick Scan of Latest Versions

```bash
docker run -v $(pwd)/downloads:/app/mikrotik_archive \
  mikrotik-scraper \
  --cli --output /app/mikrotik_archive --start 7.10 --end 7.50 --test-workers 32 --dl-workers 12
```

### Example 2: Full Historical Archive

```bash
docker run -v $(pwd)/full_archive:/app/mikrotik_archive \
  mikrotik-scraper \
  --cli --output /app/mikrotik_archive --start 3.30 --end 7.50 --test-workers 16 --dl-workers 8
```

### Example 3: High-Speed Scan (More Workers)

```bash
docker run -v $(pwd)/mikrotik_archive:/app/mikrotik_archive \
  mikrotik-scraper \
  --cli --output /app/mikrotik_archive --start 6.0 --end 7.50 --test-workers 64 --dl-workers 16
```

## Persistent Data

The container saves two important files in the output directory:

1. **`found_versions.json`** - List of all discovered versions (for resuming)
2. **`download_stats.json`** - Download statistics and progress

These files persist across container restarts when using volume mounts.

## File Structure

Downloaded files are organized by version and architecture:

```
mikrotik_archive/
├── found_versions.json
├── download_stats.json
├── 7.16.2/
│   ├── arm/
│   │   ├── routeros-arm-7.16.2.npk
│   │   ├── all_packages-arm-7.16.2.zip
│   │   └── ...
│   ├── arm64/
│   ├── x86/
│   └── ...
├── 7.16.1/
└── ...
```

## Performance Considerations

- **Test Workers** (`--test-workers`): Higher values speed up version discovery but may hit rate limits. Recommended: 16-32.
- **Download Workers** (`--dl-workers`): Higher values speed up downloads. Recommended: 8-16.
- **Network**: MikroTik CDN is fast; bottleneck is usually disk I/O.
- **Storage**: Full archive (3.30 to latest) requires ~50-100 GB.

## Troubleshooting

### Container exits immediately

Check logs:
```bash
docker logs mikrotik-scraper
```

### Downloads are slow

Increase workers:
```bash
docker run -v $(pwd)/mikrotik_archive:/app/mikrotik_archive \
  mikrotik-scraper \
  --cli --output /app/mikrotik_archive --start 7.0 --end 7.50 \
  --test-workers 32 --dl-workers 16
```

### Resume interrupted scan

The scraper automatically skips existing files. Just restart with same output directory:
```bash
docker-compose up
```

## Advanced: Daemon Mode (Continuous Polling)

To continuously monitor for new versions (checks RSS every 15 min), you'll need to modify the code or run in a loop. Current Docker setup is optimized for one-time scans.

For continuous operation, consider:
1. Running the container with a restart policy
2. External scheduler (cron) to run daily/weekly
3. Modify `run.py` to accept `--daemon` flag and implement RSS polling loop

## Building and Pushing to Registry

```bash
# Build
docker build -t your-registry/mikrotik-scraper:latest .

# Push
docker push your-registry/mikrotik-scraper:latest

# Pull and run on another machine
docker pull your-registry/mikrotik-scraper:latest
docker run -v /data/mikrotik:/app/mikrotik_archive your-registry/mikrotik-scraper:latest
```

## Notes

- The scraper respects existing files (won't re-download)
- Partial downloads are cleaned up on failure
- 404 errors are normal (not all architectures exist for all versions)
- CHANGELOG and README files are downloaded per version

## License

Refer to main repository README for license information.
