#!/usr/bin/env python3
"""
Backup PostgreSQL database to local file or S3.

Usage:
  python scripts/backup_db.py              # Backup to local backups/
  python scripts/backup_db.py --s3         # Backup to S3 (requires AWS credentials)
  python scripts/backup_db.py --drive      # Upload to Google Drive (requires
                                            #   GOOGLE_SERVICE_ACCOUNT_FILE +
                                            #   GOOGLE_DRIVE_BACKUP_FOLDER_ID)
  python scripts/backup_db.py --prune 7    # Keep only last 7 backups
"""

import subprocess
import os
import sys
from pathlib import Path
from datetime import datetime
import argparse
from dotenv import load_dotenv

load_dotenv()


def get_postgres_url():
    """Extract connection details from POSTGRES_URL env var."""
    url = os.getenv("POSTGRES_URL")
    if not url:
        raise ValueError("POSTGRES_URL not set")

    # Parse postgresql+asyncpg://user:pass@host:port/db
    import urllib.parse
    parsed = urllib.parse.urlparse(url.replace("+asyncpg", ""))
    try:
        port = parsed.port or 5432
    except ValueError as e:
        # Don't leak the password: report structure only (lengths + delimiter
        # counts/positions), enough to tell whether netloc got truncated early
        # (e.g. by an unencoded '/' or '@' inside the password) without ever
        # printing the password itself.
        # e's own message embeds the unparseable substring verbatim (from
        # urllib.parse's port property) — deliberately not included below.
        netloc = parsed.netloc
        raise ValueError(
            f"POSTGRES_URL port could not be parsed as an integer | "
            f"url_len={len(url)} netloc_len={len(netloc)} "
            f"at_count={netloc.count('@')} slash_count={netloc.count('/')} "
            f"colon_positions={[i for i, c in enumerate(netloc) if c == ':']} "
            f"at_positions={[i for i, c in enumerate(netloc) if c == '@']}"
        ) from None
    return {
        "host": parsed.hostname,
        "port": port,
        "user": parsed.username,
        "password": parsed.password,
        "db": parsed.path.lstrip("/"),
    }


def backup_to_file(output_path: Path):
    """Dump database to SQL file."""
    db = get_postgres_url()

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    cmd = [
        "pg_dump",
        f"--host={db['host']}",
        f"--port={db['port']}",
        f"--username={db['user']}",
        "--format=custom",  # Compressed binary format
        "--verbose",
        db["db"],
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        result = subprocess.run(cmd, stdout=f, env=env, check=True)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"✓ Backup saved: {output_path} ({size_mb:.1f} MB)")
    return output_path


def backup_to_s3(local_path: Path, s3_bucket: str, s3_key: str):
    """Upload backup to S3."""
    try:
        import boto3
    except ImportError:
        print("Error: boto3 not installed. Run: pip install boto3")
        sys.exit(1)

    s3 = boto3.client("s3")
    s3.upload_file(str(local_path), s3_bucket, s3_key)
    print(f"✓ Uploaded to s3://{s3_bucket}/{s3_key}")


def backup_to_drive(local_path: Path):
    """Upload backup to Google Drive via a service account."""
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    folder_id = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID")
    if not service_account_file or not folder_id:
        print("Error: GOOGLE_SERVICE_ACCOUNT_FILE and/or GOOGLE_DRIVE_BACKUP_FOLDER_ID not set")
        sys.exit(1)

    from scripts.backup_drive import upload_to_drive
    file_id = upload_to_drive(local_path, folder_id, service_account_file)
    print(f"✓ Uploaded to Google Drive (file id: {file_id})")


def prune_backups(backup_dir: Path, keep_count: int):
    """Delete old backups, keeping the most recent N."""
    backups = sorted(backup_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime)

    if len(backups) <= keep_count:
        print(f"✓ {len(backups)} backups exist (keeping {keep_count})")
        return

    to_delete = backups[:-keep_count]
    for backup in to_delete:
        backup.unlink()
        print(f"  Deleted old backup: {backup.name}")

    print(f"✓ Pruned to {keep_count} recent backups")


def main():
    parser = argparse.ArgumentParser(description="Backup PostgreSQL database")
    parser.add_argument("--s3", action="store_true", help="Upload to S3")
    parser.add_argument("--drive", action="store_true", help="Upload to Google Drive")
    parser.add_argument("--prune", type=int, metavar="N", help="Keep only last N backups")
    parser.add_argument("--dir", default="backups", help="Local backup directory")

    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(args.dir) / f"cancerbot_{timestamp}.dump"

    try:
        backup_to_file(backup_path)

        if args.s3:
            s3_bucket = os.getenv("BACKUP_S3_BUCKET")
            if not s3_bucket:
                print("Error: BACKUP_S3_BUCKET not set")
                sys.exit(1)
            s3_key = f"backups/{backup_path.name}"
            backup_to_s3(backup_path, s3_bucket, s3_key)

        if args.drive:
            backup_to_drive(backup_path)

        if args.prune:
            prune_backups(Path(args.dir), args.prune)

        print("✓ Backup complete")

    except subprocess.CalledProcessError as e:
        print(f"✗ Backup failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
