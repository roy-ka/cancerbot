#!/bin/bash
# Daily backup script for CancerBot database + OpenSearch indices
# Schedule in crontab with: 0 2 * * * /path/to/cancerbot/scripts/daily_backup.sh
# (runs at 2am every day)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"

if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "Error: .env file not found at $PROJECT_DIR/.env"
  exit 1
fi

# .env is intentionally NOT bash-`source`d: an unquoted value containing a
# shell control character (&, $, backticks, ...) gets shell-interpreted
# rather than treated as literal text, which silently corrupts variables
# like POSTGRES_URL. backup_db.py / backup_opensearch.py load .env
# themselves via python-dotenv, which parses it as data, not shell syntax.
# BACKUP_S3_BUCKET is the one value bash itself needs, so extract it the
# same safe way instead of sourcing the whole file.
cd "$PROJECT_DIR"
read -r BACKUP_S3_BUCKET GOOGLE_OAUTH_TOKEN_FILE <<< "$(python3 -c "
from dotenv import load_dotenv
import os
load_dotenv()
print(os.getenv('BACKUP_S3_BUCKET', '_'), os.getenv('GOOGLE_OAUTH_TOKEN_FILE', '_'))
")"
[ "$BACKUP_S3_BUCKET" = "_" ] && BACKUP_S3_BUCKET=""
[ "$GOOGLE_OAUTH_TOKEN_FILE" = "_" ] && GOOGLE_OAUTH_TOKEN_FILE=""

echo "Starting backup at $(date '+%Y-%m-%d %H:%M:%S')"

# Backup to local disk, keep 7 days
python3 scripts/backup_db.py --dir "$BACKUP_DIR" --prune 7

# Optionally upload to S3 (requires BACKUP_S3_BUCKET env var)
if [ -n "$BACKUP_S3_BUCKET" ]; then
  echo "Uploading to S3..."
  python3 scripts/backup_db.py --dir "$BACKUP_DIR" --s3
fi

# Optionally upload to Google Drive (requires GOOGLE_OAUTH_TOKEN_FILE +
# GOOGLE_DRIVE_BACKUP_FOLDER_ID)
if [ -n "$GOOGLE_OAUTH_TOKEN_FILE" ]; then
  echo "Uploading to Google Drive..."
  python3 scripts/backup_db.py --dir "$BACKUP_DIR" --drive
fi

if [ -n "$GOOGLE_OAUTH_TOKEN_FILE" ]; then
  python3 scripts/backup_opensearch.py --dir "$BACKUP_DIR/opensearch" --prune 7 --drive
else
  python3 scripts/backup_opensearch.py --dir "$BACKUP_DIR/opensearch" --prune 7
fi

echo "Backup complete at $(date '+%Y-%m-%d %H:%M:%S')"
