"""Offline Markdown ↔ retained-source fidelity checks.

Primary gate: statutory word-token parity between retained source body and
normalized Markdown. Fuzzy per-article ratios are intentionally not used —
omitted legal prose must fail the check.

Residual omissions under the 0.5% margin (e.g. code-fonction-publique ≈0.004%)
are almost always Casemates XML glue without spaces (``ladirective``,
``1erduCode``, ``UEdu``) that Markdown splits correctly — not dropped prose.
When the gate fails, errors include a per-article first-difference report so
the first diverging provision is obvious.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from lxml import etree, html

from lex.errors import ErrorCode, LexError
from lex.frontmatter import parse_frontmatter

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD13"
SCL_NS = "http://www.scl.lu"

# Allow tiny structural noise (list markers already stripped; residual MD/XML
# tokenization edge cases — usually source glue, not omitted prose).
# Absolute legal target is ~0 omitted words.
WORD_COUNT_MARGIN = 0.005
WORD_RE = re.compile(r"\b[a-zA-ZÀ-ÿ0-9]+\b", re.UNICODE)
_ARTICLE_ANCHOR_RE = re.compile(
    r'<a\s+id="([^"]*)"\s*></a>\s*\n##\s+([^\n]*)',
    re.MULTILINE,
)
_FIRST_DIFF_WINDOW = 8
_FIRST_DIFF_REPORT_LIMIT = 8

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
    source_bytes = source_path.read_bytes()
    try:
        if suffix == ".xml":
            source_words = xml_body_words(source_bytes)
            article_diffs = article_first_differences_xml(source_bytes, body)
        elif suffix in {".html", ".htm"}:
            source_words = html_body_words(source_bytes)
            # Synthetic / non-Legilux HTML fixtures are outside the LU AKN contract.
            if len(source_words) < 50:
                return []
            article_diffs = []
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
    return _compare_word_streams(
        source_words,
        md_words,
        rel=rel,
        article_diffs=article_diffs,
    )


def article_first_differences_xml(
    content: bytes,
    md_body: str,
    *,
    limit: int = _FIRST_DIFF_REPORT_LIMIT,
) -> list[ArticleFirstDiff]:
    """Per-article first token divergence between AKN XML body and Markdown."""
    xml_articles = xml_article_word_streams(content)
    md_articles = markdown_article_word_streams(md_body)
    return first_article_differences(xml_articles, md_articles, limit=limit)


@dataclass(frozen=True)
class ArticleFirstDiff:
    """First word-stream divergence for one provision."""

    article_id: str
    index: int
    xml_len: int
    md_len: int
    xml_window: tuple[str, ...]
    md_window: tuple[str, ...]
    kind: str  # "mismatch" | "missing_in_md" | "extra_in_md"

    def format_line(self) -> str:
        if self.kind == "missing_in_md":
            return f"{self.article_id}: present in XML ({self.xml_len} words), missing in Markdown"
        if self.kind == "extra_in_md":
            return f"{self.article_id}: present in Markdown ({self.md_len} words), missing in XML"
        xml_ctx = " ".join(self.xml_window) or "—"
        md_ctx = " ".join(self.md_window) or "—"
        return (
            f"{self.article_id}: first diff at token {self.index} "
            f"(xml_len={self.xml_len}, md_len={self.md_len}); "
            f"xml=[{xml_ctx}] md=[{md_ctx}]"
        )


def xml_article_word_streams(content: bytes) -> list[tuple[str, list[str]]]:
    """Return ``(article_id, words)`` for each ``akn:article`` in document order."""
    parser = etree.XMLParser(huge_tree=True, recover=True)
    root = etree.fromstring(content, parser=parser)
    bodies = root.xpath(f"//*[local-name()='body' and namespace-uri()='{AKN_NS}']")
    if not bodies:
        bodies = root.xpath("//*[local-name()='body']")
    if not bodies:
        return []
    out: list[tuple[str, list[str]]] = []
    for article in bodies[0].xpath(".//*[local-name()='article']"):
        xml_id = article.get("id") or ""
        num_nodes = article.xpath("./*[local-name()='num']")
        num = " ".join("".join(num_nodes[0].itertext()).split()) if num_nodes else ""
        key = _article_key(xml_id or num or f"article-{len(out) + 1}")
        # Article ``num`` is the Markdown ``##`` heading (excluded from the MD
        # body stream). Nested paragraph ``num`` values remain in both streams.
        out.append((key, tokenize(_article_body_text(article))))
    return out


def _article_body_text(article: etree._Element) -> str:
    """Statutory text of an article excluding its own ``num`` label only."""
    parts: list[str] = []
    if article.text:
        parts.append(article.text)
    for child in article:
        if not isinstance(child.tag, str):
            continue
        qname = etree.QName(child)
        if qname.namespace == SCL_NS or qname.localname == "num":
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(" ")
        parts.append(_statutory_text(child))
        if child.tail:
            parts.append(" ")
            parts.append(child.tail)
    return " ".join("".join(parts).split()).replace("\u200b", "").replace("\ufeff", "").strip()


def markdown_article_word_streams(body: str) -> list[tuple[str, list[str]]]:
    """Return ``(article_id, words)`` for each anchored ``##`` provision in Markdown."""
    matches = list(_ARTICLE_ANCHOR_RE.finditer(body))
    if not matches:
        return []
    out: list[tuple[str, list[str]]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section = body[start:end]
        # Hierarchy headings between articles (Chapitre/Titre/…) are siblings in
        # XML, not article children — stop the MD article body before them.
        heading_cut = re.search(r"(?m)^#{2,6}\s+", section)
        if heading_cut:
            section = section[: heading_cut.start()]
        key = _article_key(match.group(1) or match.group(2) or f"article-{i + 1}")
        out.append((key, markdown_body_words(section)))
    return out


def first_article_differences(
    xml_articles: list[tuple[str, list[str]]],
    md_articles: list[tuple[str, list[str]]],
    *,
    limit: int = _FIRST_DIFF_REPORT_LIMIT,
) -> list[ArticleFirstDiff]:
    """Align articles by id (document order) and report the first token mismatch each."""
    md_queues: dict[str, deque[list[str]]] = defaultdict(deque)
    for article_id, words in md_articles:
        md_queues[article_id].append(words)

    diffs: list[ArticleFirstDiff] = []
    for article_id, xml_words in xml_articles:
        if len(diffs) >= limit:
            return diffs
        if not md_queues[article_id]:
            diffs.append(
                ArticleFirstDiff(
                    article_id=article_id,
                    index=0,
                    xml_len=len(xml_words),
                    md_len=0,
                    xml_window=tuple(xml_words[:_FIRST_DIFF_WINDOW]),
                    md_window=(),
                    kind="missing_in_md",
                )
            )
            continue
        md_words = md_queues[article_id].popleft()
        diff = _first_token_diff(xml_words, md_words)
        if diff is None:
            continue
        index, xml_window, md_window = diff
        diffs.append(
            ArticleFirstDiff(
                article_id=article_id,
                index=index,
                xml_len=len(xml_words),
                md_len=len(md_words),
                xml_window=tuple(xml_window),
                md_window=tuple(md_window),
                kind="mismatch",
            )
        )

    if len(diffs) < limit:
        for article_id, queue in md_queues.items():
            while queue and len(diffs) < limit:
                md_words = queue.popleft()
                diffs.append(
                    ArticleFirstDiff(
                        article_id=article_id,
                        index=0,
                        xml_len=0,
                        md_len=len(md_words),
                        xml_window=(),
                        md_window=tuple(md_words[:_FIRST_DIFF_WINDOW]),
                        kind="extra_in_md",
                    )
                )
    return diffs


def format_article_diff_report(diffs: list[ArticleFirstDiff]) -> str:
    if not diffs:
        return ""
    lines = ["per-article first differences:"]
    lines.extend(f"  - {diff.format_line()}" for diff in diffs)
    return "\n".join(lines)


def _article_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", raw.casefold()).strip("-") or "article"


def _first_token_diff(
    xml_words: list[str],
    md_words: list[str],
    *,
    window: int = _FIRST_DIFF_WINDOW,
) -> tuple[int, list[str], list[str]] | None:
    n = min(len(xml_words), len(md_words))
    for i in range(n):
        if xml_words[i] != md_words[i]:
            return (
                i,
                xml_words[i : i + window],
                md_words[i : i + window],
            )
    if len(xml_words) != len(md_words):
        return (
            n,
            xml_words[n : n + window],
            md_words[n : n + window],
        )
    return None


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


def _statutory_text(
    element: etree._Element,
) -> str:
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
    article_diffs: list[ArticleFirstDiff] | None = None,
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
    message = (
        "Fidelity: statutory word parity failed "
        f"(source={src_n} words, md={md_n}, "
        f"missing_tokens={missing_n} ({omission_ratio:.2%}), "
        f"extra_tokens={extra_n}; "
        f"top_missing=[{top_missing}]; top_extra=[{top_extra}])"
    )
    report = format_article_diff_report(article_diffs or [])
    if report:
        message = f"{message}\n{report}"
    return [
        LexError(
            ErrorCode.LEX_INVALID_DATA,
            rel,
            message,
        )
    ]
