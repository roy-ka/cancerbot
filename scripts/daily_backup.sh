#!/bin/bash
# Daily backup script for CancerBot database
# Schedule in crontab with: 0 2 * * * /path/to/cancerbot/scripts/daily_backup.sh
# (runs at 2am every day)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  source "$PROJECT_DIR/.env"
  set +a
else
  echo "Error: .env file not found at $PROJECT_DIR/.env"
  exit 1
fi

echo "Starting backup at $(date '+%Y-%m-%d %H:%M:%S')"

# Backup to local disk, keep 7 days
cd "$PROJECT_DIR"
python scripts/backup_db.py --dir "$BACKUP_DIR" --prune 7

# Optionally upload to S3 (requires BACKUP_S3_BUCKET env var)
if [ -n "$BACKUP_S3_BUCKET" ]; then
  echo "Uploading to S3..."
  python scripts/backup_db.py --dir "$BACKUP_DIR" --s3
fi

echo "Backup complete at $(date '+%Y-%m-%d %H:%M:%S')"
