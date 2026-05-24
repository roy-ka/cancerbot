#!/usr/bin/env python3
"""
Restore PostgreSQL database from backup.

Usage:
  python scripts/restore_db.py backups/cancerbot_20250524_120000.dump
"""

import subprocess
import os
import sys
from pathlib import Path
import argparse


def get_postgres_url():
    """Extract connection details from POSTGRES_URL env var."""
    url = os.getenv("POSTGRES_URL")
    if not url:
        raise ValueError("POSTGRES_URL not set")

    import urllib.parse
    parsed = urllib.parse.urlparse(url.replace("+asyncpg", ""))
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "db": parsed.path.lstrip("/"),
    }


def restore_from_file(backup_path: Path):
    """Restore database from SQL dump file."""
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    db = get_postgres_url()

    print(f"⚠️  WARNING: This will overwrite the database '{db['db']}'")
    print(f"Backup file: {backup_path}")
    response = input("Type 'yes' to continue: ")

    if response != "yes":
        print("Cancelled")
        sys.exit(0)

    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"]

    cmd = [
        "pg_restore",
        f"--host={db['host']}",
        f"--port={db['port']}",
        f"--username={db['user']}",
        "--clean",  # Drop existing objects
        "--if-exists",  # Don't fail if objects don't exist
        "--no-acl",  # Skip ACL restoration
        "--no-owner",  # Skip ownership
        f"--dbname={db['db']}",
        str(backup_path),
    ]

    print("Restoring...")
    result = subprocess.run(cmd, env=env, check=False)

    if result.returncode == 0:
        print(f"✓ Database restored from {backup_path.name}")
    else:
        print(f"✗ Restore failed with exit code {result.returncode}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Restore PostgreSQL database from backup")
    parser.add_argument("backup_file", help="Path to .dump file")
    args = parser.parse_args()

    try:
        restore_from_file(Path(args.backup_file))
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
