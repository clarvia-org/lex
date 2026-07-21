"""Luxembourg Casemates adapter — Stage 1B: ten-law slice."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal
from urllib.parse import urlencode

from lxml import etree, html

from lex.adapters import LawRef, NormalizedLaw, SourceDocument
from lex.errors import ErrorCode, LexError
from lex.http import HttpClient
from lex.markdown import normalize_anchor

SPARQL_ENDPOINT = "http://data.legilux.public.lu/sparqlendpoint"
JOLUX = "http://data.legilux.public.lu/resource/ontology/jolux#"
AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13"
SCL_NS = "http://www.scl.lu"
NSMAP = {"akn": AKN_NS, "scl": SCL_NS}

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

DEFAULT_WARNING = (
    "Official consolidation. Cite the official ELI URI and publisher; "
    "lex is not the legal authority."
)
RECTIFICATION_WARNING = (
    "Official consolidation labelled « Version rectifiée applicable au 01/01/2025 ». "
    "Cite the official ELI URI and publisher; lex is not the legal authority."
)
CURRENT_WARNING = (
    "Official Journal text. Cite the official ELI URI and publisher; "
    "lex is not the legal authority."
)

FormatName = Literal["xml", "html"]


@dataclass(frozen=True)
class LawSpec:
    id: str
    document_type: str
    status: str
    format: FormatName
    languages: tuple[str, ...]
    title_fallback: str
    official_id: str
    work_eli: str
    sources: dict[str, str]
    resolve_latest: bool = False
    eli_fragment: str = ""
    warning_mode: Literal["default", "rectification", "current"] = "default"


# Stage 1B registry: code-civil + nine approved IDs.
LAWS: tuple[LawSpec, ...] = (
    LawSpec(
        id="lu/code-civil",
        document_type="code",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Code civil",
        official_id="Code civil",
        work_eli="http://data.legilux.public.lu/eli/etat/leg/code/civil",
        sources={},
        resolve_latest=True,
        eli_fragment="eli/etat/leg/code/civil/",
    ),
    LawSpec(
        id="lu/loi-2006-09-21-n1",
        document_type="law",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Loi du 21 septembre 2006",
        official_id="loi/2006/09/21/n1",
        work_eli=(
            "http://data.legilux.public.lu/eli/etat/leg/loi/2006/09/21/n1/consolide/20240801"
        ),
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/loi/2006/09/21/n1/"
                "consolide/20240801/fr/xml/"
                "eli-etat-leg-loi-2006-09-21-n1-consolide-20240801-fr-xml.xml"
            ),
        },
    ),
    LawSpec(
        id="lu/rgd-2025-03-13-a93",
        document_type="regulation",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Règlement grand-ducal du 13 mars 2025",
        official_id="rgd/2025/03/13/a93",
        work_eli=(
            "http://data.legilux.public.lu/eli/etat/leg/rgd/2025/03/13/a93/consolide/20250321"
        ),
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/rgd/2025/03/13/a93/"
                "consolide/20250321/fr/xml/"
                "eli-etat-leg-rgd-2025-03-13-a93-consolide-20250321-fr-xml.xml"
            ),
        },
    ),
    LawSpec(
        id="lu/code-commerce",
        document_type="code",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Code de commerce",
        official_id="Code de commerce",
        work_eli="http://data.legilux.public.lu/eli/etat/leg/code/commerce/20230201",
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/code/commerce/"
                "20230201/fr/xml/eli-etat-leg-code-commerce-20230201-fr-xml.xml"
            ),
        },
    ),
    LawSpec(
        id="lu/constitution",
        document_type="constitution",
        status="official_consolidation",
        format="xml",
        languages=("fr", "de"),
        title_fallback="Constitution",
        official_id="Constitution",
        work_eli=(
            "http://data.legilux.public.lu/eli/etat/leg/constitution/1868/10/17/n1/"
            "consolide/20230701"
        ),
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/constitution/"
                "1868/10/17/n1/consolide/20230701/fr/xml/"
                "eli-etat-leg-constitution-1868-10-17-n1-consolide-20230701-fr-xml.xml"
            ),
            "de": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/constitution/"
                "1868/10/17/n1/consolide/20230701/de/xml/"
                "eli-etat-leg-constitution-1868-10-17-n1-consolide-20230701-de-xml.xml"
            ),
        },
    ),
    LawSpec(
        id="lu/loi-2024-07-31-a339",
        document_type="law",
        status="official_current",
        format="html",
        languages=("fr",),
        title_fallback="Loi du 31 juillet 2024",
        official_id="loi/2024/07/31/a339",
        work_eli="http://data.legilux.public.lu/eli/etat/leg/loi/2024/07/31/a339/jo",
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/loi/2024/07/31/a339/"
                "jo/fr/html/eli-etat-leg-loi-2024-07-31-a339-jo-fr-html.html"
            ),
        },
        warning_mode="current",
    ),
    LawSpec(
        id="lu/code-penal",
        document_type="code",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Code pénal",
        official_id="Code pénal",
        work_eli="http://data.legilux.public.lu/eli/etat/leg/code/penal/20250311",
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/code/penal/"
                "20250311/fr/xml/eli-etat-leg-code-penal-20250311-fr-xml.xml"
            ),
        },
    ),
    LawSpec(
        id="lu/rgd-2024-12-20-a595",
        document_type="regulation",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Règlement grand-ducal du 20 décembre 2024",
        official_id="rgd/2024/12/20/a595",
        work_eli=(
            "http://data.legilux.public.lu/eli/etat/leg/rgd/2024/12/20/a595/consolide/20250101"
        ),
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/rgd/2024/12/20/a595/"
                "consolide/20250101/fr/xml/"
                "eli-etat-leg-rgd-2024-12-20-a595-consolide-20250101-fr-xml.xml"
            ),
        },
        warning_mode="rectification",
    ),
    LawSpec(
        id="lu/code-travail",
        document_type="code",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Code du travail",
        official_id="Code du travail",
        work_eli="http://data.legilux.public.lu/eli/etat/leg/code/travail/20260701",
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/code/travail/"
                "20260701/fr/xml/eli-etat-leg-code-travail-20260701-fr-xml.xml"
            ),
        },
    ),
    LawSpec(
        id="lu/code-procedure-civile",
        document_type="code",
        status="official_consolidation",
        format="xml",
        languages=("fr",),
        title_fallback="Nouveau Code de procédure civile",
        official_id="Code de procédure civile",
        work_eli="http://data.legilux.public.lu/eli/etat/leg/code/procedure_civile/20251219",
        sources={
            "fr": (
                "http://data.legilux.public.lu/filestore/eli/etat/leg/code/procedure_civile/"
                "20251219/fr/xml/eli-etat-leg-code-procedure_civile-20251219-fr-xml.xml"
            ),
        },
    ),
)

LAWS_BY_ID: dict[str, LawSpec] = {spec.id: spec for spec in LAWS}


class LuxembourgAdapter:
    country_code = "lu"

    def discover(self, client: HttpClient) -> Sequence[LawRef]:
        refs: list[LawRef] = []
        for spec in LAWS:
            for language in spec.languages:
                if spec.resolve_latest:
                    latest = self._select_latest_xml(
                        self._sparql(client, self._discovery_query(spec.eli_fragment, language)),
                        prefer_format=spec.format,
                    )
                    if latest is None:
                        raise LexError(
                            ErrorCode.LEX_NOT_FOUND,
                            spec.id,
                            f"No {spec.format} consolidation found for {spec.id}",
                        )
                    work_uri, file_url = latest
                else:
                    work_uri = spec.work_eli
                    file_url = spec.sources[language]
                refs.append(
                    LawRef(
                        id=spec.id,
                        language=language,
                        source_url=file_url,
                        official_id=spec.official_id,
                        eli_uri=work_uri,
                    )
                )
        return refs

    def fetch(self, ref: LawRef, client: HttpClient) -> SourceDocument:
        spec = LAWS_BY_ID.get(ref.id)
        if spec is None:
            raise LexError(
                ErrorCode.LEX_INVALID_ID,
                ref.id,
                "Unknown Luxembourg law ID for Stage 1B adapter",
            )

        file_url = ref.source_url
        work_uri = ref.eli_uri or spec.work_eli
        if not file_url:
            if spec.resolve_latest:
                latest = self._select_latest_xml(
                    self._sparql(client, self._discovery_query(spec.eli_fragment, ref.language)),
                    prefer_format=spec.format,
                )
                if latest is None:
                    raise LexError(
                        ErrorCode.LEX_NOT_FOUND,
                        ref.id,
                        f"No {spec.format} consolidation found for {spec.id}",
                    )
                work_uri, file_url = latest
            else:
                file_url = spec.sources[ref.language]

        response = client.get(file_url)
        content = response.content
        self._reject_invalid_payload(content, response.url, expect_format=spec.format)

        consolidated_at = _date_from_work_uri(work_uri)
        published_at: date | None = None
        title = spec.title_fallback
        warning = _warning_for(spec)

        if spec.format == "xml":
            try:
                root = etree.fromstring(content)
            except etree.XMLSyntaxError as exc:
                raise LexError(
                    ErrorCode.LEX_INVALID_DATA,
                    response.url,
                    f"Invalid LegalDocML XML: {exc}",
                ) from exc
            meta_title = _jolux_value(root, "title")
            if meta_title:
                title = meta_title
            pub = _jolux_value(root, "publicationDate")
            if pub:
                published_at = date.fromisoformat(pub)
            applicability = _jolux_value(root, "dateApplicability")
            if applicability:
                consolidated_at = date.fromisoformat(applicability)
            if spec.warning_mode == "rectification":
                warning = _rectification_warning(root, title)
        else:
            title, published_at = _html_meta(content, title)

        return SourceDocument(
            content=content,
            extension=spec.format,
            final_url=response.url,
            media_type=response.media_type
            or ("application/xml" if spec.format == "xml" else "text/html"),
            retrieved_at=datetime.now(UTC),
            title=title,
            document_type=spec.document_type,
            status=spec.status,
            official_id=ref.official_id or spec.official_id,
            eli_uri=work_uri or ref.eli_uri,
            published_at=published_at,
            consolidated_at=consolidated_at if spec.status == "official_consolidation" else None,
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
        spec = LAWS_BY_ID.get(ref.id)
        document_type = spec.document_type if spec else source.document_type
        if source.extension == "html" or (spec and spec.format == "html"):
            title, body = _normalize_html(source.content, source.title or "Untitled")
            return NormalizedLaw(title=title, document_type=document_type, body=body)

        try:
            root = etree.fromstring(source.content)
        except etree.XMLSyntaxError as exc:
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                ref.id,
                f"Invalid LegalDocML XML: {exc}",
            ) from exc

        title = source.title or _jolux_value(root, "title") or (spec.title_fallback if spec else "")
        body_el = root.find(f"{{{AKN_NS}}}body")
        if body_el is None:
            bodies = root.xpath("//akn:body", namespaces=NSMAP)
            body_el = bodies[0] if bodies else None
        if body_el is None:
            raise LexError(ErrorCode.LEX_INVALID_DATA, ref.id, "No akn:body in source")

        lines: list[str] = [f"# {title}", ""]
        self._walk(body_el, lines)
        body = "\n".join(lines)
        body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
        return NormalizedLaw(title=title, document_type=document_type, body=body)

    def normalize_bytes(self, content: bytes, title: str = "Code civil") -> NormalizedLaw:
        """Test helper: normalize without a full SourceDocument."""
        return self.normalize(
            LawRef(id="lu/code-civil", language="fr", source_url="fixture://local"),
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
        """Select latest XML Code civil from a SPARQL discovery payload (tests)."""
        latest = self._select_latest_xml(payload, prefer_format="xml")
        if latest is None:
            raise LexError(
                ErrorCode.LEX_NOT_FOUND,
                "lu/code-civil",
                "No XML consolidation in discovery payload",
            )
        work_uri, file_url = latest
        return LawRef(
            id="lu/code-civil",
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
        for nested in article.findall(f"{{{AKN_NS}}}article"):
            self._emit_article(nested, lines)

    def _sparql(self, client: HttpClient, query: str) -> dict[str, Any]:
        url = f"{SPARQL_ENDPOINT}?{urlencode({'query': query, 'format': 'json'})}"
        payload = client.get_json(url)
        if not isinstance(payload, dict):
            raise LexError(
                ErrorCode.LEX_NETWORK_ERROR, SPARQL_ENDPOINT, "Unexpected SPARQL payload"
            )
        return payload

    @staticmethod
    def _discovery_query(fragment: str, language: str = "fr") -> str:
        return f"""
SELECT ?work ?fileUrl WHERE {{
  ?work a <{JOLUX}Consolidation> .
  FILTER(CONTAINS(STR(?work), "{fragment}"))
  ?work <{JOLUX}isRealizedBy> ?expr .
  ?expr <{JOLUX}isEmbodiedBy> ?manifest .
  ?manifest <{JOLUX}isExemplifiedBy> ?fileUrl .
  FILTER(CONTAINS(STR(?manifest), "/xml") || CONTAINS(STR(?manifest), "/html"))
  FILTER(CONTAINS(STR(?fileUrl), "/{language}/"))
}}
ORDER BY DESC(STR(?work))
LIMIT 20
""".strip()

    @staticmethod
    def _select_latest_xml(
        payload: dict[str, Any],
        *,
        prefer_format: FormatName = "xml",
    ) -> tuple[str, str] | None:
        bindings = payload.get("results", {}).get("bindings", [])
        preferred: list[tuple[str, str]] = []
        fallback: list[tuple[str, str]] = []
        for row in bindings:
            work = row.get("work", {}).get("value")
            file_url = row.get("fileUrl", {}).get("value")
            if not work or not file_url:
                continue
            if f"/{prefer_format}" in file_url or file_url.endswith(f".{prefer_format}"):
                preferred.append((work, file_url))
            elif prefer_format == "xml" and "/xml" in file_url:
                preferred.append((work, file_url))
            elif prefer_format == "html" and "/html" in file_url:
                preferred.append((work, file_url))
            else:
                fallback.append((work, file_url))
        candidates = preferred or ([] if prefer_format == "xml" else fallback)
        # Stage 1A behaviour: when preferring XML, never fall back to HTML.
        if prefer_format == "xml":
            candidates = preferred
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0]

    @staticmethod
    def _reject_invalid_payload(
        content: bytes, url: str, *, expect_format: FormatName
    ) -> None:
        if _looks_like_browser_shell(content):
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                url,
                "Received browser-shell HTML instead of LegalDocML",
            )
        sample = content.lstrip()[:4000].lower()
        has_html_root = b"<html" in sample
        has_akn = b"akomantoso" in sample or b"<akn:" in sample
        if expect_format == "xml":
            if has_html_root and not has_akn:
                raise LexError(
                    ErrorCode.LEX_INVALID_DATA,
                    url,
                    "Expected XML/LegalDocML, received HTML",
                )
            return
        if not has_html_root:
            raise LexError(
                ErrorCode.LEX_INVALID_DATA,
                url,
                "Expected HTML manifestation, received non-HTML",
            )


def _warning_for(spec: LawSpec) -> str:
    if spec.warning_mode == "rectification":
        return RECTIFICATION_WARNING
    if spec.warning_mode == "current":
        return CURRENT_WARNING
    return DEFAULT_WARNING


def _rectification_warning(root: etree._Element, title: str) -> str:
    if "rectifi" in title.lower():
        return (
            f"Official consolidation: {title}. "
            "Cite the official ELI URI and publisher; lex is not the legal authority."
        )
    # Prefer expression title if present.
    for node in root.xpath(".//scl:jolux[@scl:name='title']", namespaces=NSMAP):
        text = "".join(node.itertext()).strip()
        if text and "rectifi" in text.lower():
            return (
                f"Official consolidation: {text}. "
                "Cite the official ELI URI and publisher; lex is not the legal authority."
            )
    return RECTIFICATION_WARNING


def _looks_like_browser_shell(content: bytes) -> bool:
    sample = content[:8000].decode("utf-8", errors="ignore")
    return any(marker in sample for marker in BROWSER_SHELL_MARKERS)


def _date_from_work_uri(work_uri: str) -> date | None:
    match = re.search(r"/consolide/(\d{8})", work_uri)
    if not match:
        match = re.search(r"/(\d{8})(?:/|$)", work_uri)
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


def _html_meta(content: bytes, fallback_title: str) -> tuple[str, date | None]:
    title = fallback_title
    published_at: date | None = None
    text = content.decode("utf-8", errors="replace")
    # JSON-LD block when present.
    match = re.search(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                name = data.get("name")
                if isinstance(name, str) and name.strip():
                    title = name.strip()
                pub = data.get("datePublished")
                if isinstance(pub, str) and pub:
                    published_at = date.fromisoformat(pub[:10])
        except json.JSONDecodeError:
            pass
    return title, published_at


def _normalize_html(content: bytes, fallback_title: str) -> tuple[str, str]:
    if _looks_like_browser_shell(content):
        raise LexError(
            ErrorCode.LEX_INVALID_DATA,
            "html",
            "Refusing to normalize browser-shell HTML",
        )
    # Legilux HTML is XHTML; the HTML parser relocates <p> inside <h1>, so parse as XML.
    try:
        doc = etree.fromstring(content)
    except etree.XMLSyntaxError:
        doc = html.fromstring(content)

    title = fallback_title
    h1_nodes = doc.xpath(
        "//*[local-name()='h1' and (@id='intituleAct' or contains(@class,'richtext_longTitle'))]"
    )
    if h1_nodes:
        heading = _element_text(h1_nodes[0])
        if heading:
            title = heading
    if title == fallback_title:
        meta_title, _ = _html_meta(content, fallback_title)
        title = meta_title

    lines: list[str] = [f"# {title}", ""]
    articles = doc.xpath("//*[local-name()='div' and contains(@class,'richtext_article')]")
    if not articles:
        raise LexError(ErrorCode.LEX_INVALID_DATA, "html", "No richtext_article elements found")

    for article in articles:
        raw_id = article.get("id") or "article"
        anchor = normalize_anchor(raw_id)
        num_nodes = article.xpath(
            ".//*[local-name()='p' and contains(@class,'richtext_num_article')]"
        )
        num = _element_text(num_nodes[0]) if num_nodes else raw_id
        lines.append(f'<a id="{anchor}"></a>')
        lines.append(f"## {num}")
        lines.append("")
        for alinea in article.xpath(
            ".//*[local-name()='div' and contains(@class,'richtext_alinea')]"
        ):
            for block in _html_alinea_blocks(alinea):
                lines.append(block)
                lines.append("")

    body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    return title, body


def _html_alinea_blocks(alinea: etree._Element) -> list[str]:
    blocks: list[str] = []
    for p in alinea.xpath(".//*[local-name()='p' and contains(@class,'richtext_p')]"):
        classes = p.get("class") or ""
        if "richtext_num_article" in classes:
            continue
        text = _element_text(p)
        if text:
            blocks.append(text)
    for row in alinea.xpath(".//*[local-name()='tr' and contains(@class,'richtext_elementLI')]"):
        num_cells = row.xpath(".//*[local-name()='td' and contains(@class,'richtext_numLI')]")
        content_cells = row.xpath(
            ".//*[local-name()='td' and contains(@class,'richtext_contentLI')]"
        )
        num = _element_text(num_cells[0]) if num_cells else ""
        content = _element_text(content_cells[0]) if content_cells else ""
        if num and content:
            blocks.append(f"{num} {content}")
        elif content:
            blocks.append(content)
    if not blocks:
        text = _element_text(alinea)
        if text:
            blocks.append(text)
    return blocks


def _element_text(element: etree._Element) -> str:
    text = " ".join("".join(element.itertext()).split())
    return text.replace("\u200b", "").replace("\ufeff", "").strip()


adapter = LuxembourgAdapter()
