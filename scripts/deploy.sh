#!/bin/bash
# Production deploy script for CancerBot
# Pulls latest code, builds Docker images, runs migrations, and health checks
# Usage: ./scripts/deploy.sh [--force]
# The --force flag skips confirmation prompts

set -euo pipefail

# Add Node.js snap to PATH for npm commands (fallback if nvm not used)
export PATH=$PATH:/snap/bin

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# git pull (below) can update this very file mid-run. Bash has already read
# this script into memory by the time that happens, so it keeps executing the
# OLD version for the rest of the run — any step added to deploy.sh in the
# commit being pulled would silently never run on the deploy that introduces
# it. Guard against that: hash this file now, compare after the pull, and
# re-exec from scratch (so bash reloads the new version fully) if it changed.
: "${DEPLOY_REEXEC_COUNT:=0}"
DEPLOY_SH_HASH_BEFORE_PULL="$(sha256sum "$SCRIPT_DIR/deploy.sh" | awk '{print $1}')"

# Parse arguments
FORCE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)
      FORCE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Setup logging
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/backups"
# Ensure the current user owns the log dirs so tee can write
sudo chown "$(id -u):$(id -g)" "$PROJECT_DIR/logs" "$PROJECT_DIR/backups" 2>/dev/null || true
chmod 755 "$PROJECT_DIR/logs" "$PROJECT_DIR/backups" 2>/dev/null || true
# Reuse the same log file across a self re-exec (see DEPLOY_REEXEC_COUNT above)
# instead of splitting one logical deploy across two timestamped log files.
LOG_FILE="${DEPLOY_LOG_FILE_OVERRIDE:-$PROJECT_DIR/logs/deploy_$TIMESTAMP.log}"

# Create log file and redirect all output to it and stdout
if touch "$LOG_FILE" 2>/dev/null; then
  exec > >(tee -a "$LOG_FILE") 2>&1
else
  echo "⚠ Warning: could not create log file at $LOG_FILE — output will not be saved"
fi

echo "========================================="
echo "CancerBot Deploy Started at $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="
echo "Log file: $LOG_FILE"
echo ""

# Load .env file
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "✗ Error: .env file not found at $PROJECT_DIR/.env"
  exit 1
fi

set -a
source "$PROJECT_DIR/.env"
set +a

echo "✓ Loaded .env configuration"

# Check prerequisites
echo ""
echo "Checking prerequisites..."

if ! command -v git &> /dev/null; then
  echo "✗ Error: git is not installed"
  exit 1
fi
echo "✓ git found"

if ! command -v docker &> /dev/null; then
  echo "✗ Error: docker is not installed"
  exit 1
fi
echo "✓ docker found"

if ! command -v alembic &> /dev/null; then
  echo "⚠ Warning: alembic not found in PATH (will run inside Docker)"
fi

# Check disk space (needs >100GB free)
DISK_AVAILABLE=$(df -BG "$PROJECT_DIR" | awk 'NR==2 {print $(NF-2)}' | sed 's/G$//')
if [ "$DISK_AVAILABLE" -lt 100 ]; then
  echo "⚠ Low disk space (${DISK_AVAILABLE}GB). Running Docker cleanup..."
  docker system prune -a -f --volumes 2>/dev/null || true
  DISK_AVAILABLE=$(df -BG "$PROJECT_DIR" | awk 'NR==2 {print $(NF-2)}' | sed 's/G$//')
  if [ "$DISK_AVAILABLE" -lt 100 ]; then
    echo "✗ Error: Still not enough disk space after cleanup. Required: 100GB, Available: ${DISK_AVAILABLE}GB"
    exit 1
  fi
  echo "✓ Disk space recovered (${DISK_AVAILABLE}GB available)"
fi
echo "✓ Disk space check passed (${DISK_AVAILABLE}GB available)"

# Check vm.max_map_count (OpenSearch bootstrap check requires >= 262144;
# most fresh hosts default to 65530, which makes opensearch-node1/2 exit
# immediately on startup rather than just start slowly).
REQUIRED_MAX_MAP_COUNT=262144
CURRENT_MAX_MAP_COUNT="$(cat /proc/sys/vm/max_map_count)"
if [ "$CURRENT_MAX_MAP_COUNT" -lt "$REQUIRED_MAX_MAP_COUNT" ]; then
  echo "⚠ vm.max_map_count is ${CURRENT_MAX_MAP_COUNT} (OpenSearch needs >= ${REQUIRED_MAX_MAP_COUNT}). Fixing..."
  sudo sysctl -w vm.max_map_count=$REQUIRED_MAX_MAP_COUNT
  if ! grep -q "^vm.max_map_count" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.max_map_count=${REQUIRED_MAX_MAP_COUNT}" | sudo tee -a /etc/sysctl.conf > /dev/null
  fi
  CURRENT_MAX_MAP_COUNT="$(cat /proc/sys/vm/max_map_count)"
  if [ "$CURRENT_MAX_MAP_COUNT" -lt "$REQUIRED_MAX_MAP_COUNT" ]; then
    echo "✗ Error: vm.max_map_count still ${CURRENT_MAX_MAP_COUNT} after attempted fix"
    exit 1
  fi
  echo "✓ vm.max_map_count set to ${CURRENT_MAX_MAP_COUNT}"
else
  echo "✓ vm.max_map_count check passed (${CURRENT_MAX_MAP_COUNT})"
fi

# Confirmation prompt
if [ "$FORCE" = false ]; then
  echo ""
  read -p "Deploy to production? [y/N] " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled"
    exit 0
  fi
fi

DEPLOY_START=$(date +%s)

# Capture current image IDs for rollback
echo ""
echo "Capturing current images for rollback..."
BACKEND_IMAGE=$(docker ps --filter "name=cancerbot-backend" --format "{{.Image}}" 2>/dev/null | head -1 || echo "")
BACKEND_IMAGE_TAG="cancerbot-backend:rollback_$TIMESTAMP"

if [ -n "$BACKEND_IMAGE" ]; then
  if docker tag "$BACKEND_IMAGE" "$BACKEND_IMAGE_TAG" 2>/dev/null; then
    echo "✓ Saved backend image: $BACKEND_IMAGE_TAG"
  else
    echo "⚠ Warning: Could not tag backend image for rollback"
  fi
fi

# Initialize backup file variable (may remain empty if not created)
BACKUP_FILE=""
MIGRATIONS_APPLIED=false

# Run a command inside a one-off backend container (defined early so rollback can call it)
_alembic() {
  docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot \
    run --rm --no-deps backend "$@" 2>&1 | sed 's/^/    /'
}

# Rollback function
rollback() {
  local exit_code=$?
  echo ""
  echo "========================================="
  echo "✗ DEPLOYMENT FAILED - INITIATING ROLLBACK"
  echo "========================================="

  # Reset git to the commit that was live before this deploy
  echo "Resetting git to pre-deploy commit: ${PREV_GIT_HEAD:-HEAD}..."
  cd "$PROJECT_DIR"
  if git reset --hard "${PREV_GIT_HEAD:-HEAD}"; then
    echo "✓ Git reset to previous state"
  else
    echo "⚠ Warning: Failed to reset git state"
  fi

  # Always stop services and restart with old images
  echo "Stopping services..."
  docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot down || true

  if [ -n "$BACKEND_IMAGE" ] && docker inspect "$BACKEND_IMAGE_TAG" &>/dev/null; then
    docker tag "$BACKEND_IMAGE_TAG" "$BACKEND_IMAGE"
    echo "✓ Restored backend image"
  fi

  echo "Starting services with previous images..."
  docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot --profile prod up -d || true

  if [ -f "$BACKUP_FILE" ]; then
    # Wait for postgres to be ready
    echo "Waiting for PostgreSQL to be ready..."
    local retry=0
    while [ $retry -lt 30 ]; do
      if docker exec cancerbot-postgres pg_isready -U cancerbot -d cancerbot &>/dev/null; then
        echo "✓ PostgreSQL is ready"
        break
      fi
      sleep 2
      ((retry++))
    done

    # Restore database
    echo "Restoring database..."
    if cat "$BACKUP_FILE" | docker exec -i cancerbot-postgres psql -U cancerbot cancerbot &>/dev/null; then
      echo "✓ Database restored from backup"
    else
      echo "✗ Failed to restore database - manual intervention required"
      echo "Backup file: $BACKUP_FILE"
    fi
  elif [ "$MIGRATIONS_APPLIED" = true ]; then
    # No backup but migrations already ran — attempt a schema downgrade so the
    # old backend image doesn't start against a forward-migrated schema.
    echo "⚠ No backup available — attempting alembic downgrade to match previous image..."
    _alembic alembic downgrade -1 2>/dev/null || \
      echo "  ⚠ Downgrade failed — old backend may be incompatible with current schema"
  else
    echo "⚠ No backup file available - database not restored"
  fi

  echo ""
  echo "Failed after: $(( ($(date +%s) - ${DEPLOY_START:-$(date +%s)}) / 60 ))m $(( ($(date +%s) - ${DEPLOY_START:-$(date +%s)}) % 60 ))s"
  echo "Rollback complete. Check log for details: $LOG_FILE"
  exit $exit_code
}

# Set trap for errors
trap rollback ERR

# Reset git to clean state before pulling
echo ""
echo "Resetting git working directory to HEAD..."
cd "$PROJECT_DIR"
if git reset --hard HEAD; then
  echo "✓ Git working directory reset"
else
  echo "✗ Git reset failed"
  exit 1
fi

# Capture current commit so rollback can return to it if pull succeeds but deploy fails.
# On a self re-exec (DEPLOY_PREV_GIT_HEAD_OVERRIDE set), HEAD already points at
# the newly-pulled commit — use the value saved from before that pull instead
# of recomputing, or rollback would "roll back" to the new commit itself.
PREV_GIT_HEAD="${DEPLOY_PREV_GIT_HEAD_OVERRIDE:-$(git rev-parse HEAD)}"
echo "✓ Saved pre-deploy commit: $PREV_GIT_HEAD"

# Pull latest code
echo ""
echo "Pulling latest code from git..."
if git pull; then
  echo "✓ Git pull completed"
else
  echo "✗ Git pull failed"
  exit 1
fi

# If deploy.sh itself changed in the pull, re-exec now so the rest of this
# run uses the new version instead of continuing on bash's stale in-memory
# copy of the old one (see DEPLOY_REEXEC_COUNT comment near the top).
DEPLOY_SH_HASH_AFTER_PULL="$(sha256sum "$SCRIPT_DIR/deploy.sh" | awk '{print $1}')"
if [ "$DEPLOY_SH_HASH_AFTER_PULL" != "$DEPLOY_SH_HASH_BEFORE_PULL" ] && [ "$DEPLOY_REEXEC_COUNT" -lt 1 ]; then
  echo ""
  echo "⚠ deploy.sh changed in this pull — re-executing the updated script from the top so new steps aren't silently skipped this run..."
  export DEPLOY_REEXEC_COUNT=$((DEPLOY_REEXEC_COUNT + 1))
  export DEPLOY_LOG_FILE_OVERRIDE="$LOG_FILE"
  export DEPLOY_PREV_GIT_HEAD_OVERRIDE="$PREV_GIT_HEAD"
  exec "$SCRIPT_DIR/deploy.sh" --force
fi

# Build frontend
echo ""
echo "Building frontend..."
cd "$PROJECT_DIR/client"

# Only reinstall if package.json changed — keeps node_modules cached between deploys
PKGLOCK="$PROJECT_DIR/client/package-lock.json"
PKGLOCK_HASH_FILE="$PROJECT_DIR/.deploy_npm_hash"
PKGLOCK_HASH_NOW=$(md5sum "$PKGLOCK" 2>/dev/null | cut -d' ' -f1)
PKGLOCK_HASH_PREV=$(cat "$PKGLOCK_HASH_FILE" 2>/dev/null || echo "")
NPM_NEEDS_INSTALL=true
if [ "$PKGLOCK_HASH_NOW" = "$PKGLOCK_HASH_PREV" ] && [ -d "$PROJECT_DIR/client/node_modules" ]; then
  echo "✓ package-lock.json unchanged — skipping npm install"
  NPM_NEEDS_INSTALL=false
else
  echo "package-lock.json changed or node_modules missing — reinstalling..."
  rm -rf node_modules dist 2>/dev/null || true
fi

# Find npm in nvm or system
NPM_PATH=""
NPM_BIN_DIR=""

# Determine the actual user (in case script was run with sudo)
ACTUAL_USER="${SUDO_USER:-$(whoami)}"
ACTUAL_HOME=$(eval echo "~$ACTUAL_USER")

echo "Running as: $(whoami), Actual user: $ACTUAL_USER, Home: $ACTUAL_HOME"

if [ -d "$ACTUAL_HOME/.nvm" ]; then
  echo "Found nvm at: $ACTUAL_HOME/.nvm"
  # Find the latest Node.js version installed by nvm
  for node_dir in "$ACTUAL_HOME"/.nvm/versions/node/v*/bin; do
    if [ -f "$node_dir/npm" ]; then
      NPM_PATH="$node_dir/npm"
      NPM_BIN_DIR="$node_dir"
      echo "Found npm at: $NPM_PATH"
      break
    fi
  done
fi

# Fall back to system npm if not found in nvm
if [ -z "$NPM_PATH" ]; then
  NPM_PATH=$(command -v npm || echo "")
  if [ -n "$NPM_PATH" ]; then
    echo "Found system npm at: $NPM_PATH"
  fi
fi

if [ -z "$NPM_PATH" ] || [ ! -f "$NPM_PATH" ]; then
  echo "✗ Error: npm not found"
  echo "Please install Node.js 22 via nvm:"
  echo "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash"
  echo "  source ~/.bashrc"
  echo "  nvm install 22"
  exit 1
fi

echo "✓ Using npm: $NPM_PATH"
echo "✓ Node.js version: $("${NPM_PATH%/npm}/node" --version)"

# Add npm bin directory to PATH if using nvm (so node is found)
if [ -n "$NPM_BIN_DIR" ]; then
  export PATH="$NPM_BIN_DIR:$PATH"
  echo "✓ Added to PATH: $NPM_BIN_DIR"

  # Create symlinks in /usr/local/bin if they don't exist (for system-wide access)
  if [ ! -f "/usr/local/bin/node" ]; then
    ln -sf "$NPM_BIN_DIR/node" /usr/local/bin/node 2>/dev/null || true
  fi
  if [ ! -f "/usr/local/bin/npm" ]; then
    ln -sf "$NPM_PATH" /usr/local/bin/npm 2>/dev/null || true
  fi
fi

# Use node with explicit path to ensure it's found
NODE_PATH="${NPM_BIN_DIR}/node"
if [ ! -x "$NODE_PATH" ]; then
  NODE_PATH=$(command -v node || echo "")
fi

if [ -z "$NODE_PATH" ]; then
  echo "✗ Error: node binary not found"
  exit 1
fi

export VITE_BASE_URL=""

# Run npm as the actual user (not root) to avoid permission issues
# Pass VITE_* vars explicitly so they survive sudo's env reset
_npm() { "$NPM_PATH" "$@"; }
if [ "$(whoami)" = "root" ] && [ -n "$SUDO_USER" ]; then
  _npm() { sudo -u "$SUDO_USER" env VITE_BASE_URL="$VITE_BASE_URL" "$NPM_PATH" "$@"; }
fi

if [ "$NPM_NEEDS_INSTALL" = true ]; then
  if _npm install; then
    echo "✓ npm dependencies installed"
    echo "$PKGLOCK_HASH_NOW" > "$PKGLOCK_HASH_FILE"
  else
    echo "✗ npm install failed"
    exit 1
  fi
fi

if _npm run build; then
  echo "✓ Frontend build completed"
else
  echo "✗ Frontend build failed"
  exit 1
fi

cd "$PROJECT_DIR"

# Build Docker images — use --no-cache only when requirements files changed
echo ""
echo "Building Docker images..."
REQS_HASH_FILE="$PROJECT_DIR/.deploy_reqs_hash"
REQS_HASH_NOW=$(cat "$PROJECT_DIR/requirements.txt" 2>/dev/null | md5sum | cut -d' ' -f1)
REQS_HASH_PREV=$(cat "$REQS_HASH_FILE" 2>/dev/null || echo "")
DOCKER_BUILD_FLAGS=""
if [ "$REQS_HASH_NOW" != "$REQS_HASH_PREV" ]; then
  echo "Requirements changed — building with --no-cache"
  DOCKER_BUILD_FLAGS="--no-cache"
else
  echo "Requirements unchanged — using Docker layer cache"
fi
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot --profile prod build --pull $DOCKER_BUILD_FLAGS --build-arg APT_CACHE_DATE="$(date +%Y%m%d)"; then
  echo "✓ Docker images built successfully"
  echo "$REQS_HASH_NOW" > "$REQS_HASH_FILE"
else
  echo "✗ Docker build failed"
  exit 1
fi

# Scan Docker images for vulnerabilities
echo ""
echo "Scanning Docker images for vulnerabilities..."
if command -v trivy &>/dev/null; then
  SCAN_FAILED=false
  TRIVY_TAR=""
  # Cleanup on any exit path (normal, signal, or ERR trap firing rollback).
  # Must be set before the loop so interrupted docker save doesn't leak a large tar.
  _trivy_cleanup() { rm -f "${TRIVY_TAR:-}"; }
  trap '_trivy_cleanup' EXIT INT TERM

  for IMAGE in cancerbot-backend cancerbot-url-classifier; do
    if docker image inspect "$IMAGE" &>/dev/null; then
      echo "  Scanning $IMAGE..."
      # Write tar to PROJECT_DIR (not /tmp) so snap-confined Trivy can read it —
      # snap apps see a private tmpfs at /tmp that hides files written by the host shell.
      # Portable mktemp template syntax works on both GNU coreutils and macOS BSD mktemp.
      TRIVY_TAR=$(mktemp "$PROJECT_DIR/.trivy-scan-XXXXXX.tar")
      if ! docker save "$IMAGE:latest" -o "$TRIVY_TAR"; then
        echo "✗ docker save failed for $IMAGE — cannot scan"
        rm -f "$TRIVY_TAR"; TRIVY_TAR=""
        SCAN_FAILED=true
        continue
      fi
      if ! trivy image --quiet --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed --no-progress --input "$TRIVY_TAR"; then
        echo "✗ Trivy scan failed for $IMAGE — HIGH/CRITICAL vulnerabilities found (commit: $(git rev-parse HEAD))"
        SCAN_FAILED=true
      else
        echo "✓ $IMAGE passed vulnerability scan"
      fi
      rm -f "$TRIVY_TAR"; TRIVY_TAR=""
    else
      echo "✗ Image $IMAGE not found — cannot scan"
      SCAN_FAILED=true
    fi
  done
  trap - EXIT INT TERM
  if [ "$SCAN_FAILED" = true ]; then
    exit 1
  fi
else
  echo "⚠ Warning: trivy not installed — skipping image scan (install with: apt install trivy)"
fi

# Conditional database backup - only if postgres is running
echo ""
if docker ps --format '{{.Names}}' | grep -q 'cancerbot-postgres'; then
  echo "Creating PostgreSQL backup..."
  BACKUP_FILE="$PROJECT_DIR/backups/backup_$TIMESTAMP.sql"
  TEMP_BACKUP="/tmp/backup_$TIMESTAMP.sql"

  # Backup to temp location first, then move with sudo
  if docker exec cancerbot-postgres pg_dump -U cancerbot cancerbot > "$TEMP_BACKUP"; then
    sudo mv "$TEMP_BACKUP" "$BACKUP_FILE" 2>/dev/null || mv "$TEMP_BACKUP" "$BACKUP_FILE"
    sudo chmod 644 "$BACKUP_FILE" 2>/dev/null || true
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "✓ Database backup created: $BACKUP_FILE ($BACKUP_SIZE)"
  else
    echo "✗ Database backup failed"
    exit 1
  fi
else
  echo "⚠ Warning: postgres not running, skipping backup"
  BACKUP_FILE=""
fi

# Start infrastructure only (postgres, opensearch, dashboards) — NOT the backend.
# Migrations must run before the backend starts to avoid a race condition where
# start.sh's 'alembic upgrade heads' and the deploy's migration container run
# concurrently and corrupt the alembic_version table with duplicate entries.
echo ""
echo "Starting infrastructure services..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot up -d; then
  echo "✓ Infrastructure services started"
else
  echo "✗ Failed to start infrastructure services"
  exit 1
fi

# Fix permissions on built frontend
echo ""
echo "Fixing permissions on frontend build..."
if sudo chmod -R 755 "$PROJECT_DIR/client/dist" && sudo chmod -R 755 "$PROJECT_DIR"; then
  echo "✓ Frontend permissions fixed"
else
  echo "⚠ Warning: Failed to fix frontend permissions (Nginx may have access issues)"
fi

# Wait for PostgreSQL to be healthy before running migrations
echo ""
echo "Waiting for PostgreSQL to be ready (up to 60 seconds)..."
POSTGRES_READY=false
for i in $(seq 1 30); do
  if docker exec cancerbot-postgres pg_isready -U cancerbot -d cancerbot &>/dev/null; then
    POSTGRES_READY=true
    echo "✓ PostgreSQL is ready (attempt $i/30)"
    break
  fi
  echo "  Attempt $i/30 - PostgreSQL not ready, waiting..."
  sleep 2
done

if [ "$POSTGRES_READY" = false ]; then
  echo "✗ PostgreSQL failed to become ready after 60 seconds"
  exit 1
fi

# Run Alembic migrations in a one-off container before the backend starts.
echo ""
echo "Running Alembic migrations..."
CURRENT_OUT=$(_alembic alembic current 2>&1)
echo "  Current revision:"
echo "$CURRENT_OUT"

if echo "$CURRENT_OUT" | grep -q "(head)"; then
  echo "✓ Database already at head, no migrations needed"
  MIGRATIONS_APPLIED=true
else
  echo "  Applying migrations..."
  if _alembic alembic upgrade heads; then
    MIGRATIONS_APPLIED=true
    echo "  Revision after upgrade:"
    _alembic alembic current || true
    echo "✓ Alembic migrations completed"
  else
    echo "✗ Alembic migrations failed"
    exit 1
  fi
fi

# Wait for OpenSearch to be healthy before running seeds. A cold 2-node
# cluster on a fresh host can take minutes to form (see the healthcheck
# start_period/retries on opensearch-node1 in docker-compose.yml) — far
# longer than the Postgres wait above, so seeds raced ahead of it and hit
# "Connection refused" on every fresh deploy. Non-fatal like the seeds
# themselves: they already tolerate OpenSearch being unavailable.
echo ""
echo "Waiting for OpenSearch to be ready (up to 5 minutes)..."
OPENSEARCH_READY=false
for i in $(seq 1 60); do
  if [ "$(docker inspect --format='{{.State.Health.Status}}' opensearch-node1 2>/dev/null)" = "healthy" ]; then
    OPENSEARCH_READY=true
    echo "✓ OpenSearch is ready (attempt $i/60)"
    break
  fi
  echo "  Attempt $i/60 - OpenSearch not ready, waiting..."
  sleep 5
done

if [ "$OPENSEARCH_READY" = false ]; then
  echo "⚠ Warning: OpenSearch not healthy after 5 minutes — seeds will likely fail (non-critical)"
fi

# Run one-off seeds against the live infrastructure (OpenSearch, Postgres)
# Seeds are non-fatal: a failure logs a warning but does not abort the deploy.
echo ""
echo "Running seeds..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot \
    run --rm --no-deps backend python scripts/seed_wikipedia_tags.py 2>&1 | sed 's/^/    /'; then
  echo "✓ Seeds completed"
else
  echo "⚠ Warning: seeds failed (non-critical — deploy continues)"
fi

# Backfill existing OpenSearch docs to chunked schema (idempotent — skips already-migrated docs)
echo ""
echo "Running chunk backfill migration..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot \
    run --rm --no-deps backend python scripts/backfill_chunks.py 2>&1 | sed 's/^/    /'; then
  echo "✓ Chunk backfill completed"
else
  echo "⚠ Warning: chunk backfill failed (non-critical — deploy continues)"
fi

# Backfill pub_year/pub_types/evidence_level onto existing pmid sources so
# retrieval's evidence/recency boosts have something to match (idempotent —
# only touches docs still missing evidence_level)
echo ""
echo "Running source metadata backfill..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot \
    run --rm --no-deps backend python scripts/backfill_source_metadata.py 2>&1 | sed 's/^/    /'; then
  echo "✓ Source metadata backfill completed"
else
  echo "⚠ Warning: source metadata backfill failed (non-critical — deploy continues)"
fi

# Backfill real titles onto existing conversations still on the naive
# first-message-prefix title (idempotent — skips already-backfilled ones)
echo ""
echo "Running conversation title backfill..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot \
    run --rm --no-deps backend python scripts/backfill_conversation_titles.py 2>&1 | sed 's/^/    /'; then
  echo "✓ Conversation title backfill completed"
else
  echo "⚠ Warning: conversation title backfill failed (non-critical — deploy continues)"
fi

# Now start the backend and other prod-profile services
echo ""
echo "Starting backend services..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot --profile prod up -d --remove-orphans; then
  echo "✓ Backend services started"
else
  echo "✗ Failed to start backend services"
  exit 1
fi

# Fix iptables rules for Docker-host connectivity
# Poll for the Docker network to exist rather than sleeping a fixed interval
echo ""
echo "Waiting for Docker network to be ready..."
for i in $(seq 1 20); do
  if docker network inspect cancerbot_osnet &>/dev/null; then
    echo "✓ Docker network ready"
    break
  fi
  echo "  Waiting for network... ($i/20)"
  sleep 1
done

echo "Fixing iptables rules for Docker-host connectivity..."
if sudo "$SCRIPT_DIR/fix-iptables.sh"; then
  echo "✓ iptables rules applied successfully"
else
  echo "⚠ Warning: iptables fix failed (this may affect Ollama connectivity)"
fi

# Health check loop
echo ""
echo "Running health checks (up to 30 attempts, 5 seconds apart)..."
HEALTHY=false
for i in $(seq 1 30); do
  # Capture exit code without triggering set -e on connection failures
  curl_exit=0
  response=$(curl -sf http://localhost:8000/health/ 2>&1) || curl_exit=$?

  if echo "$response" | grep -q '"status":"ok"'; then
    HEALTHY=true
    echo "✓ Health check passed (attempt $i/30)"
    echo "  Response: $response"
    break
  fi

  if [ $curl_exit -ne 0 ]; then
    echo "  Attempt $i/30 - connection error, waiting..."
    echo "  Error: $(echo "$response" | head -1)"
  else
    echo "  Attempt $i/30 - API not ready, waiting..."
    echo "  Response: $response"
  fi
  sleep 5
done

if [ "$HEALTHY" = false ]; then
  echo "✗ Health check failed after 30 attempts"
  echo "Debug: Check if backend container is running:"
  docker ps --format '{{.Names}}: {{.Status}}' | grep -E 'backend|cancerbot'
  exit 1
fi

# Reload nginx with new frontend
echo ""
echo "Reloading nginx..."
NGINX_CONF_SRC="$PROJECT_DIR/nginx.conf"
NGINX_CONF_DEST="/etc/nginx/sites-available/cancerbot"
if [ -f "$NGINX_CONF_SRC" ]; then
  echo "Updating nginx config..."
  sudo cp "$NGINX_CONF_SRC" "$NGINX_CONF_DEST"
  echo "✓ Nginx config updated"
fi

if sudo nginx -t &>/dev/null; then
  if sudo systemctl reload nginx; then
    echo "✓ Nginx reloaded successfully"
  else
    echo "⚠ Warning: Nginx reload failed (frontend may not be updated)"
  fi
else
  echo "⚠ Warning: Nginx config test failed (frontend may not be updated)"
fi

# Unset error trap on success
trap - ERR

# Rotate old backups — keep the 5 most recent
echo ""
echo "Rotating old backups..."
ls -t "$PROJECT_DIR/backups"/backup_*.sql 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null || true
echo "✓ Old backups cleaned up"

# Success summary
DEPLOY_ELAPSED=$(( $(date +%s) - DEPLOY_START ))
echo ""
echo "========================================="
echo "✓ DEPLOYMENT SUCCESSFUL"
echo "========================================="
echo "Deployed at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Git commit:  $(git rev-parse HEAD) ($(git rev-parse --short HEAD))"
echo "Duration: $(( DEPLOY_ELAPSED / 60 ))m $(( DEPLOY_ELAPSED % 60 ))s"
echo "Backend image: $(docker inspect --format='{{.Image}}' cancerbot-backend-1 2>/dev/null || echo 'unknown')"
echo "Database backup: $BACKUP_FILE"
echo "Deploy log: $LOG_FILE"
echo ""
echo "To view the deployment log later:"
echo "  tail -f $LOG_FILE"
echo ""
