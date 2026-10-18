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

## OpenSearch Backups

`scripts/backup_opensearch.py` (also run by `daily_backup.sh`) exports each search index into a per-date directory: `<index>_<HHMMSS>.mapping.json` (mapping + settings) and `<index>_<HHMMSS>.jsonl.gz` (the documents, embeddings included). The index only caches search results the app fetched while answering questions and refills with use, so restoring it is optional. It saves re-fetching and re-embedding everything.

`scripts/restore_opensearch.py` loads one of those directories back:
- It recreates each index from its saved mapping, with `number_of_replicas` forced to 0 because the cluster is a single node. A replica copied from an older two-node backup would otherwise leave the index yellow forever.
- It loads the documents under their original ids, so running it twice doesn't create duplicates.
- It refuses to overwrite an index that already has documents unless you pass `--replace`. An empty index, like the one the backend creates on startup, is replaced without asking.
- `--dry-run` shows what it would restore.

Locally (with OpenSearch from `docker compose up -d`):
```bash
python scripts/restore_opensearch.py backups/opensearch/2026-10-17 --dry-run
python scripts/restore_opensearch.py backups/opensearch/2026-10-17 --replace
```

On the production server, run it inside the backend container. That way it reaches OpenSearch over the in-network HTTPS address with the pinned CA, and the server's `.env` needs no OpenSearch settings. Mount the folder that holds the backup (here `./backups`) into the container. `backup/` and `backups/` are git- and docker-ignored, so dumps never end up in a commit or an image.
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot \
  run --rm --no-deps -v "$PWD/backups:/app/backups:ro" backend \
  python scripts/restore_opensearch.py backups/opensearch/2026-10-17 --replace
```
Run it after a deploy has started OpenSearch. The backend's own index creation on startup is harmless, since that index is empty.
