"""Offline Markdown ↔ retained-source fidelity checks.

Catches silent projection bugs (empty articles, dropped lists, truncated bodies)
that SHA-256 of the source file alone cannot detect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree, html

from lex.errors import ErrorCode, LexError
from lex.frontmatter import parse_frontmatter
from lex.markdown import normalize_anchor

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13"
SCL_NS = "http://www.scl.lu"

_BODY_CHILD_TAGS = frozenset({"alinea", "paragraph", "content", "p", "ol", "ul", "list", "table"})
_SKIP_TAGS = frozenset({"JOLUXWork", "indexterms", "meta", "preface", "num", "heading"})
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+[.)]|[a-zA-Z][.)]|\([0-9a-zA-Z]+\))\s+\S")


@dataclass(frozen=True)
class ArticleInventory:
    anchor: str
    text_chars: int
    list_items: int


def check_law_fidelity(md_path: Path, *, rel_path: str | Path | None = None) -> list[LexError]:
    """Compare retained source structure/text mass to normalized Markdown bodies."""
    rel = rel_path if rel_path is not None else md_path
    text = md_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    source_file = meta.get("source_file")
    if not isinstance(source_file, str) or not source_file:
        return []
    source_path = md_path.parent / source_file
    if not source_path.is_file():
        return []

    suffix = source_path.suffix.lower()
    try:
        if suffix == ".xml":
            source_articles = _inventory_xml(source_path.read_bytes())
        elif suffix in {".html", ".htm"}:
            source_articles = _inventory_html(source_path.read_bytes())
        else:
            return []
    except etree.XMLSyntaxError as exc:
        return [
            LexError(
                ErrorCode.LEX_INVALID_DATA,
                rel,
                f"Cannot parse source for fidelity check: {exc}",
            )
        ]

    md_articles = _inventory_markdown(body)
    md_by_anchor = {item.anchor: item for item in md_articles}
    errors: list[LexError] = []

    for src in source_articles:
        md = md_by_anchor.get(src.anchor)
        if md is None:
            errors.append(
                LexError(
                    ErrorCode.LEX_INVALID_DATA,
                    rel,
                    f"Fidelity: source article '{src.anchor}' missing from Markdown",
                )
            )
            continue
        if src.text_chars >= 80 and md.text_chars < 20:
            errors.append(
                LexError(
                    ErrorCode.LEX_INVALID_DATA,
                    rel,
                    f"Fidelity: article '{src.anchor}' empty/near-empty in Markdown "
                    f"(source≈{src.text_chars} chars, md={md.text_chars})",
                )
            )
            continue
        if src.text_chars >= 200 and md.text_chars < int(src.text_chars * 0.25):
            errors.append(
                LexError(
                    ErrorCode.LEX_INVALID_DATA,
                    rel,
                    f"Fidelity: article '{src.anchor}' truncated in Markdown "
                    f"(source≈{src.text_chars} chars, md={md.text_chars})",
                )
            )
            continue
        if src.list_items >= 3 and md.list_items < max(1, int(src.list_items * 0.3)):
            # Require accompanying text loss so table-rendered lists do not false-fail.
            if md.text_chars < max(40, int(src.text_chars * 0.5)):
                errors.append(
                    LexError(
                        ErrorCode.LEX_INVALID_DATA,
                        rel,
                        f"Fidelity: article '{src.anchor}' lost list items "
                        f"(source={src.list_items}, md={md.list_items})",
                    )
                )
    return errors


def _inventory_xml(content: bytes) -> list[ArticleInventory]:
    parser = etree.XMLParser(huge_tree=True, recover=True)
    root = etree.fromstring(content, parser=parser)
    articles = root.xpath(f"//*[local-name()='article' and namespace-uri()='{AKN_NS}']")
    if not articles:
        articles = root.xpath("//*[local-name()='article']")
    out: list[ArticleInventory] = []
    seen: set[str] = set()
    for article in articles:
        # Nested / quoted articles are not independent published provisions.
        if _has_intervening_article_ancestor(article):
            continue
        # Attachments/components are outside akn:body and are not projected today.
        if not _under_main_body(article):
            continue
        xml_id = article.get("id")
        if not xml_id:
            # Without an official @id, anchors collide across annexes; skip for mass checks.
            continue
        anchor = _normalize_xml_article_id(xml_id)
        if not anchor or anchor in seen:
            continue
        seen.add(anchor)
        text = _xml_article_text(article)
        list_items = _xml_list_item_count(article)
        out.append(ArticleInventory(anchor=anchor, text_chars=len(text), list_items=list_items))
    return out


def _under_main_body(el: etree._Element) -> bool:
    parent = el.getparent()
    while parent is not None:
        tag = etree.QName(parent).localname
        if tag == "body":
            return True
        if tag in {"attachments", "attachment", "components", "component"}:
            return False
        parent = parent.getparent()
    return False


def _has_intervening_article_ancestor(el: etree._Element) -> bool:
    parent = el.getparent()
    while parent is not None:
        if etree.QName(parent).localname == "article":
            return True
        parent = parent.getparent()
    return False


def _xml_article_anchor(article: etree._Element) -> str:
    xml_id = article.get("id")
    if xml_id:
        return _normalize_xml_article_id(xml_id)
    num_el = article.find(f"{{{AKN_NS}}}num")
    if num_el is not None:
        num = " ".join("".join(num_el.itertext()).split())
        if num:
            return normalize_anchor(num)
    return ""


def _normalize_xml_article_id(xml_id: str) -> str:
    lowered = xml_id.strip().lower()
    trailing_marker = bool(re.search(r"[^a-z0-9]+$", lowered))
    collapsed = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if trailing_marker and collapsed:
        return f"{collapsed}-"
    return collapsed


def _xml_article_text(article: etree._Element) -> str:
    chunks: list[str] = []
    for child in article:
        tag = etree.QName(child).localname
        ns = etree.QName(child).namespace
        if ns == SCL_NS or tag in _SKIP_TAGS or tag == "article":
            continue
        if tag in _BODY_CHILD_TAGS or tag in {
            "paragraph",
            "alinea",
            "heading",
            "section",
            "subsection",
            "chapter",
            "title",
            "book",
            "part",
        }:
            chunks.append(_text_excluding_nested_articles(child))
    return " ".join(" ".join(chunks).split())


def _text_excluding_nested_articles(el: etree._Element) -> str:
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        if etree.QName(child).localname == "article":
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_text_excluding_nested_articles(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _xml_list_item_count(article: etree._Element) -> int:
    count = 0
    for el in article.iter():
        if el is article:
            continue
        if _has_intervening_article(article, el):
            continue
        # Table-encoded Legilux lists are projected as tables, not md bullets.
        if _inside_table(el):
            continue
        tag = etree.QName(el).localname
        if tag in {"li", "point"}:
            text = " ".join("".join(el.itertext()).split())
            if text:
                count += 1
    return count


def _inside_table(el: etree._Element) -> bool:
    parent = el.getparent()
    while parent is not None:
        if etree.QName(parent).localname == "table":
            return True
        parent = parent.getparent()
    return False


def _has_intervening_article(root_article: etree._Element, el: etree._Element) -> bool:
    parent = el.getparent()
    while parent is not None and parent is not root_article:
        if etree.QName(parent).localname == "article":
            return True
        parent = parent.getparent()
    return False


def _inventory_html(content: bytes) -> list[ArticleInventory]:
    try:
        doc = etree.fromstring(content)
    except etree.XMLSyntaxError:
        doc = html.fromstring(content)
    articles = doc.xpath("//*[local-name()='div' and contains(@class,'richtext_article')]")
    out: list[ArticleInventory] = []
    for article in articles:
        raw_id = article.get("id") or ""
        anchor = normalize_anchor(raw_id) if raw_id else ""
        if not anchor:
            continue
        # Exclude num_article paragraphs from mass? include all visible text under alineas.
        text_chunks: list[str] = []
        list_items = 0
        for alinea in article.xpath(
            ".//*[local-name()='div' and contains(@class,'richtext_alinea')]"
        ):
            text_chunks.append("".join(alinea.itertext()))
            list_items += len(alinea.xpath(".//*[local-name()='li']")) + len(
                alinea.xpath(".//*[local-name()='tr' and contains(@class,'richtext_elementLI')]")
            )
        text = " ".join(" ".join(text_chunks).split())
        out.append(ArticleInventory(anchor=anchor, text_chars=len(text), list_items=list_items))
    return out


def _inventory_markdown(body: str) -> list[ArticleInventory]:
    out: list[ArticleInventory] = []
    matches = list(re.finditer(r'<a\s+id="([^"]+)"></a>', body))
    for i, match in enumerate(matches):
        anchor = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section = body[start:end]
        lines = section.splitlines()
        body_lines: list[str] = []
        seen_heading = False
        for line in lines:
            if not seen_heading:
                if line.startswith("#"):
                    seen_heading = True
                continue
            body_lines.append(line)
        text = " ".join(" ".join(body_lines).split())
        list_items = sum(1 for line in body_lines if _LIST_ITEM_RE.match(line))
        out.append(ArticleInventory(anchor=anchor, text_chars=len(text), list_items=list_items))
    return out
