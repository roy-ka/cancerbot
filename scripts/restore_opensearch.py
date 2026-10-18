#!/usr/bin/env python3
"""
Restore OpenSearch indices from backups made by scripts/backup_opensearch.py.

A backup run writes, per index, `<index>_<HHMMSS>.mapping.json` (mappings +
settings) and `<index>_<HHMMSS>.jsonl.gz` (one {"_id", "_source"} document
per line) into a per-date directory. This recreates each index from its
mapping and bulk-loads its documents under their original ids, so running
it twice doesn't create duplicates.

Only the indices the app currently uses (dbConnector's sources and claims
index names) are restored; anything else in the directory is skipped. When a
directory holds several runs from the same day, the latest one per index is
used.

Usage:
  python scripts/restore_opensearch.py backups/opensearch/2026-10-17 --dry-run
  python scripts/restore_opensearch.py backups/opensearch/2026-10-17 --replace

On the production server, run it inside the backend container so it uses
the in-network HTTPS address and the pinned CA (see BACKUP.md):
  docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot \\
    run --rm --no-deps -v "$PWD/backups:/app/backups:ro" backend \\
    python scripts/restore_opensearch.py backups/opensearch/2026-10-17 --replace
"""

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.db_connector import dbConnector

# Index settings OpenSearch reports for an existing index but rejects (or
# would wrongly copy) when creating a new one.
_READ_ONLY_SETTINGS = frozenset({"uuid", "creation_date", "provided_name", "version", "resize", "history"})

_BACKUP_NAME_RE = re.compile(r"^(?P<index>.+)_(?P<time>\d{6})\.mapping\.json$")

BULK_CHUNK_SIZE = 500


def clean_settings(settings: dict) -> dict:
    """Index settings from a backup, made safe to create an index with.

    Drops the read-only fields and forces number_of_replicas to 0: the
    cluster is a single node (docker-compose.yml), so a replica copied from
    the old two-node cluster could never be assigned.
    """
    index_settings = {
        key: value
        for key, value in (settings.get("index") or {}).items()
        if key not in _READ_ONLY_SETTINGS
    }
    index_settings["number_of_replicas"] = "0"
    return {"index": index_settings}


def find_backups(backup_dir: Path, wanted_indices: list[str]) -> dict[str, tuple[Path, Path]]:
    """Map each wanted index to its (mapping_path, docs_path) in backup_dir,
    taking the latest run when there are several. Indices with no backup, or
    with a mapping but no documents file, are left out."""
    latest: dict[str, tuple[str, Path, Path]] = {}
    for mapping_path in backup_dir.glob("*.mapping.json"):
        match = _BACKUP_NAME_RE.match(mapping_path.name)
        if not match or match["index"] not in wanted_indices:
            continue
        docs_path = backup_dir / f"{match['index']}_{match['time']}.jsonl.gz"
        if not docs_path.exists():
            print(f"  Skipping {mapping_path.name}: no matching {docs_path.name}")
            continue
        current = latest.get(match["index"])
        if current is None or match["time"] > current[0]:
            latest[match["index"]] = (match["time"], mapping_path, docs_path)
    return {index: (mapping, docs) for index, (_, mapping, docs) in latest.items()}


def _read_docs(docs_path: Path, index_name: str):
    with gzip.open(docs_path, "rt") as f:
        for line in f:
            if not line.strip():
                continue
            doc = json.loads(line)
            yield {"_op_type": "index", "_index": index_name, "_id": doc["_id"], "_source": doc["_source"]}


def count_backup_docs(docs_path: Path) -> int:
    with gzip.open(docs_path, "rt") as f:
        return sum(1 for line in f if line.strip())


def restore_index(client, index_name: str, mapping_path: Path, docs_path: Path, *, replace: bool) -> dict:
    """Recreate one index from its backup and load its documents.

    Refuses to touch an index that already holds documents unless `replace`
    is set. An existing empty index (e.g. the one the backend creates on
    startup) is recreated without asking, so the restored mapping is the one
    that applies.

    Returns {"loaded": int, "errors": [str], "count": int}.
    """
    from opensearchpy.helpers import bulk

    if client.indices.exists(index=index_name):
        existing = client.count(index=index_name)["count"]
        if existing and not replace:
            raise RuntimeError(
                f"{index_name} already has {existing} documents — pass --replace to delete it and restore"
            )
        client.indices.delete(index=index_name)

    definition = json.loads(mapping_path.read_text())
    client.indices.create(
        index=index_name,
        body={"settings": clean_settings(definition.get("settings") or {}), "mappings": definition["mappings"]},
    )

    loaded, errors = bulk(
        client,
        _read_docs(docs_path, index_name),
        chunk_size=BULK_CHUNK_SIZE,
        raise_on_error=False,
        stats_only=False,
    )
    client.indices.refresh(index=index_name)
    return {
        "loaded": loaded,
        "errors": [str(e) for e in errors],
        "count": client.count(index=index_name)["count"],
    }


def restore_opensearch(backup_dir: Path, *, replace: bool = False, dry_run: bool = False) -> dict:
    """Restore every app index found in backup_dir. Returns a per-index result dict."""
    if not backup_dir.is_dir():
        raise RuntimeError(f"{backup_dir} is not a directory")

    dbConnector._initialize()
    if not dbConnector._model or not dbConnector.db_client:
        raise RuntimeError("OpenSearch not configured (check OPENSEARCH_URL / OPENSEARCH_INITIAL_ADMIN_PASSWORD)")

    wanted = [dbConnector._model["sources_index"], dbConnector._model["claims_index"]]
    backups = find_backups(backup_dir, wanted)
    if not backups:
        raise RuntimeError(f"no backups for {', '.join(wanted)} in {backup_dir}")

    results = {}
    for index_name in wanted:
        if index_name not in backups:
            print(f"  No backup for {index_name} — left as it is")
            continue
        mapping_path, docs_path = backups[index_name]
        if dry_run:
            docs = count_backup_docs(docs_path)
            print(f"  Would restore {index_name}: {docs} docs from {docs_path.name}")
            results[index_name] = {"docs": docs}
            continue
        result = restore_index(dbConnector.db_client, index_name, mapping_path, docs_path, replace=replace)
        print(f"✓ {index_name}: {result['loaded']} docs loaded, {result['count']} in the index")
        for error in result["errors"][:5]:
            print(f"  ✗ {error}")
        if len(result["errors"]) > 5:
            print(f"  ✗ ... and {len(result['errors']) - 5} more failed documents")
        results[index_name] = result
    return results


def main():
    parser = argparse.ArgumentParser(description="Restore OpenSearch indices from a backup_opensearch.py run")
    parser.add_argument("backup_dir", help="A backup date directory, e.g. backups/opensearch/2026-10-17")
    parser.add_argument("--replace", action="store_true", help="Delete and replace indices that already hold documents")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be restored without writing anything")
    args = parser.parse_args()

    try:
        results = restore_opensearch(Path(args.backup_dir), replace=args.replace, dry_run=args.dry_run)
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)

    if any(r.get("errors") for r in results.values()):
        print("✗ Restore finished with failed documents (see above)")
        sys.exit(1)
    print("✓ Dry run complete — nothing written" if args.dry_run else "✓ Restore complete")


if __name__ == "__main__":
    main()
