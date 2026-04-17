#!/usr/bin/env bash
set -euo pipefail

echo "=== Shadow Pages Server Setup ==="

# Update system
apt-get update && apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh

# Install Docker Compose (v2 plugin)
apt-get install -y docker-compose-plugin

# Install certbot
apt-get install -y certbot

# Create deploy user
if ! id "deploy" &>/dev/null; then
    useradd -m -s /bin/bash -G docker deploy
fi
mkdir -p /home/deploy/.ssh
echo "# Add your SSH public key here" >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

# Create project directory
mkdir -p /opt/shadowpages
chown deploy:deploy /opt/shadowpages

# Firewall
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Swap (for small servers)
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo ""
echo "=== Setup complete ==="
echo "1. Add your SSH public key to /home/deploy/.ssh/authorized_keys"
echo "2. Clone your repo to /opt/shadowpages as the deploy user"
echo "3. Copy .env.production.template to .env and fill in secrets"
echo "4. Run: sudo bash infra/init-ssl.sh yourdomain.com"
echo "5. Run: bash infra/deploy.sh"
