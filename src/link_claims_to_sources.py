import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
PMID_RE = re.compile(r"\bpmid[:\s]*([0-9]{6,10})\b", re.I)
URL_RE = re.compile(r"https?://[^\s)>\"]+", re.I)

def _norm_doi(doi: str) -> str:
    doi = doi.strip()
    doi = doi.lower()
    doi = doi.replace("doi:", "").strip()
    return doi

def _norm_pmid(pmid: str) -> str:
    return str(pmid).strip()

def _norm_url(url: str) -> str:
    url = url.strip()
    # keep stable canonical form
    url = url.rstrip("/")
    return url

def _extract_evidence_keys_from_claim(claim: dict) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Returns: (dois, pmids, urls)

    Supports these evidence encodings inside claim["key_evidence"] entries:
      - identifier: "doi:..." | "pmid:..." | "url:..."
      - direct fields: {"doi": "..."}, {"pmid": "..."}, {"link": "..."} or {"url": "..."}
      - citations containing DOI/PMID/URL strings
    """
    dois: Set[str] = set()
    pmids: Set[str] = set()
    urls: Set[str] = set()

    key_evidence = claim.get("key_evidence") or []
    for ev in key_evidence:
        if not isinstance(ev, dict):
            continue

        # 1) identifier field (preferred, explicit)
        ident = ev.get("identifier")
        if isinstance(ident, str) and ident.strip():
            s = ident.strip()
            low = s.lower()
            if low.startswith("doi:"):
                # allow identifier to be either "doi:10...." or just "doi: ..."
                dois.add(_norm_doi(s))
            elif low.startswith("pmid:"):
                pmids.add(_norm_pmid(s.split(":", 1)[1]))
            elif low.startswith("url:"):
                urls.add(_norm_url(s.split(":", 1)[1]))

        # 2) direct fields used by some of your claim objects
        doi_val = ev.get("doi")
        if isinstance(doi_val, str) and doi_val.strip():
            dois.add(_norm_doi(doi_val))

        pmid_val = ev.get("pmid")
        # pmid sometimes appears as int
        if pmid_val is not None and str(pmid_val).strip():
            pmids.add(_norm_pmid(pmid_val))

        # your claims sometimes store the URL under "link"
        link_val = ev.get("link")
        if isinstance(link_val, str) and link_val.strip():
            urls.add(_norm_url(link_val))

        url_val = ev.get("url")
        if isinstance(url_val, str) and url_val.strip():
            urls.add(_norm_url(url_val))

        # 3) parse the citation text for embedded identifiers
        cit = ev.get("citation") or ""
        if isinstance(cit, str) and cit.strip():
            for m in DOI_RE.findall(cit):
                dois.add(_norm_doi(m))
            for m in PMID_RE.findall(cit):
                pmids.add(_norm_pmid(m))
            for m in URL_RE.findall(cit):
                urls.add(_norm_url(m))

    return dois, pmids, urls

def link_claims_to_sources(
    claims_path: str,
    sources_path: str,
    out_sources_path: Optional[str] = None,
    backup: bool = True,
) -> Dict[str, int]:
    """
    Reads claims_canonical.jsonl + enriched_sources.jsonl.
    Updates sources' claim_ids by matching DOI/PMID/URL evidence.
    Writes updated JSONL to out_sources_path (or overwrites sources_path).

    Returns stats dict.
    """
    claims_file = Path(claims_path)
    sources_file = Path(sources_path)

    if out_sources_path is None:
        out_sources_file = sources_file
    else:
        out_sources_file = Path(out_sources_path)

    # 1) Load sources and build indices
    sources: List[dict] = []
    doi_to_idxs: Dict[str, List[int]] = {}
    pmid_to_idxs: Dict[str, List[int]] = {}
    url_to_idxs: Dict[str, List[int]] = {}

    with sources_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            src = json.loads(line)
            idx = len(sources)
            sources.append(src)

            doi = src.get("doi")
            pmid = src.get("pmid")
            url = src.get("url")

            if isinstance(doi, str) and doi.strip():
                doi_to_idxs.setdefault(_norm_doi(doi), []).append(idx)
            if pmid is not None:
                pmid_to_idxs.setdefault(_norm_pmid(pmid), []).append(idx)
            if isinstance(url, str) and url.strip():
                url_to_idxs.setdefault(_norm_url(url), []).append(idx)

    # 2) Walk claims and attach claim_ids to matching sources
    matched_claims = 0
    total_links_added = 0
    claims_seen = 0

    with claims_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            claim = json.loads(line)
            claims_seen += 1

            claim_id = claim.get("claim_id")
            if not isinstance(claim_id, str) or not claim_id.strip():
                continue

            dois, pmids, urls = _extract_evidence_keys_from_claim(claim)

            matched_source_idxs: Set[int] = set()
            for d in dois:
                matched_source_idxs.update(doi_to_idxs.get(d, []))
            for p in pmids:
                matched_source_idxs.update(pmid_to_idxs.get(p, []))
            for u in urls:
                matched_source_idxs.update(url_to_idxs.get(u, []))

            if not matched_source_idxs:
                continue

            matched_claims += 1
            for idx in matched_source_idxs:
                src = sources[idx]
                cur = src.get("claim_ids")
                if not isinstance(cur, list):
                    cur = []
                # dedupe while preserving existing order
                if claim_id not in cur:
                    cur.append(claim_id)
                    total_links_added += 1
                src["claim_ids"] = cur

    # 3) Write updated sources
    if backup and out_sources_file == sources_file:
        backup_path = sources_file.with_suffix(sources_file.suffix + ".bak")
        if not backup_path.exists():
            backup_path.write_text(sources_file.read_text(encoding="utf-8"), encoding="utf-8")

    with out_sources_file.open("w", encoding="utf-8") as f:
        for src in sources:
            f.write(json.dumps(src, ensure_ascii=False) + "\n")

    return {
        "claims_seen": claims_seen,
        "sources_seen": len(sources),
        "claims_matched_to_at_least_1_source": matched_claims,
        "total_claim_ids_added_to_sources": total_links_added,
    }

if __name__ == "__main__":
    stats = link_claims_to_sources(
        claims_path="data/claims_canonical.jsonl",
        sources_path="data/enriched_sources_merges.jsonl",
        out_sources_path=None,   # overwrite in place
        backup=True,
    )
    print("Done:", stats)