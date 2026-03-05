# MikroTik Scraper - CentOS Deployment Guide

## Prerequisites on CentOS Server

### Install Docker (if not already installed)

```bash
# Remove old versions
sudo yum remove docker docker-client docker-client-latest docker-common \
    docker-latest docker-latest-logrotate docker-logrotate docker-engine

# Set up repository
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Install Docker Engine
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Verify
sudo docker --version
```

## Deploy from GitHub

### Option 1: Build on Server (Recommended)

```bash
# Clone the repository
cd /opt  # or your preferred location
git clone https://github.com/g1ftb4sk3t4u/Mikrotik-Master.git
cd Mikrotik-Master

# Build the image
sudo docker build -t mikrotik-scraper:latest .

# Create persistent storage directory
mkdir -p ./mikrotik_archive

# Run the container
sudo docker run -d \
  --name mikrotik-scraper \
  --restart unless-stopped \
  -v $(pwd)/mikrotik_archive:/app/mikrotik_archive \
  mikrotik-scraper:latest
```

### Option 2: Using Docker Compose

```bash
cd /opt/Mikrotik-Master

# Run with compose
sudo docker compose up -d

# View logs
sudo docker compose logs -f

# Stop
sudo docker compose down
```

## Usage Examples

### One-Time Scan (Recent Versions Only)

```bash
sudo docker run --rm \
  -v /data/mikrotik:/app/mikrotik_archive \
  mikrotik-scraper:latest \
  --cli --output /app/mikrotik_archive --start 7.0 --end 7.50 \
  --test-workers 32 --dl-workers 12
```

### Scheduled Scans with Cron

Add to `/etc/crontab`:

```cron
# Run MikroTik scraper daily at 2 AM for new versions
0 2 * * * root docker run --rm -v /data/mikrotik:/app/mikrotik_archive mikrotik-scraper:latest --cli --output /app/mikrotik_archive --start 7.10 --end 7.50 --test-workers 16 --dl-workers 8
```

Or create a systemd timer (more reliable):

**`/etc/systemd/system/mikrotik-scraper.service`**
```ini
[Unit]
Description=MikroTik RouterOS Scraper
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --rm \
  -v /data/mikrotik:/app/mikrotik_archive \
  mikrotik-scraper:latest \
  --cli --output /app/mikrotik_archive --start 7.0 --end 7.50 \
  --test-workers 32 --dl-workers 12

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/mikrotik-scraper.timer`**
```ini
[Unit]
Description=Run MikroTik Scraper Daily
Requires=mikrotik-scraper.service

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Enable timer:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mikrotik-scraper.timer
sudo systemctl status mikrotik-scraper.timer
```

## Performance Tuning for CentOS

### Increase Workers for Faster Scans

```bash
# High-performance scan (requires good network/CPU)
sudo docker run --rm \
  -v /data/mikrotik:/app/mikrotik_archive \
  --cpus="8" --memory="4g" \
  mikrotik-scraper:latest \
  --cli --output /app/mikrotik_archive --start 3.30 --end 7.50 \
  --test-workers 64 --dl-workers 16
```

### Resource Limits

```bash
# Limit container resources
sudo docker run -d \
  --name mikrotik-scraper \
  --restart unless-stopped \
  --cpus="4" \
  --memory="2g" \
  --memory-swap="2g" \
  -v /data/mikrotik:/app/mikrotik_archive \
  mikrotik-scraper:latest
```

## Monitoring

### Check Container Status

```bash
sudo docker ps -a | grep mikrotik
sudo docker logs mikrotik-scraper
sudo docker logs -f mikrotik-scraper  # Follow logs
```

### Check Downloaded Files

```bash
# View found versions
sudo cat /data/mikrotik/mikrotik_archive/found_versions.json | jq '.versions | length'

# View download stats
sudo cat /data/mikrotik/mikrotik_archive/download_stats.json | jq '.stats'

# Disk usage
sudo du -sh /data/mikrotik/mikrotik_archive
```

## Troubleshooting

### Firewall (SELinux/iptables)

If connection issues occur:

```bash
# Check SELinux status
getenforce

# Temporarily disable for testing
sudo setenforce 0

# Check firewall
sudo firewall-cmd --list-all

# Allow outbound HTTP/HTTPS (should be default)
sudo firewall-cmd --zone=public --add-service=http --permanent
sudo firewall-cmd --zone=public --add-service=https --permanent
sudo firewall-cmd --reload
```

### Volume Permissions

If permission errors occur:

```bash
# Fix ownership
sudo chown -R $(id -u):$(id -g) /data/mikrotik/mikrotik_archive

# Or run container as specific user
sudo docker run --user $(id -u):$(id -g) ...
```

### Container Won't Start

```bash
# Check logs
sudo docker logs mikrotik-scraper

# Check if port conflicts (shouldn't be any for this app)
sudo netstat -tulpn | grep docker

# Remove and recreate
sudo docker rm -f mikrotik-scraper
sudo docker run -d --name mikrotik-scraper ...
```

## Updating the Container

```bash
# Pull latest code
cd /opt/Mikrotik-Master
git pull

# Rebuild image
sudo docker build -t mikrotik-scraper:latest .

# Stop old container
sudo docker stop mikrotik-scraper
sudo docker rm mikrotik-scraper

# Start new container (data persists in volume)
sudo docker run -d --name mikrotik-scraper ...
```

## Production Best Practices

1. **Use systemd service** instead of `docker run -d` for better reliability
2. **Set up log rotation** for Docker logs:
   ```bash
   # /etc/docker/daemon.json
   {
     "log-driver": "json-file",
     "log-opts": {
       "max-size": "10m",
       "max-file": "3"
     }
   }
   ```
3. **Monitor disk space** - full archive can be 50-100 GB
4. **Use external volume** mounted from NAS/SAN for large storage
5. **Run scans during off-hours** to avoid network congestion

## Example Production Deployment

```bash
#!/bin/bash
# deploy_mikrotik.sh

REPO_DIR="/opt/Mikrotik-Master"
DATA_DIR="/data/mikrotik"
CONTAINER_NAME="mikrotik-scraper"

# Pull latest code
cd $REPO_DIR
git pull

# Build image
docker build -t mikrotik-scraper:latest .

# Stop old container if running
docker stop $CONTAINER_NAME 2>/dev/null
docker rm $CONTAINER_NAME 2>/dev/null

# Create data directory
mkdir -p $DATA_DIR

# Run container
docker run -d \
  --name $CONTAINER_NAME \
  --restart unless-stopped \
  --cpus="4" \
  --memory="2g" \
  -v $DATA_DIR:/app/mikrotik_archive \
  mikrotik-scraper:latest \
  --cli --output /app/mikrotik_archive \
  --start 7.0 --end 7.50 \
  --test-workers 24 --dl-workers 10

# Show logs
docker logs -f $CONTAINER_NAME
```

Make executable and run:
```bash
sudo chmod +x deploy_mikrotik.sh
sudo ./deploy_mikrotik.sh
```

## Verify Deployment

```bash
# Check container is running
sudo docker ps | grep mikrotik-scraper

# Check logs for progress
sudo docker logs -f mikrotik-scraper | grep "VERSION.*FOUND"

# Wait a few minutes, then check downloads
ls -lh /data/mikrotik/mikrotik_archive/
sudo docker exec mikrotik-scraper ls -lh /app/mikrotik_archive/ | head -20
```

Success indicators:
- Container status: "Up X minutes"
- Logs showing "VERSION X.X.X - FOUND"
- Files appearing in mikrotik_archive/
- found_versions.json and download_stats.json created
