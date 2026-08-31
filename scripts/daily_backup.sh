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
BACKUP_S3_BUCKET="$(python3 -c "
from dotenv import load_dotenv
import os
load_dotenv()
print(os.getenv('BACKUP_S3_BUCKET', ''))
")"

echo "Starting backup at $(date '+%Y-%m-%d %H:%M:%S')"

# Backup to local disk, keep 7 days
python3 scripts/backup_db.py --dir "$BACKUP_DIR" --prune 7

# Optionally upload to S3 (requires BACKUP_S3_BUCKET env var)
if [ -n "$BACKUP_S3_BUCKET" ]; then
  echo "Uploading to S3..."
  python3 scripts/backup_db.py --dir "$BACKUP_DIR" --s3
fi

python3 scripts/backup_opensearch.py --dir "$BACKUP_DIR/opensearch" --prune 7

echo "Backup complete at $(date '+%Y-%m-%d %H:%M:%S')"
