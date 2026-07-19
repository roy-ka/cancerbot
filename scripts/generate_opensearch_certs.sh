#!/bin/bash
# Generates a self-signed root CA and a node certificate for OpenSearch's
# security plugin, so the app can verify TLS with verify_certs=True instead
# of disabling verification (see src/retrieval/db_connector.py).
#
# Run this once per environment (local dev, and separately on prod / wherever
# OpenSearch actually runs) — each environment gets its own CA. The root CA
# private key (root-ca-key.pem) never leaves the machine it was generated on;
# only root-ca.pem (public) needs to be distributed, via OPENSEARCH_CA_CERT.
#
# Usage: scripts/generate_opensearch_certs.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CERT_DIR="$PROJECT_DIR/certs/opensearch"

mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

if [ -f root-ca.pem ]; then
  echo "Certs already exist at $CERT_DIR — remove them first if you want to regenerate."
  exit 1
fi

echo "Generating root CA..."
openssl genrsa -out root-ca-key.pem 2048 2>/dev/null
openssl req -new -x509 -sha256 -key root-ca-key.pem \
  -subj "/CN=CancerBot OpenSearch Root CA" -days 3650 \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -out root-ca.pem

echo "Generating node certificate (opensearch-node1, opensearch-node2, localhost)..."
openssl genrsa -out node-key.pem 2048 2>/dev/null
openssl req -new -key node-key.pem -subj "/CN=opensearch-node1" -out node.csr

cat > node.ext <<EOF
subjectAltName = DNS:opensearch-node1,DNS:opensearch-node2,DNS:localhost,IP:127.0.0.1
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth,clientAuth
EOF

openssl x509 -req -in node.csr -CA root-ca.pem -CAkey root-ca-key.pem -CAcreateserial \
  -sha256 -days 3650 -out node.pem -extfile node.ext

rm -f node.csr node.ext root-ca.srl
chmod 600 root-ca-key.pem node-key.pem

echo ""
echo "Done. Generated in $CERT_DIR:"
echo "  root-ca.pem      — public CA cert, set OPENSEARCH_CA_CERT to this path"
echo "  root-ca-key.pem  — private CA key, KEEP SECRET, never commit or share"
echo "  node.pem         — node certificate (mounted into OpenSearch containers)"
echo "  node-key.pem      — node private key (mounted into OpenSearch containers)"
echo ""
echo "Restart the OpenSearch containers after this, then set in your .env:"
echo "  OPENSEARCH_CA_CERT=$CERT_DIR/root-ca.pem"
