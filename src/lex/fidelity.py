"""Offline Markdown ↔ retained-source fidelity checks.

Primary gate: statutory word-token parity between retained source body and
normalized Markdown. Fuzzy per-article ratios are intentionally not used —
omitted legal prose must fail the check.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from lxml import etree, html

from lex.errors import ErrorCode, LexError
from lex.frontmatter import parse_frontmatter

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13"
SCL_NS = "http://www.scl.lu"

# Allow tiny structural noise (list markers already stripped; residual MD/XML
# tokenization edge cases). Absolute legal target is ~0 omitted words.
WORD_COUNT_MARGIN = 0.005
WORD_RE = re.compile(r"\b[a-zA-ZÀ-ÿ0-9]+\b", re.UNICODE)

_SKIP_TAGS = frozenset(
    {
        "meta",
        "preface",
        "toc",
        "JOLUXWork",
        "JOLUXComplexWork",
        "JOLUXLegalResource",
        "JOLUXExpression",
        "JOLUXManifestation",
        "indexterms",
        "indexterm",
        "jolux",
        "rdf",
        "label",
    }
)

# Block-ish elements: insert a word boundary so article/paragraph edges are not glued.
_BLOCK_BOUNDARY_TAGS = frozenset(
    {
        "article",
        "paragraph",
        "subparagraph",
        "alinea",
        "section",
        "subsection",
        "chapter",
        "title",
        "book",
        "part",
        "heading",
        "num",
        "content",
        "p",
        "li",
        "ol",
        "ul",
        "list",
        "point",
        "table",
        "tr",
        "td",
        "th",
        "tocItem",
        "authorialNote",
        "wrapUp",
        "intro",
        "quotedStructure",
        "subdivision",
        "subchapter",
        "subFlow",
        "embeddedText",
    }
)


def check_law_fidelity(md_path: Path, *, rel_path: str | Path | None = None) -> list[LexError]:
    """Fail when normalized Markdown omits statutory words present in retained source."""
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
            source_words = xml_body_words(source_path.read_bytes())
        elif suffix in {".html", ".htm"}:
            source_words = html_body_words(source_path.read_bytes())
            # Synthetic / non-Legilux HTML fixtures are outside the LU AKN contract.
            if len(source_words) < 50:
                return []
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

    md_words = markdown_body_words(body)
    return _compare_word_streams(source_words, md_words, rel=rel)


def xml_body_words(content: bytes) -> list[str]:
    parser = etree.XMLParser(huge_tree=True, recover=True)
    root = etree.fromstring(content, parser=parser)
    bodies = root.xpath(f"//*[local-name()='body' and namespace-uri()='{AKN_NS}']")
    if not bodies:
        bodies = root.xpath("//*[local-name()='body']")
    if not bodies:
        return []
    return tokenize(_statutory_text(bodies[0]))


def html_body_words(content: bytes) -> list[str]:
    try:
        doc = etree.fromstring(content)
    except etree.XMLSyntaxError:
        doc = html.fromstring(content)
    articles = doc.xpath("//*[local-name()='div' and contains(@class,'richtext_article')]")
    if not articles:
        return tokenize(_statutory_text(doc))
    parts = [_statutory_text(article) for article in articles]
    return tokenize(" ".join(parts))


def markdown_body_words(body: str) -> list[str]:
    lines_out: list[str] = []
    skipped_title = False
    for line in body.splitlines():
        stripped = line.strip()
        if not skipped_title and stripped.startswith("# "):
            # Main document title — not part of akn:body comparison.
            skipped_title = True
            continue
        if re.fullmatch(r'<a\s+id="[^"]*"></a>', stripped):
            continue
        stripped = re.sub(r"^#{1,6}\s+", "", stripped)
        # Strip only bullet markers we invent; keep real numerals from source.
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        stripped = stripped.replace("|", " ")
        lines_out.append(stripped)
    return tokenize("\n".join(lines_out))


def tokenize(text: str) -> list[str]:
    words = WORD_RE.findall(text.casefold())
    words = _split_alpha_digit_runs(words)
    return _merge_ordinal_splits(words)


def _split_alpha_digit_runs(words: list[str]) -> list[str]:
    """Split ``m3`` / ``5verre`` so unit and numeral tokens align across XML/MD."""
    out: list[str] = []
    for word in words:
        parts = re.findall(r"[a-zà-ÿ]+|\d+", word, flags=re.IGNORECASE)
        if parts:
            out.extend(part.casefold() for part in parts)
        else:
            out.append(word)
    return out


def _merge_ordinal_splits(words: list[str]) -> list[str]:
    """Merge ``1``+``er`` / ``32``+``bis`` splits so XML/MD tokenization aligns."""
    suffixes = frozenset(
        {
            "er",
            "re",
            "e",
            "ème",
            "eme",
            "èmes",
            "emes",
            "bis",
            "ter",
            "quater",
            "quinquies",
            "sexies",
            "ère",
            "ere",
            "ères",
            "eres",
        }
    )
    out: list[str] = []
    i = 0
    while i < len(words):
        if i + 1 < len(words) and words[i].isdigit() and words[i + 1] in suffixes:
            out.append(words[i] + words[i + 1])
            i += 2
            continue
        out.append(words[i])
        i += 1
    return out


# Inline wrappers: keep text glued (``1``+``er``, ``ij``+``a``). Space only at
# non-inline element edges so parent text does not merge with nested blocks.
_INLINE_TEXT_TAGS = frozenset(
    {
        "a",
        "abbr",
        "b",
        "del",
        "em",
        "embeddedText",
        "i",
        "inline",
        "ins",
        "ref",
        "s",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "u",
    }
)


def _statutory_text(element: etree._Element) -> str:
    """Concatenate descendant text with spaces at block edges only.

    Inline wrappers (sup/b/i/ref/…) stay glued so ``1``+``er`` → ``1er``.
    Block edges get a space so ``… et`` + nested ``sections…`` do not become
    ``etsections``, and ``…finales`` + ``Art.`` do not become ``finalesart``.
    """
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        qname = etree.QName(node)
        if qname.namespace == SCL_NS or qname.localname in _SKIP_TAGS:
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            if not isinstance(child.tag, str):
                continue
            child_tag = etree.QName(child).localname
            if child_tag not in _INLINE_TEXT_TAGS:
                parts.append(" ")
            walk(child)
            if child.tail:
                if child_tag not in _INLINE_TEXT_TAGS:
                    parts.append(" ")
                parts.append(child.tail)

    walk(element)
    return " ".join("".join(parts).split()).replace("\u200b", "").replace("\ufeff", "").strip()


def _compare_word_streams(
    source_words: list[str],
    md_words: list[str],
    *,
    rel: str | Path,
) -> list[LexError]:
    """Fail when Markdown omits >0.5% of source statutory word tokens.

    Compares the full token multiset (letters and digits). List markers are
    stripped on the Markdown side and must not be invented by the adapter.
    """
    if not source_words:
        return []
    src_n = len(source_words)
    md_n = len(md_words)
    src_counts = Counter(source_words)
    md_counts = Counter(md_words)
    missing = src_counts - md_counts
    extra = md_counts - src_counts
    missing_n = sum(missing.values())
    extra_n = sum(extra.values())
    omission_ratio = missing_n / src_n
    if omission_ratio <= WORD_COUNT_MARGIN:
        return []

    top_missing = ", ".join(f"{w}×{c}" for w, c in missing.most_common(8)) or "—"
    top_extra = ", ".join(f"{w}×{c}" for w, c in extra.most_common(5)) or "—"
    return [
        LexError(
            ErrorCode.LEX_INVALID_DATA,
            rel,
            "Fidelity: statutory word parity failed "
            f"(source={src_n} words, md={md_n}, "
            f"missing_tokens={missing_n} ({omission_ratio:.2%}), "
            f"extra_tokens={extra_n}; "
            f"top_missing=[{top_missing}]; top_extra=[{top_extra}])",
        )
    ]
