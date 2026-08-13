#!/usr/bin/env bash
# Native CentOS install: no Docker required. Sets up a dedicated user, a venv
# under /opt/mikrotik-grabber, and a systemd timer that runs a headless daily
# check for new RouterOS releases. Run the historical backfill once by hand
# afterwards (see the printed instructions at the end).
#
# Usage: sudo ./install.sh [/path/to/repo/checkout]

set -euo pipefail

REPO_SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
INSTALL_DIR="/opt/mikrotik-grabber"
ARCHIVE_DIR="/data/mikrotik_archive"
SERVICE_USER="mikrotik-grabber"

if [[ $EUID -ne 0 ]]; then
    echo "Run as root (sudo ./install.sh)" >&2
    exit 1
fi

echo "==> Installing system packages"
if command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip python3-virtualenv
else
    yum install -y python3 python3-pip python3-virtualenv
fi

echo "==> Creating service user"
id -u "$SERVICE_USER" &>/dev/null || useradd --system --home-dir "$INSTALL_DIR" --shell /sbin/nologin "$SERVICE_USER"

echo "==> Syncing application code to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude='.git' --exclude='mikrotik_archive' --exclude='venv' --exclude='.venv' --exclude='__pycache__' \
    "$REPO_SRC/" "$INSTALL_DIR/"

echo "==> Creating archive directory: $ARCHIVE_DIR"
mkdir -p "$ARCHIVE_DIR"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$ARCHIVE_DIR" "$INSTALL_DIR"

echo "==> Creating virtualenv"
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "==> Installing systemd units"
cp "$INSTALL_DIR/deploy/centos/mikrotik-grabber-watch.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/centos/mikrotik-grabber-watch.timer" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/centos/mikrotik-grabber-fullscan.service" /etc/systemd/system/
sed -i "s#/data/mikrotik_archive#${ARCHIVE_DIR}#g" /etc/systemd/system/mikrotik-grabber-watch.service /etc/systemd/system/mikrotik-grabber-fullscan.service

systemctl daemon-reload
systemctl enable --now mikrotik-grabber-watch.timer

echo "==> Allowing outbound HTTPS through firewalld (if active)"
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    firewall-cmd --zone=public --add-service=https --permanent
    firewall-cmd --reload
fi

cat <<EOF

Done.

Daily watch timer installed and enabled:
  systemctl status mikrotik-grabber-watch.timer
  systemctl list-timers mikrotik-grabber-watch.timer

Run the one-time historical backfill (can take a long time, ~tens of GB):
  systemctl start mikrotik-grabber-fullscan.service
  journalctl -u mikrotik-grabber-fullscan.service -f

Trigger a watch check manually:
  systemctl start mikrotik-grabber-watch.service
  journalctl -u mikrotik-grabber-watch.service -f

Archive lives at: $ARCHIVE_DIR
EOF
