#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu 22.04/24.04 server (safe to re-run).
# Installs Docker and Tailscale, a 2 GB swap file and a firewall that only lets
# SSH in. Run as the default user (it uses sudo): bash infra/server/setup.sh
set -euo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

say "System updates"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git ufw unattended-upgrades

if ! command -v docker >/dev/null; then
  say "Docker (official install script)"
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

if ! command -v tailscale >/dev/null; then
  say "Tailscale (official install script)"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

if ! swapon --show | grep -q /swapfile; then
  say "2 GB swap file (keeps the web build from running out of memory)"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

say "Firewall: only SSH in"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw --force enable

say "Automatic security updates"
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

say "Done. Log out and back in (exit, then ssh again) so the docker group applies."
echo "Next: sudo tailscale up   (docs/SERVER.md, step 4)"
