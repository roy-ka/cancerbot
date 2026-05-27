#!/bin/bash
# Production deploy script for CancerBot
# Pulls latest code, builds Docker images, runs migrations, and health checks
# Usage: ./scripts/deploy.sh [--force]
# The --force flag skips confirmation prompts

set -euo pipefail

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
    echo "✗ No backup file found - cannot restore database"
  fi

  exit $exit_code
}

# Set trap for errors (after we have the backup)
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

# Create database backup
echo ""
echo "Creating PostgreSQL backup..."
BACKUP_FILE="$PROJECT_DIR/backups/backup_$TIMESTAMP.sql"
if docker exec cancerbot-postgres pg_dump -U cancerbot cancerbot > "$BACKUP_FILE"; then
  BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
  echo "✓ Database backup created: $BACKUP_FILE ($BACKUP_SIZE)"
else
  echo "✗ Database backup failed"
  exit 1
fi

# Build Docker images
echo ""
echo "Building Docker images..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot build; then
  echo "✓ Docker images built successfully"
else
  echo "✗ Docker build failed"
  exit 1
fi

# Extract POSTGRES_PASSWORD from .env
POSTGRES_PASSWORD=$(grep -E '^POSTGRES_PASSWORD=' "$PROJECT_DIR/.env" | cut -d'=' -f2- | tr -d "'\"")

# Run Alembic migrations
echo ""
echo "Running Alembic migrations..."
if docker run --rm \
  --network cancerbot-private_osnet \
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

# Restart services
echo ""
echo "Restarting Docker services..."
if docker compose -f "$PROJECT_DIR/docker-compose.yml" -p cancerbot up -d --force-recreate; then
  echo "✓ Services restarted"
else
  echo "✗ Failed to restart services"
  exit 1
fi

# Fix iptables rules for Docker-host connectivity
echo ""
echo "Fixing iptables rules for Docker-host connectivity..."
sleep 10
echo "Waiting for Docker networks to fully initialize..."
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
