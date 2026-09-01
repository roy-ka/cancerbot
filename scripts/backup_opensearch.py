#!/usr/bin/env python3
"""
Backup OpenSearch indices to local gzip-compressed NDJSON files.

The docker-compose OpenSearch cluster has no `path.repo`/shared snapshot
volume configured, so the native Snapshot API isn't available without an
infra change. This does a document-level export instead: for each known
index, dump its mapping+settings (needed to recreate the index) and scroll
every document to a gzip NDJSON file.

Usage:
  python scripts/backup_opensearch.py              # Backup to local backups/opensearch/
  python scripts/backup_opensearch.py --drive      # Also upload to Google Drive (requires
                                                     #   GOOGLE_OAUTH_TOKEN_FILE +
                                                     #   GOOGLE_DRIVE_BACKUP_FOLDER_ID)
  python scripts/backup_opensearch.py --prune 7    # Keep only the last 7 backup dates
"""

import argparse
import gzip
import json
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.db_connector import dbConnector


def backup_index(index_name: str, output_dir: Path, time_str: str) -> dict:
    """Dump one index's mapping+settings and documents to output_dir.

    Returns {"docs": int, "mapping_path": Path, "docs_path": Path}.
    """
    from opensearchpy.helpers import scan

    dbConnector._initialize()
    client = dbConnector.db_client
    if not client:
        raise RuntimeError("OpenSearch client not initialized (check OPENSEARCH_URL / OPENSEARCH_INITIAL_ADMIN_PASSWORD)")

    output_dir.mkdir(parents=True, exist_ok=True)

    mapping_path = output_dir / f"{index_name}_{time_str}.mapping.json"
    docs_path = output_dir / f"{index_name}_{time_str}.jsonl.gz"

    index_def = client.indices.get(index=index_name)[index_name]
    with open(mapping_path, "w") as f:
        json.dump(
            {"mappings": index_def["mappings"], "settings": index_def["settings"]},
            f,
        )

    doc_count = 0
    with gzip.open(docs_path, "wt") as f:
        for hit in scan(client, index=index_name, query={"query": {"match_all": {}}}):
            f.write(json.dumps({"_id": hit["_id"], "_source": hit["_source"]}) + "\n")
            doc_count += 1

    return {"docs": doc_count, "mapping_path": mapping_path, "docs_path": docs_path}


def backup_opensearch(output_dir: Path, date_str: str | None = None) -> dict:
    """Backup every known sources/claims index into output_dir/date_str/.

    Returns a per-index result dict.
    """
    dbConnector._initialize()
    if not dbConnector._model:
        raise RuntimeError("dbConnector has no active model (OpenSearch not configured)")

    now = datetime.now()
    date_str = date_str or now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    date_dir = output_dir / date_str
    index_names = [dbConnector._model["sources_index"], dbConnector._model["claims_index"]]

    results = {}
    for index_name in index_names:
        if not dbConnector.db_client.indices.exists(index=index_name):
            print(f"  Skipping {index_name}: does not exist")
            continue
        result = backup_index(index_name, date_dir, time_str)
        size_mb = result["docs_path"].stat().st_size / (1024 * 1024)
        print(f"✓ {index_name}: {result['docs']} docs -> {result['docs_path'].name} ({size_mb:.1f} MB)")
        results[index_name] = result

    return results


def backup_to_drive(results: dict, date_str: str):
    """Upload every file from this run's results to Google Drive under your own
    account (OAuth), into a per-date subfolder of GOOGLE_DRIVE_BACKUP_FOLDER_ID."""
    token_file = os.getenv("GOOGLE_OAUTH_TOKEN_FILE")
    folder_id = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID")
    if not token_file or not folder_id:
        print("Error: GOOGLE_OAUTH_TOKEN_FILE and/or GOOGLE_DRIVE_BACKUP_FOLDER_ID not set")
        sys.exit(1)

    from scripts.backup_drive import upload_to_drive
    for result in results.values():
        for path in (result["mapping_path"], result["docs_path"]):
            file_id = upload_to_drive(path, folder_id, token_file, subfolder=date_str)
            print(f"✓ Uploaded {path.name} to Google Drive (file id: {file_id})")


def prune_backups(backup_dir: Path, keep_count: int):
    """Delete old date subdirectories under backup_dir, keeping the most recent N.

    Backups live in per-date subdirectories (backup_dir/YYYY-MM-DD/*), so
    pruning removes whole date directories, not individual files — a
    partially-pruned date dir could otherwise look like an incomplete run.
    """
    date_dirs = sorted(d for d in backup_dir.glob("*") if d.is_dir())

    if len(date_dirs) <= keep_count:
        print(f"✓ {len(date_dirs)} backup date(s) exist (keeping {keep_count})")
        return

    to_delete = date_dirs[:-keep_count]
    for date_dir in to_delete:
        for f in date_dir.iterdir():
            f.unlink()
        date_dir.rmdir()
        print(f"  Deleted old backup date: {date_dir.name}")

    print(f"✓ Pruned to {keep_count} recent backup date(s)")


def main():
    parser = argparse.ArgumentParser(description="Backup OpenSearch indices")
    parser.add_argument("--dir", default="backups/opensearch", help="Local backup directory")
    parser.add_argument("--drive", action="store_true", help="Upload to Google Drive")
    parser.add_argument("--prune", type=int, metavar="N", help="Keep only the last N backup runs")

    args = parser.parse_args()
    output_dir = Path(args.dir)
    date_str = datetime.now().strftime("%Y-%m-%d")

    try:
        results = backup_opensearch(output_dir, date_str)
        if not results:
            print("✗ No indices backed up (none exist)")
            sys.exit(1)

        if args.drive:
            backup_to_drive(results, date_str)

        if args.prune:
            prune_backups(output_dir, args.prune)

        print("✓ Backup complete")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
