#!/bin/bash
# Setup systemd service to automatically fix iptables rules after Docker starts
# Run this once on the server: sudo ./scripts/setup-iptables-service.sh

set -euo pipefail

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "✗ Error: This script must be run as root (use: sudo ./scripts/setup-iptables-service.sh)"
  exit 1
fi

echo "Setting up iptables-docker systemd service..."

# Get the absolute path to the fix-iptables.sh script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIX_IPTABLES_SCRIPT="$SCRIPT_DIR/fix-iptables.sh"

# Verify fix-iptables.sh exists and is executable
if [ ! -x "$FIX_IPTABLES_SCRIPT" ]; then
  echo "✗ Error: $FIX_IPTABLES_SCRIPT not found or not executable"
  exit 1
fi

# Create systemd service file
SERVICE_FILE="/etc/systemd/system/iptables-docker.service"

cat > "$SERVICE_FILE" << 'EOF'
[Unit]
Description=Fix iptables for Docker host access
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=SCRIPT_PATH
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Replace SCRIPT_PATH with actual path
sed -i "s|SCRIPT_PATH|$FIX_IPTABLES_SCRIPT|g" "$SERVICE_FILE"

echo "✓ Created $SERVICE_FILE"

# Reload systemd daemon
systemctl daemon-reload
echo "✓ Reloaded systemd daemon"

# Enable service to run on boot
systemctl enable iptables-docker.service
echo "✓ Enabled iptables-docker service"

# Start the service now
systemctl start iptables-docker.service
echo "✓ Started iptables-docker service"

# Verify service is running
if systemctl is-active --quiet iptables-docker.service; then
  echo ""
  echo "========================================="
  echo "✓ Setup complete!"
  echo "========================================="
  echo "The iptables-docker service is now:"
  echo "  • Running and applied iptables rules"
  echo "  • Enabled to run automatically after Docker starts on every boot"
  echo ""
  echo "To verify the service status:"
  echo "  systemctl status iptables-docker.service"
  echo ""
  echo "To view the service log:"
  echo "  journalctl -u iptables-docker.service -n 20"
else
  echo "⚠ Warning: Service may not have started successfully"
  echo "Check status: systemctl status iptables-docker.service"
fi
