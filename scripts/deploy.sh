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
chmod 755 "$PROJECT_DIR/logs" "$PROJECT_DIR/backups" 2>/dev/null || sudo chmod 755 "$PROJECT_DIR/logs" "$PROJECT_DIR/backups" 2>/dev/null || true
LOG_FILE="$PROJECT_DIR/logs/deploy_$TIMESTAMP.log"

# Create log file and redirect all output to it and stdout
touch "$LOG_FILE" && chmod 666 "$LOG_FILE" 2>/dev/null || true
exec > >(tee -a "$LOG_FILE") 2>&1

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

# Check disk space (needs >2GB free)
DISK_AVAILABLE=$(df -BG "$PROJECT_DIR" | awk 'NR==2 {print $(NF-2)}' | sed 's/G$//')
if [ "$DISK_AVAILABLE" -lt 2 ]; then
  echo "⚠ Low disk space (${DISK_AVAILABLE}GB). Running Docker cleanup..."
  docker system prune -a -f --volumes 2>/dev/null || true
  DISK_AVAILABLE=$(df -BG "$PROJECT_DIR" | awk 'NR==2 {print $(NF-2)}' | sed 's/G$//')
  if [ "$DISK_AVAILABLE" -lt 2 ]; then
    echo "✗ Error: Still not enough disk space after cleanup. Required: 2GB, Available: ${DISK_AVAILABLE}GB"
    exit 1
  fi
  echo "✓ Disk space recovered (${DISK_AVAILABLE}GB available)"
fi
echo "✓ Disk space check passed (${DISK_AVAILABLE}GB available)"

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

# Capture current image IDs for rollback
echo ""
echo "Capturing current images for rollback..."
BACKEND_IMAGE=$(docker ps --filter "name=cancerbot-backend" --format "{{.Image}}" 2>/dev/null | head -1 || echo "")
NLP_IMAGE=$(docker ps --filter "name=cancerbot-nlp" --format "{{.Image}}" 2>/dev/null | head -1 || echo "")
BACKEND_IMAGE_TAG="cancerbot-backend:rollback_$TIMESTAMP"
NLP_IMAGE_TAG="cancerbot-nlp:rollback_$TIMESTAMP"

if [ -n "$BACKEND_IMAGE" ]; then
  if docker tag "$BACKEND_IMAGE" "$BACKEND_IMAGE_TAG" 2>/dev/null; then
    echo "✓ Saved backend image: $BACKEND_IMAGE_TAG"
  else
    echo "⚠ Warning: Could not tag backend image for rollback"
  fi
fi

if [ -n "$NLP_IMAGE" ]; then
  if docker tag "$NLP_IMAGE" "$NLP_IMAGE_TAG" 2>/dev/null; then
    echo "✓ Saved NLP image: $NLP_IMAGE_TAG"
  else
    echo "⚠ Warning: Could not tag NLP image for rollback"
  fi
fi

# Initialize backup file variable (may remain empty if not created)
BACKUP_FILE=""

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

  if [ -n "$NLP_IMAGE" ] && docker inspect "$NLP_IMAGE_TAG" &>/dev/null; then
    docker tag "$NLP_IMAGE_TAG" "$NLP_IMAGE"
    echo "✓ Restored NLP image"
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
  else
    echo "⚠ No backup file available - database not restored"
  fi

  echo ""
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

# Capture current commit so rollback can return to it if pull succeeds but deploy fails
PREV_GIT_HEAD=$(git rev-parse HEAD)
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

# Read build-time env vars from server .env (keep secrets out of git)
SENTRY_DSN_VAL=$(grep -E '^SENTRY_DSN=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
export VITE_BASE_URL=""
export VITE_SENTRY_DSN="$SENTRY_DSN_VAL"

# Run npm as the actual user (not root) to avoid permission issues
# Pass VITE_* vars explicitly so they survive sudo's env reset
_npm() { "$NPM_PATH" "$@"; }
if [ "$(whoami)" = "root" ] && [ -n "$SUDO_USER" ]; then
  _npm() { sudo -u "$SUDO_USER" env VITE_BASE_URL="$VITE_BASE_URL" VITE_SENTRY_DSN="$VITE_SENTRY_DSN" "$NPM_PATH" "$@"; }
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
REQS_HASH_NOW=$(cat "$PROJECT_DIR/requirements.txt" "$PROJECT_DIR/nlp_service/requirements.txt" 2>/dev/null | md5sum | cut -d' ' -f1)
REQS_HASH_PREV=$(cat "$REQS_HASH_FILE" 2>/dev/null || echo "")
DOCKER_BUILD_FLAGS=""
if [ "$REQS_HASH_NOW" != "$REQS_HASH_PREV" ]; then
  echo "Requirements changed — building with --no-cache"
  DOCKER_BUILD_FLAGS="--no-cache"
else
  echo "Requirements unchanged — using Docker layer cache"
fi
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot --profile prod build $DOCKER_BUILD_FLAGS; then
  echo "✓ Docker images built successfully"
  echo "$REQS_HASH_NOW" > "$REQS_HASH_FILE"
else
  echo "✗ Docker build failed"
  exit 1
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

# Update services — only containers with changed images are recreated;
# stateful services (postgres, opensearch, ollama) keep running throughout
echo ""
echo "Updating services..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot --profile prod up -d --remove-orphans; then
  echo "✓ Services updated"
else
  echo "✗ Failed to update services"
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

# Run Alembic migrations inside the backend container (alembic is installed there)
echo ""
echo "Running Alembic migrations..."
BACKEND_CONTAINER=$(docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot ps -q backend 2>/dev/null | head -1)
if [ -z "$BACKEND_CONTAINER" ]; then
  echo "✗ Backend container not found"
  exit 1
fi

for i in $(seq 1 15); do
  if docker inspect "$BACKEND_CONTAINER" --format='{{.State.Running}}' 2>/dev/null | grep -q "true"; then
    break
  fi
  echo "  Waiting for backend container to start... ($i/15)"
  sleep 2
done

echo "  Current revision:"
docker exec "$BACKEND_CONTAINER" alembic current 2>&1 | sed 's/^/    /'

echo "  Pending migrations:"
docker exec "$BACKEND_CONTAINER" alembic history --indicate-current 2>&1 | sed 's/^/    /'

echo "  Applying migrations..."
if docker exec "$BACKEND_CONTAINER" alembic upgrade head 2>&1 | sed 's/^/    /'; then
  echo "  Revision after upgrade:"
  docker exec "$BACKEND_CONTAINER" alembic current 2>&1 | sed 's/^/    /'
  echo "✓ Alembic migrations completed"
else
  echo "✗ Alembic migrations failed"
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
  # Use curl with verbose error output
  response=$(curl -sf http://localhost:8000/health/ 2>&1)
  curl_exit=$?

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
echo ""
echo "========================================="
echo "✓ DEPLOYMENT SUCCESSFUL"
echo "========================================="
echo "Deployed at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Backend image: $(docker inspect --format='{{.Image}}' cancerbot-backend-1 2>/dev/null || echo 'unknown')"
echo "NLP image: $(docker inspect --format='{{.Image}}' cancerbot-nlp 2>/dev/null || echo 'unknown')"
echo "Database backup: $BACKUP_FILE"
echo "Deploy log: $LOG_FILE"
echo ""
echo "To view the deployment log later:"
echo "  tail -f $LOG_FILE"
echo ""
