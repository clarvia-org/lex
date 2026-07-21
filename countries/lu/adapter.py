"""Luxembourg Casemates adapter — Stage 1A: lu/code-civil only."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode

from lxml import etree

from lex.adapters import LawRef, NormalizedLaw, SourceDocument
from lex.errors import ErrorCode, LexError
from lex.http import HttpClient
from lex.markdown import normalize_anchor

SPARQL_ENDPOINT = "http://data.legilux.public.lu/sparqlendpoint"
JOLUX = "http://data.legilux.public.lu/resource/ontology/jolux#"
AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13"
SCL_NS = "http://www.scl.lu"
NSMAP = {"akn": AKN_NS, "scl": SCL_NS}

CODE_CIVIL_ID = "lu/code-civil"
CODE_CIVIL_FRAGMENT = "eli/etat/leg/code/civil/"
COMPLEX_WORK_ELI = "http://data.legilux.public.lu/eli/etat/leg/code/civil"

BROWSER_SHELL_MARKERS = (
    "<app-root",
    "ng-version=",
    "window.location",
    "Enable JavaScript",
)

HIERARCHY_LEVELS = {
    "book": 1,
    "part": 1,
    "title": 2,
    "chapter": 3,
    "section": 4,
    "subsection": 5,
}


class LuxembourgAdapter:
    country_code = "lu"

    def discover(self, client: HttpClient) -> Sequence[LawRef]:
        payload = self._sparql(client, self._discovery_query())
        latest = self._select_latest_xml(payload)
        if latest is None:
            raise LexError(
                ErrorCode.LEX_NOT_FOUND,
                CODE_CIVIL_ID,
                "No XML consolidation found for Code civil",
            )
        work_uri, file_url = latest
        return [
            LawRef(
                id=CODE_CIVIL_ID,
                language="fr",
                source_url=file_url,
                official_id="Code civil",
                eli_uri=work_uri,
            )
        ]

    def fetch(self, ref: LawRef, client: HttpClient) -> SourceDocument:
        if ref.id != CODE_CIVIL_ID:
            raise LexError(
                ErrorCode.LEX_INVALID_ID,
                ref.id,
                "Stage 1A adapter only supports lu/code-civil",
            )

        # Prefer the discover-selected URL; re-resolve if stale.
        file_url = ref.source_url
        work_uri = ref.eli_uri or ""
        if not file_url or "/xml/" not in file_url:
            latest = self._select_latest_xml(self._sparql(client, self._discovery_query()))
            if latest is None:
                raise LexError(
                    ErrorCode.LEX_NOT_FOUND,
                    ref.id,
                    "No XML consolidation found for Code civil",
                )
            work_uri, file_url = latest

        response = client.get(file_url)
        content = response.content
        self._reject_invalid_payload(content, response.url)

        consolidated_at = _date_from_work_uri(work_uri)
        published_at = None
        title = "Code civil"
        warning = (
            "Official consolidation. Cite the official ELI URI and publisher; "
            "lex is not the legal authority."
        )

        # Enrich from XML meta when present.
        try:
            root = etree.fromstring(content)
            meta_title = _jolux_value(root, "title")
            if meta_title:
                title = meta_title
            pub = _jolux_value(root, "publicationDate")
            if pub:
                published_at = date.fromisoformat(pub)
            applicability = _jolux_value(root, "dateApplicability")
            if applicability:
                consolidated_at = date.fromisoformat(applicability)
        except etree.XMLSyntaxError as exc:
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                response.url,
                f"Invalid LegalDocML XML: {exc}",
            ) from exc

        return SourceDocument(
            content=content,
            extension="xml",
            final_url=response.url,
            media_type=response.media_type or "application/xml",
            retrieved_at=datetime.now(UTC),
            title=title,
            document_type="code",
            status="official_consolidation",
            official_id=ref.official_id or "Code civil",
            eli_uri=work_uri or ref.eli_uri,
            published_at=published_at,
            consolidated_at=consolidated_at,
            source_modified_at=None,
            warning=warning,
        )

    def normalize(self, ref: LawRef, source: SourceDocument) -> NormalizedLaw:
        if _looks_like_browser_shell(source.content):
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                ref.id,
                "Refusing to normalize browser-shell HTML",
            )
        try:
            root = etree.fromstring(source.content)
        except etree.XMLSyntaxError as exc:
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                ref.id,
                f"Invalid LegalDocML XML: {exc}",
            ) from exc

        title = source.title or _jolux_value(root, "title") or "Code civil"
        body_el = root.find(f"{{{AKN_NS}}}body")
        if body_el is None:
            # Some documents nest act/body.
            bodies = root.xpath("//akn:body", namespaces=NSMAP)
            body_el = bodies[0] if bodies else None
        if body_el is None:
            raise LexError(ErrorCode.LEX_INVALID_DATA, ref.id, "No akn:body in source")

        lines: list[str] = [f"# {title}", ""]
        self._walk(body_el, lines)
        # Collapse excess blank lines.
        body = "\n".join(lines)
        body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
        return NormalizedLaw(title=title, document_type="code", body=body)

    def normalize_bytes(self, content: bytes, title: str = "Code civil") -> NormalizedLaw:
        """Test helper: normalize without a full SourceDocument."""
        return self.normalize(
            LawRef(id=CODE_CIVIL_ID, language="fr", source_url="fixture://local"),
            SourceDocument(
                content=content,
                extension="xml",
                final_url="fixture://local",
                media_type="application/xml",
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                title=title,
                document_type="code",
                status="official_consolidation",
            ),
        )

    def parse_discovery(self, payload: dict[str, Any]) -> LawRef:
        latest = self._select_latest_xml(payload)
        if latest is None:
            raise LexError(
                ErrorCode.LEX_NOT_FOUND,
                CODE_CIVIL_ID,
                "No XML consolidation in discovery payload",
            )
        work_uri, file_url = latest
        return LawRef(
            id=CODE_CIVIL_ID,
            language="fr",
            source_url=file_url,
            official_id="Code civil",
            eli_uri=work_uri,
        )

    def _walk(self, element: etree._Element, lines: list[str]) -> None:
        for child in element:
            tag = etree.QName(child).localname
            if tag in HIERARCHY_LEVELS:
                level = HIERARCHY_LEVELS[tag]
                num = _child_text(child, "num")
                heading = _child_text(child, "heading")
                label = " ".join(part for part in (num, heading) if part).strip()
                if label:
                    lines.append(f"{'#' * (level + 1)} {label}")
                    lines.append("")
                self._walk(child, lines)
            elif tag == "article":
                self._emit_article(child, lines)
            else:
                # Descend through containers (division, chapter wrappers, etc.)
                if tag not in {"meta", "preface", "num", "heading"}:
                    self._walk(child, lines)

    def _emit_article(self, article: etree._Element, lines: list[str]) -> None:
        raw_id = article.get("id") or _child_text(article, "num") or "article"
        anchor = normalize_anchor(raw_id)
        num = _child_text(article, "num") or raw_id
        lines.append(f'<a id="{anchor}"></a>')
        lines.append(f"## {num}")
        lines.append("")
        for alinea in article.findall(f"{{{AKN_NS}}}alinea"):
            text = _alinea_text(alinea)
            if text:
                lines.append(text)
                lines.append("")
        # Nested articles (rare) — still emit.
        for nested in article.findall(f"{{{AKN_NS}}}article"):
            self._emit_article(nested, lines)

    def _sparql(self, client: HttpClient, query: str) -> dict[str, Any]:
        # GET with query string — never POST /sparql.
        url = f"{SPARQL_ENDPOINT}?{urlencode({'query': query, 'format': 'json'})}"
        payload = client.get_json(url)
        if not isinstance(payload, dict):
            raise LexError(
                ErrorCode.LEX_NETWORK_ERROR, SPARQL_ENDPOINT, "Unexpected SPARQL payload"
            )
        return payload

    @staticmethod
    def _discovery_query() -> str:
        return f"""
SELECT ?work ?fileUrl WHERE {{
  ?work a <{JOLUX}Consolidation> .
  FILTER(CONTAINS(STR(?work), "{CODE_CIVIL_FRAGMENT}"))
  ?work <{JOLUX}isRealizedBy> ?expr .
  ?expr <{JOLUX}isEmbodiedBy> ?manifest .
  ?manifest <{JOLUX}isExemplifiedBy> ?fileUrl .
  FILTER(CONTAINS(STR(?manifest), "/xml"))
  FILTER(CONTAINS(STR(?fileUrl), "/fr/"))
}}
ORDER BY DESC(STR(?work))
LIMIT 20
""".strip()

    @staticmethod
    def _select_latest_xml(payload: dict[str, Any]) -> tuple[str, str] | None:
        bindings = payload.get("results", {}).get("bindings", [])
        candidates: list[tuple[str, str]] = []
        for row in bindings:
            work = row.get("work", {}).get("value")
            file_url = row.get("fileUrl", {}).get("value")
            if not work or not file_url:
                continue
            if "/xml" not in file_url:
                continue
            candidates.append((work, file_url))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0]

    @staticmethod
    def _reject_invalid_payload(content: bytes, url: str) -> None:
        if _looks_like_browser_shell(content):
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                url,
                "Received browser-shell HTML instead of LegalDocML",
            )
        head = content.lstrip()[:200].lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            # HTML manifestation is not selected for Stage 1A Code civil.
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                url,
                "Expected XML/LegalDocML, received HTML",
            )


def _looks_like_browser_shell(content: bytes) -> bool:
    sample = content[:8000].decode("utf-8", errors="ignore")
    return any(marker in sample for marker in BROWSER_SHELL_MARKERS)


def _date_from_work_uri(work_uri: str) -> date | None:
    match = re.search(r"/(\d{8})$", work_uri.rstrip("/"))
    if not match:
        return None
    raw = match.group(1)
    return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))


def _jolux_value(root: etree._Element, name: str) -> str | None:
    nodes = root.xpath(
        f".//scl:jolux[@scl:name='{name}']",
        namespaces=NSMAP,
    )
    for node in nodes:
        text = "".join(node.itertext()).strip()
        if text:
            return text
    return None


def _child_text(element: etree._Element, localname: str) -> str:
    child = element.find(f"{{{AKN_NS}}}{localname}")
    if child is None:
        return ""
    return " ".join("".join(child.itertext()).split())


def _alinea_text(alinea: etree._Element) -> str:
    parts: list[str] = []
    for p in alinea.xpath(".//akn:p", namespaces=NSMAP):
        text = " ".join("".join(p.itertext()).split())
        if text:
            parts.append(text)
    return " ".join(parts)


adapter = LuxembourgAdapter()
