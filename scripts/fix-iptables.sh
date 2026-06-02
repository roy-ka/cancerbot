#!/bin/bash
# Fix iptables rules for Docker container-to-host connectivity
# Allows Docker containers to reach the host (e.g., Ollama running on host)
# Handles dynamic bridge IDs by flushing old rules and re-applying current ones
# Called by iptables-docker.service after Docker starts or during deploy

set -euo pipefail

echo "Applying iptables rules for Docker-host connectivity..."

# Flush any existing docker/osnet INPUT rules to avoid duplicates
# This prevents accumulation of rules when networks are recreated
echo "Flushing existing docker/osnet iptables rules..."
iptables -D INPUT -i docker0 -j ACCEPT 2>/dev/null || true
echo "  Cleared old docker0 rules"

# Find and remove old osnet bridge rules (handles changing bridge IDs)
for iface in $(ip link show | grep -o 'br-[0-9a-f]*' || true); do
  iptables -D INPUT -i "$iface" -j ACCEPT 2>/dev/null || true
done
echo "  Cleared old osnet bridge rules"

# Add fresh iptables rules for current Docker setup
echo "Adding new iptables rules..."

# Allow input from docker0 bridge interface
iptables -I INPUT -i docker0 -j ACCEPT
echo "✓ Added rule for docker0 interface"

# Allow input from OpenSearch network bridge (osnet)
# Docker network bridges are named br-{first12charsofnetworkid}
OSNET_BRIDGE=$(docker network ls -qf name=osnet | head -1)
if [ -n "$OSNET_BRIDGE" ]; then
  OSNET_INTERFACE="br-${OSNET_BRIDGE:0:12}"
  if [ -d "/sys/class/net/$OSNET_INTERFACE" ]; then
    iptables -I INPUT -i "$OSNET_INTERFACE" -j ACCEPT
    echo "✓ Added rule for $OSNET_INTERFACE (osnet network)"
  else
    echo "⚠ Warning: Could not find interface for osnet network"
  fi
else
  echo "⚠ Warning: osnet network not found"
fi

# Allow PostgreSQL remote access on port 5432
iptables -I INPUT -p tcp --dport 5432 -j ACCEPT
echo "✓ Added rule for PostgreSQL port 5432"

# Persist iptables rules
if command -v netfilter-persistent &> /dev/null; then
  netfilter-persistent save
  echo "✓ Saved iptables rules with netfilter-persistent"
else
  echo "⚠ Warning: netfilter-persistent not found - rules may not persist on reboot"
fi

echo "Done at $(date '+%Y-%m-%d %H:%M:%S')"
