#!/bin/bash
# Run ONCE on a fresh Ubuntu 24.04 VPS, as root:  bash bootstrap.sh
# Updates the system, installs Docker if the template did not, closes every port except SSH, HTTP and HTTPS, and keeps the system patched.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -y && apt-get upgrade -y
apt-get install -y ca-certificates curl ufw unattended-upgrades fail2ban rsync

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# firewall: Docker publishes only 80 and 443 (and 6080 on 127.0.0.1); SSH stays open
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades || true

mkdir -p /opt/myt-mcp
echo "ready: copy the project to /opt/myt-mcp (docs/Deploy_VPS.md, step 5)"
