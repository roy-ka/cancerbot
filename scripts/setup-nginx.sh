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

# Create nginx config
echo ""
echo "Creating nginx configuration..."
NGINX_CONFIG_PATH="/etc/nginx/sites-available/cancerbot"

cat > "$NGINX_CONFIG_PATH" << 'EOF'
server {
    listen 80;
    server_name _;

    # Serve frontend from build output
    root /home/ubuntu/cancerbot-private/client/dist;
    index index.html;

    # SPA routing: try file, then directory, then fall back to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API endpoints
    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Health check endpoint
    location /health/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
    }

    # WebSocket connections
    location /ws/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Auth endpoints
    location /auth/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Conversations endpoints
    location /conversations/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

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
echo "Frontend will be served from: /home/ubuntu/cancerbot-private/client/dist"
echo "API proxy configured for: http://localhost:8000"
echo ""
echo "Next steps:"
echo "1. Run ./scripts/deploy.sh to deploy the application"
echo "2. Visit http://82.70.211.195 to access the app"
echo ""
