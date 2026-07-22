"""Public Markdown ↔ source fidelity gate."""

from __future__ import annotations

from pathlib import Path

from lex.fidelity import check_law_fidelity
from lex.frontmatter import parse_frontmatter

FIXTURES = Path("countries/lu/fixtures")
LAW = Path("countries/lu/laws/loi-2000-06-29-n2")


def test_fidelity_fails_on_broken_projection(tmp_path: Path) -> None:
    """Saved pre-fix truncated body must fail against retained source.xml."""
    source = (LAW / "source.xml").read_bytes()
    original = (LAW / "current.md").read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(original)
    broken_body = (FIXTURES / "broken-loi-2000-body.md").read_text(encoding="utf-8")
    # Rebuild with real frontmatter pointing at source.xml beside the temp md.
    from lex.frontmatter import serialize_frontmatter

    md_text = serialize_frontmatter(meta) + "\n" + broken_body
    (tmp_path / "source.xml").write_bytes(source)
    md_path = tmp_path / "current.md"
    md_path.write_text(md_text, encoding="utf-8")

    errors = check_law_fidelity(md_path)
    assert errors, "expected fidelity failures on truncated projection"
    messages = " | ".join(err.message for err in errors)
    assert "art-3" in messages or "art-7" in messages or "art-13" in messages


def test_fidelity_passes_on_published_loi_2000() -> None:
    md = LAW / "current.md"
    assert md.is_file()
    errors = check_law_fidelity(md)
    assert not errors, [err.message for err in errors]
