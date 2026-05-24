# Database Backup & Recovery

## Quick Start

**Manual backup:**
```bash
python scripts/backup_db.py
```
Saves to `backups/cancerbot_YYYYMMDD_HHMMSS.dump`

**Restore from backup:**
```bash
python scripts/restore_db.py backups/cancerbot_20250524_120000.dump
```

## Automated Daily Backups

**Option 1: Cron job (Linux/Mac)**

Make the script executable:
```bash
chmod +x scripts/daily_backup.sh
```

Add to crontab (runs at 2am daily):
```bash
crontab -e
# Add this line:
0 2 * * * /path/to/cancerbot/scripts/daily_backup.sh >> /path/to/cancerbot/backups/cron.log 2>&1
```

**Option 2: Docker Compose**

Add a backup service to your `docker-compose.yml`:
```yaml
backup:
  image: postgres:15
  entrypoint: sh -c 'while true; do sleep 86400; python /app/scripts/backup_db.py; done'
  volumes:
    - ./:/app
    - ./backups:/app/backups
  environment:
    - POSTGRES_URL=postgresql+asyncpg://user:pass@postgres:5432/cancerbot
  depends_on:
    - postgres
```

## S3 Backups

To automatically upload backups to S3:

1. Install boto3:
   ```bash
   pip install boto3
   ```

2. Configure AWS credentials (standard methods):
   ```bash
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   ```
   Or use IAM roles if running on EC2/ECS.

3. Set the S3 bucket in `.env`:
   ```
   BACKUP_S3_BUCKET=my-backup-bucket
   ```

4. Backups will now upload automatically:
   ```bash
   python scripts/backup_db.py --s3
   ```

## Retention

Keep the last N backups (deletes old ones):
```bash
python scripts/backup_db.py --prune 7  # Keep 7 backups
```

The `daily_backup.sh` script includes `--prune 7` by default.

## Monitoring

Check backup status:
```bash
ls -lh backups/
```

Check cron logs (if using cron):
```bash
tail -f backups/cron.log
```

## Recovery

To restore a backup:
```bash
python scripts/restore_db.py backups/cancerbot_20250524_120000.dump
```

⚠️ **WARNING**: This will overwrite the current database. You'll be prompted to confirm.

## Testing Recovery

Test your backup/restore process regularly:
```bash
# 1. Backup current database
python scripts/backup_db.py

# 2. In a test environment, restore and verify
python scripts/restore_db.py backups/cancerbot_YYYYMMDD_HHMMSS.dump
```
