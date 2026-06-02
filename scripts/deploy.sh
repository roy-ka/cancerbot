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
LOG_FILE="$PROJECT_DIR/logs/deploy_$TIMESTAMP.log"

# Redirect all output to log file and stdout
exec > >(tee -a "$LOG_FILE")
exec 2>&1

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
  echo "✗ Warning: alembic not found in PATH (will run inside Docker)"
fi

# Check disk space (needs >2GB free)
DISK_AVAILABLE=$(df -BG "$PROJECT_DIR" | awk 'NR==2 {print $(NF-2)}' | sed 's/G$//')
if [ "$DISK_AVAILABLE" -lt 2 ]; then
  echo "✗ Error: Not enough disk space. Required: 2GB, Available: ${DISK_AVAILABLE}GB"
  exit 1
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
BACKEND_IMAGE=$(docker inspect --format='{{.Image}}' cancerbot-backend-1 2>/dev/null || echo "")
NLP_IMAGE=$(docker inspect --format='{{.Image}}' cancerbot-nlp 2>/dev/null || echo "")
BACKEND_IMAGE_TAG="cancerbot-backend:rollback_$TIMESTAMP"
NLP_IMAGE_TAG="cancerbot-nlp:rollback_$TIMESTAMP"

if [ -n "$BACKEND_IMAGE" ]; then
  docker tag "$BACKEND_IMAGE" "$BACKEND_IMAGE_TAG"
  echo "✓ Saved backend image: $BACKEND_IMAGE_TAG"
fi

if [ -n "$NLP_IMAGE" ]; then
  docker tag "$NLP_IMAGE" "$NLP_IMAGE_TAG"
  echo "✓ Saved NLP image: $NLP_IMAGE_TAG"
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

  if [ -f "$BACKUP_FILE" ]; then
    echo "Restoring database from backup: $BACKUP_FILE"
    # Bring down services first
    echo "Stopping services..."
    docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot down || true

    # Re-tag old images if we saved them
    if [ -n "$BACKEND_IMAGE" ] && docker inspect "$BACKEND_IMAGE_TAG" &>/dev/null; then
      docker tag "$BACKEND_IMAGE_TAG" "$BACKEND_IMAGE"
      echo "✓ Restored backend image"
    fi

    if [ -n "$NLP_IMAGE" ] && docker inspect "$NLP_IMAGE_TAG" &>/dev/null; then
      docker tag "$NLP_IMAGE_TAG" "$NLP_IMAGE"
      echo "✓ Restored NLP image"
    fi

    # Bring services back up
    echo "Starting services with previous images..."
    docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot up -d || true

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

    echo ""
    echo "Rollback complete. Check log for details: $LOG_FILE"
  else
    echo "⚠ No backup file available - database not restored"
  fi

  exit $exit_code
}

# Set trap for errors
trap rollback ERR

# Pull latest code
echo ""
echo "Pulling latest code from git..."
cd "$PROJECT_DIR"
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
fi

if "$NPM_PATH" install; then
  echo "✓ npm dependencies installed"
else
  echo "✗ npm install failed"
  exit 1
fi

if "$NPM_PATH" run build; then
  echo "✓ Frontend build completed"
else
  echo "✗ Frontend build failed"
  exit 1
fi

cd "$PROJECT_DIR"

# Build Docker images
echo ""
echo "Building Docker images..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot build; then
  echo "✓ Docker images built successfully"
else
  echo "✗ Docker build failed"
  exit 1
fi

# Conditional database backup - only if postgres is running
echo ""
if docker ps --format '{{.Names}}' | grep -q 'cancerbot-postgres'; then
  echo "Creating PostgreSQL backup..."
  BACKUP_FILE="$PROJECT_DIR/backups/backup_$TIMESTAMP.sql"
  if docker exec cancerbot-postgres pg_dump -U cancerbot cancerbot > "$BACKUP_FILE"; then
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

# Stop and remove existing containers
echo ""
echo "Stopping and removing existing containers..."

# First try docker compose down
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot down --remove-orphans 2>&1; then
  echo "✓ Docker compose down completed"
else
  echo "⚠ Warning: docker compose down had issues, continuing with manual cleanup"
fi

# Force remove any remaining containers
echo "Stopping and removing containers..."
docker ps -a -q | while read container_id; do
  docker stop "$container_id" 2>/dev/null || true
done
docker ps -a -q | while read container_id; do
  docker rm -f "$container_id" 2>/dev/null || true
done
echo "✓ Containers removed"

# Remove any dangling networks and wait for port release
echo ""
echo "Cleaning up networks and ports..."
docker network prune -f 2>/dev/null || true

# Full Docker cleanup if needed
echo "Running full Docker system prune (removing unused images, volumes, networks)..."
docker system prune -f --volumes 2>/dev/null || true

# Kill any process using port 8000
echo "Checking port 8000..."
if lsof -i :8000 &>/dev/null; then
  echo "Killing processes using port 8000..."
  lsof -ti :8000 | xargs kill -9 2>/dev/null || true
  sleep 2
elif netstat -tuln 2>/dev/null | grep -q ':8000 '; then
  echo "Port 8000 appears in use but no process found, waiting..."
  sleep 3
fi

# Wait for port 8000 to be released (up to 10 seconds)
echo "Waiting for port 8000 to be released..."
for i in $(seq 1 10); do
  if ! lsof -i :8000 &>/dev/null 2>&1 && ! netstat -tuln 2>/dev/null | grep -q ':8000 '; then
    echo "✓ Port 8000 is free"
    break
  fi
  echo "  Port 8000 still in use, waiting... ($i/10)"
  sleep 1
done

if lsof -i :8000 &>/dev/null 2>&1; then
  echo "⚠ Warning: Port 8000 still in use, but proceeding anyway"
fi

# Start services
echo ""
echo "Starting services..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot up -d; then
  echo "✓ Services started"
else
  echo "✗ Failed to start services"
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

# Extract POSTGRES_PASSWORD from .env
POSTGRES_PASSWORD=$(grep -E '^POSTGRES_PASSWORD=' "$PROJECT_DIR/.env" | cut -d'=' -f2- | tr -d "'\"")

# Run Alembic migrations
echo ""
echo "Running Alembic migrations..."
if docker run --rm \
  --network cancerbot_osnet \
  --env-file "$PROJECT_DIR/.env" \
  -e POSTGRES_URL="postgresql+asyncpg://cancerbot:${POSTGRES_PASSWORD}@cancerbot-postgres:5432/cancerbot" \
  -v "$(pwd):/app" -w /app \
  python:3.12-slim bash -c \
  "pip install alembic psycopg2-binary sqlalchemy python-dotenv -q && alembic upgrade head"; then
  echo "✓ Alembic migrations completed"
else
  echo "✗ Alembic migrations failed"
  exit 1
fi

# Fix iptables rules for Docker-host connectivity (after 10 second sleep)
echo ""
echo "Waiting 10 seconds for Docker networks to fully initialize..."
sleep 10
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
  response=$(curl -sf http://localhost:8000/health/ 2>/dev/null || echo "")
  if echo "$response" | grep -q '"status":"ok"'; then
    HEALTHY=true
    echo "✓ Health check passed (attempt $i/30)"
    break
  fi
  echo "  Attempt $i/30 - health check not ready, waiting..."
  sleep 5
done

if [ "$HEALTHY" = false ]; then
  echo "✗ Health check failed after 30 attempts"
  exit 1
fi

# Reload nginx with new frontend
echo ""
echo "Reloading nginx..."
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
