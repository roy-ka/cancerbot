from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import re
import xml.etree.ElementTree as ET
from defusedxml.ElementTree import fromstring as _safe_fromstring


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None:
        return None
    t = (el.text or "").strip()
    return t or None


def _all_text(el: Optional[ET.Element]) -> Optional[str]:
    """
    Get full text content including nested tags, normalized.
    """
    if el is None:
        return None
    t = "".join(el.itertext()).strip()
    return " ".join(t.split()) or None


def _find(el: ET.Element, path: str) -> Optional[ET.Element]:
    return el.find(path)


def _findall(el: ET.Element, path: str) -> List[ET.Element]:
    return list(el.findall(path))


def _strip_tags(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    # Remove any embedded XML/HTML tags that sometimes appear inside PubMed abstracts.
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _to_et_root(xml: Union[str, bytes, ET.Element, Any]) -> ET.Element:
    """Normalize various XML inputs into an ElementTree root element.

    Supported inputs:
      - str / bytes containing XML
      - xml.etree.ElementTree.Element
      - BeautifulSoup Tag-like objects (we fall back to `str(obj)`)

    Note: If you pass a BeautifulSoup Tag that is *not* a <PubmedArticle> (e.g. just <Article>),
    the converter will still work but fields that live outside <Article> (PMID, keywords, etc.)
    may be missing.
    """
    if isinstance(xml, ET.Element):
        return xml

    if isinstance(xml, (bytes, bytearray)):
        return _safe_fromstring(bytes(xml))

    if isinstance(xml, str):
        return _safe_fromstring(xml)

    # Best-effort support for BeautifulSoup Tag or similar objects.
    # BeautifulSoup tags stringify to their XML/HTML.
    try:
        xml_str = str(xml)
        if not xml_str.strip().startswith("<"):
            raise TypeError
        return _safe_fromstring(xml_str)
    except Exception as e:
        raise TypeError(
            "pubmed_article_xml_to_source() expected XML as str/bytes/Element (or a Tag that stringifies to XML). "
            f"Got: {type(xml)}"
        ) from e


@dataclass
class Source:
    source_type: str  # e.g. "pubmed"
    pmid: Optional[str]
    doi: Optional[str]
    title: Optional[str]
    journal: Optional[str]
    iso_abbrev: Optional[str]
    pub_year: Optional[str]
    pub_month: Optional[str]
    pub_day: Optional[str]
    language: Optional[str]
    authors: List[str]
    affiliations: List[str]
    keywords: List[str]
    abstract_en: Optional[str]
    abstract_en_sections: List[Dict[str, str]]
    abstract_other: List[Dict[str, str]]
    publication_status: Optional[str]

    pub_types: Optional[List[str]]
    url: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def pubmed_article_xml_to_source(xml: Union[str, bytes]) -> Dict[str, Any]:
    """
    Convert a PubMed <PubmedArticle> XML string to a normalized 'source' dict.

    Input can be:
      - the full <PubmedArticle>...</PubmedArticle>
      - or a larger XML blob containing PubmedArticle (we'll locate the first one)
    """
    root = _to_et_root(xml)

    # Handle blobs that wrap PubmedArticleSet, etc.
    # Also allow passing a bare <Article> element (fields outside <Article> may be missing).
    pubmed_article = root
    if root.tag == "PubmedArticle":
        pass
    elif root.tag == "Article":
        # We'll treat this as an <Article> subtree.
        pubmed_article = root
    else:
        found = root.find(".//PubmedArticle")
        if found is not None:
            pubmed_article = found
        else:
            found_article = root.find(".//Article")
            if found_article is not None:
                pubmed_article = found_article
            else:
                raise ValueError("Could not find <PubmedArticle> or <Article> element in the XML input.")

    if pubmed_article.tag == "PubmedArticle":
        mc = _find(pubmed_article, "./MedlineCitation")
        article = _find(pubmed_article, "./MedlineCitation/Article")
    else:
        # pubmed_article is actually an <Article> element
        mc = None
        article = pubmed_article

    pmid = _text(_find(pubmed_article, "./MedlineCitation/PMID")) if pubmed_article.tag == "PubmedArticle" else None
    title = _all_text(_find(article, "./ArticleTitle")) if article is not None else None

    # DOI can appear in ELocationID or in PubmedData/ArticleIdList
    doi = None
    if article is not None:
        doi = _text(_find(article, "./ELocationID[@EIdType='doi']"))
    if (not doi) and (pubmed_article.tag == "PubmedArticle"):
        doi = _text(_find(pubmed_article, "./PubmedData/ArticleIdList/ArticleId[@IdType='doi']"))

    journal = _all_text(_find(article, "./Journal/Title")) if article is not None else None
    iso_abbrev = _text(_find(article, "./Journal/ISOAbbreviation")) if article is not None else None

    pub_date = _find(article, "./Journal/JournalIssue/PubDate") if article is not None else None
    pub_year = _text(_find(pub_date, "./Year")) if pub_date is not None else None
    pub_month = _text(_find(pub_date, "./Month")) if pub_date is not None else None
    pub_day = _text(_find(pub_date, "./Day")) if pub_date is not None else None

    language = _text(_find(article, "./Language")) if article is not None else None

    # Authors and affiliations
    authors: List[Dict[str, Optional[str]]] = []
    affiliations: List[str] = []
    if article is not None:
        for a in _findall(article, "./AuthorList/Author[@ValidYN='Y']"):
            last = _text(_find(a, "./LastName"))
            fore = _text(_find(a, "./ForeName"))
            initials = _text(_find(a, "./Initials"))
            if last or fore or initials:
                authors.append({"last": last, "fore": fore, "initials": initials})

            for aff in _findall(a, "./AffiliationInfo/Affiliation"):
                at = _all_text(aff)
                if at:
                    affiliations.append(at)

    # Keywords
    keywords: List[str] = []
    if mc is not None:
        for kw in _findall(mc, "./KeywordList/Keyword"):
            kt = _all_text(kw)
            if kt:
                keywords.append(kt)

    language = _text(_find(article, "./Language")) if article is not None else None

    pub_types: Optional[List[str]] = None
    if article is not None:
        pts = []
        for pt in _findall(article, "./PublicationTypeList/PublicationType"):
            t = _all_text(pt)
            if t:
                pts.append(t)
        pub_types = pts or None

    # English abstract: MedlineCitation/Article/Abstract/AbstractText
    abstract_en_sections: List[Dict[str, str]] = []
    abstract_en_full_parts: List[str] = []
    if article is not None:
        abstract = _find(article, "./Abstract")
        if abstract is not None:
            for at in _findall(abstract, "./AbstractText"):
                label = at.attrib.get("Label") or at.attrib.get("NlmCategory") or "UNLABELED"
                txt = _strip_tags(_all_text(at))
                if txt:
                    abstract_en_sections.append({"label": label, "text": txt})
                    abstract_en_full_parts.append(txt)

    abstract_en = "\n\n".join(
        [f"{s['label']}: {s['text']}" for s in abstract_en_sections]
    ) if abstract_en_sections else None

    abstract_plain = None
    if abstract_en_sections:
        parts = [s["text"] for s in abstract_en_sections if s.get("text")]
        abstract_plain = "\n\n".join(parts) if parts else None

    # Other-language abstracts (e.g., Turkish in OtherAbstract)
    abstract_other: List[Dict[str, str]] = []
    if mc is not None:
        for oa in _findall(mc, "./OtherAbstract"):
            lang = oa.attrib.get("Language") or "unknown"
            for at in _findall(oa, "./AbstractText"):
                label = at.attrib.get("Label") or at.attrib.get("NlmCategory") or "UNLABELED"
                txt = _all_text(at)
                if txt:
                    abstract_other.append({"language": lang, "label": label, "text": txt})

    publication_status = (
        _text(_find(pubmed_article, "./PubmedData/PublicationStatus"))
        if pubmed_article.tag == "PubmedArticle"
        else None
    )


    # Build a citation-style title line like: "Last I et al. Article title. 2026."
    citation_author = None
    if authors:
        first = authors[0]
        last = (first.get("last") or "").strip() or None
        ini = (first.get("initials") or "").strip() or None
        if last and ini:
            citation_author = f"{last} {ini}"
        elif last:
            citation_author = last

        if citation_author and len(authors) > 1:
            citation_author = f"{citation_author} et al."

    year = pub_year
    title_line_parts = []
    if citation_author:
        title_line_parts.append(citation_author)
    if title:
        title_line_parts.append(f"{title}." if not title.endswith(".") else title)
    if year:
        title_line_parts.append(f"{year}.")
    citation_title_line = " ".join(title_line_parts) if title_line_parts else title

    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None

    # Stable id
    if pmid:
        src_id = f"src_pmid_{pmid}"
    elif doi:
        src_id = "src_doi_" + re.sub(r"[^A-Za-z0-9]+", "_", doi).strip("_")
    else:
        src_id = "src_unknown"

    content_for_embedding = None
    if citation_title_line and abstract_plain:
        content_for_embedding = f"{citation_title_line}\n\n{abstract_plain}"
    elif citation_title_line:
        content_for_embedding = citation_title_line
    elif abstract_plain:
        content_for_embedding = abstract_plain

    abstract_fetched_at = datetime.now(timezone.utc).isoformat()

    src = Source(
        source_type="pubmed",
        pmid=pmid,
        doi=doi,
        title=title,
        journal=journal,
        iso_abbrev=iso_abbrev,
        pub_year=pub_year,
        pub_month=pub_month,
        pub_day=pub_day,
        language=language,
        authors=authors,
        affiliations=affiliations,
        keywords=keywords,
        abstract_en=abstract_en,
        abstract_en_sections=abstract_en_sections,
        abstract_other=abstract_other,
        publication_status=publication_status,
        pub_types=pub_types,
        url=url,
    )

    # Align output schema to the project's expected source format
    out: Dict[str, Any] = {
        "source_type": "pubmed",
        "title": citation_title_line,
        "pmid": pmid,
        "doi": doi,
        "url": url,
        "claim_ids": [],
        "tags": ["primary_academic"],
        "id": src_id,
        "content_for_embedding": content_for_embedding,
        "abstract": abstract_plain,
        "year": year,
        "journal": journal,
        "authors": [
            " ".join([p for p in [(a.get('fore') or '').strip() or None, (a.get('last') or '').strip() or None] if p])
            for a in authors
        ] or None,
        "original": None,
        "pub_types": pub_types,
        "evidence_score_0_5": None,
        "evidence_strength": None,
        "chatbot_data_quality_score_0_100": None,
        "match_similarity": None,
        "original_citation_line": None,
        "search_query_used": None,
        "search_queries_tried": None,
        "low_confidence_match": None,
        "original_unresolved": None,
        "abstract_source": "pubmed",
        "abstract_fetched_at": abstract_fetched_at,
    }

    return out