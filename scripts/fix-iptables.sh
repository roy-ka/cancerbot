#!/bin/bash
# Fix iptables rules for Docker container-to-host connectivity
# Allows Docker containers to reach the host (e.g., Ollama running on host)
# Called by iptables-docker.service after Docker starts

set -euo pipefail

echo "Applying iptables rules for Docker-host connectivity..."

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

# Persist iptables rules
if command -v netfilter-persistent &> /dev/null; then
  netfilter-persistent save
  echo "✓ Saved iptables rules with netfilter-persistent"
else
  echo "⚠ Warning: netfilter-persistent not found - rules may not persist on reboot"
fi

echo "Done at $(date '+%Y-%m-%d %H:%M:%S')"
