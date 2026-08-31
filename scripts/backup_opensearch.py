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
  python scripts/backup_opensearch.py --prune 7    # Keep only the last 7 backup runs
"""

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.db_connector import dbConnector


def backup_index(index_name: str, output_dir: Path, timestamp: str) -> dict:
    """Dump one index's mapping+settings and documents to output_dir.

    Returns {"docs": int, "mapping_path": Path, "docs_path": Path}.
    """
    from opensearchpy.helpers import scan

    dbConnector._initialize()
    client = dbConnector.db_client
    if not client:
        raise RuntimeError("OpenSearch client not initialized (check OPENSEARCH_URL / OPENSEARCH_INITIAL_ADMIN_PASSWORD)")

    output_dir.mkdir(parents=True, exist_ok=True)

    mapping_path = output_dir / f"{index_name}_{timestamp}.mapping.json"
    docs_path = output_dir / f"{index_name}_{timestamp}.jsonl.gz"

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


def backup_opensearch(output_dir: Path) -> dict:
    """Backup every known sources/claims index. Returns a per-index result dict."""
    dbConnector._initialize()
    if not dbConnector._model:
        raise RuntimeError("dbConnector has no active model (OpenSearch not configured)")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    index_names = [dbConnector._model["sources_index"], dbConnector._model["claims_index"]]

    results = {}
    for index_name in index_names:
        if not dbConnector.db_client.indices.exists(index=index_name):
            print(f"  Skipping {index_name}: does not exist")
            continue
        result = backup_index(index_name, output_dir, timestamp)
        size_mb = result["docs_path"].stat().st_size / (1024 * 1024)
        print(f"✓ {index_name}: {result['docs']} docs -> {result['docs_path'].name} ({size_mb:.1f} MB)")
        results[index_name] = result

    return results


_TIMESTAMP_RE = re.compile(r"_(\d{8}_\d{6})\.")


def prune_backups(backup_dir: Path, keep_count: int):
    """Delete files from old backup runs, keeping the most recent N runs.

    One run writes multiple files (mapping.json + jsonl.gz per index), all
    sharing the same timestamp — prune by run, not by file, or a run could
    be left with its docs file but no mapping (or vice versa).
    """
    timestamps = sorted({
        m.group(1)
        for f in backup_dir.glob("*")
        if (m := _TIMESTAMP_RE.search(f.name))
    })

    if len(timestamps) <= keep_count:
        print(f"✓ {len(timestamps)} backup run(s) exist (keeping {keep_count})")
        return

    to_delete = set(timestamps[:-keep_count])
    deleted = 0
    for f in backup_dir.glob("*"):
        m = _TIMESTAMP_RE.search(f.name)
        if m and m.group(1) in to_delete:
            f.unlink()
            deleted += 1
    print(f"✓ Pruned {len(to_delete)} old backup run(s) ({deleted} files)")


def main():
    parser = argparse.ArgumentParser(description="Backup OpenSearch indices")
    parser.add_argument("--dir", default="backups/opensearch", help="Local backup directory")
    parser.add_argument("--prune", type=int, metavar="N", help="Keep only the last N backup runs")

    args = parser.parse_args()
    output_dir = Path(args.dir)

    try:
        results = backup_opensearch(output_dir)
        if not results:
            print("✗ No indices backed up (none exist)")
            sys.exit(1)

        if args.prune:
            prune_backups(output_dir, args.prune)

        print("✓ Backup complete")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
