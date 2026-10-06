#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu VM (Oracle Cloud Always Free etc.).
# Run as the default user: bash deploy/vm/setup.sh
set -euo pipefail
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git
# Docker (official convenience script)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# 2 GB swap: the 1 GB free VMs need it for the road-network graph
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
# Oracle's Ubuntu images block ports with iptables even after the cloud
# firewall allows them — open 80/443 locally too.
if command -v iptables >/dev/null; then
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || true
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT || true
  sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save || true
fi
echo "Done. Log out and back in (so the docker group applies), then continue."
