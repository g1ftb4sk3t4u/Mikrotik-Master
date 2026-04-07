# MikroTik Scraper - CentOS Version

This folder contains a **CentOS/headless-safe** variant of the scraper.

It avoids all GUI dependencies (`tkinter`) and runs as pure CLI, which is the most common issue on CentOS servers.

## Files

- `run_centos.py`: command-line entry point
- `mikrotik_centos_scraper.py`: scraping engine
- `requirements.txt`: Python dependencies

## Quick setup on CentOS

```bash
cd /opt
git clone https://github.com/g1ftb4sk3t4u/Mikrotik-Master.git
cd Mikrotik-Master/centos_version

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Run once (range scan)

```bash
python run_centos.py --mode range --output /data/mikrotik_archive --start 7.0 --end 7.50 --test-workers 24 --dl-workers 10
```

## Run as RSS daemon

```bash
python run_centos.py --mode rss --output /data/mikrotik_archive --rss-interval 900
```

## Notes

- Output persists to:
  - `/data/mikrotik_archive/found_versions.json`
  - `/data/mikrotik_archive/download_stats.json`
- If you run under `systemd`, make sure the service has write access to your output directory.

## Minimal systemd service example

Create `/etc/systemd/system/mikrotik-scraper-centos.service`:

```ini
[Unit]
Description=MikroTik Scraper (CentOS CLI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/Mikrotik-Master/centos_version
ExecStart=/opt/Mikrotik-Master/centos_version/.venv/bin/python run_centos.py --mode rss --output /data/mikrotik_archive --rss-interval 900
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mikrotik-scraper-centos.service
sudo systemctl status mikrotik-scraper-centos.service
```
