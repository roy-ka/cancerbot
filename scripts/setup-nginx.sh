#!/bin/bash
# Setup Nginx reverse proxy for CancerBot
# Serves frontend from client/dist and proxies API requests to FastAPI backend
# Run once on the server: sudo ./scripts/setup-nginx.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "Setting up Nginx for CancerBot"
echo "========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "✗ This script must be run as root (use sudo)"
  exit 1
fi

# Install nginx.conf from the repo — the same file scripts/deploy.sh
# refreshes on every deploy — with this checkout's path filled in.
echo ""
echo "Installing nginx configuration..."
NGINX_CONFIG_PATH="/etc/nginx/sites-available/cancerbot"
sed "s#__PROJECT_DIR__#${PROJECT_DIR}#g" "$PROJECT_DIR/nginx.conf" > "$NGINX_CONFIG_PATH"

echo "✓ Nginx configuration created at $NGINX_CONFIG_PATH"

# Enable the site by creating symlink
echo ""
echo "Enabling nginx site..."
SITES_ENABLED="/etc/nginx/sites-enabled/cancerbot"

if [ -L "$SITES_ENABLED" ]; then
  echo "  Site already enabled"
elif [ -e "$SITES_ENABLED" ]; then
  echo "✗ File exists at $SITES_ENABLED but is not a symlink"
  exit 1
else
  ln -s "$NGINX_CONFIG_PATH" "$SITES_ENABLED"
  echo "✓ Site enabled (symlink created)"
fi

# Disable default site if it exists
DEFAULT_SITE="/etc/nginx/sites-enabled/default"
if [ -e "$DEFAULT_SITE" ]; then
  echo ""
  echo "Disabling default nginx site..."
  rm "$DEFAULT_SITE"
  echo "✓ Default site disabled"
fi

# Test nginx configuration
echo ""
echo "Testing nginx configuration..."
if nginx -t; then
  echo "✓ Configuration test passed"
else
  echo "✗ Configuration test failed"
  exit 1
fi

# Reload nginx
echo ""
echo "Reloading nginx..."
if systemctl reload nginx; then
  echo "✓ Nginx reloaded successfully"
else
  echo "✗ Failed to reload nginx"
  exit 1
fi

# Verify nginx is running
echo ""
echo "Verifying nginx is running..."
if systemctl is-active --quiet nginx; then
  echo "✓ Nginx is running"
else
  echo "✗ Nginx is not running"
  exit 1
fi

echo ""
echo "========================================="
echo "✓ Nginx setup completed successfully!"
echo "========================================="
echo "Frontend will be served from: $PROJECT_DIR/client/dist"
echo "API proxy configured for: http://localhost:8000"
echo ""
echo "Next steps:"
echo "1. Run ./scripts/deploy.sh to deploy the application"
echo "2. Visit https://cancer-bot.com to access the app"
echo ""
