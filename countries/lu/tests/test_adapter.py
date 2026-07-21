from __future__ import annotations

import json
from pathlib import Path

import pytest

from lex.errors import ErrorCode, LexError
from lex.markdown import extract_provision, normalize_anchor

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load_adapter():  # type: ignore[no-untyped-def]
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "adapter.py"
    spec = importlib.util.spec_from_file_location("lu_adapter_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.adapter


def test_stable_id_and_discovery_selects_latest_xml() -> None:
    adapter = _load_adapter()
    payload = json.loads((FIXTURES / "discovery.json").read_text(encoding="utf-8"))
    ref = adapter.parse_discovery(payload)
    assert ref.id == "lu/code-civil"
    assert ref.language == "fr"
    assert ref.eli_uri.endswith("/20251226")
    assert "/xml/" in ref.source_url
    assert "20251226" in ref.source_url


def test_source_selection_prefers_xml_over_html() -> None:
    adapter = _load_adapter()
    payload = {
        "results": {
            "bindings": [
                {
                    "work": {
                        "type": "uri",
                        "value": "http://data.legilux.public.lu/eli/etat/leg/code/civil/20251226",
                    },
                    "fileUrl": {
                        "type": "uri",
                        "value": (
                            "http://data.legilux.public.lu/filestore/eli/etat/leg/code/civil/"
                            "20251226/fr/html/eli-etat-leg-code-civil-20251226-fr-html.html"
                        ),
                    },
                },
                {
                    "work": {
                        "type": "uri",
                        "value": "http://data.legilux.public.lu/eli/etat/leg/code/civil/20251226",
                    },
                    "fileUrl": {
                        "type": "uri",
                        "value": (
                            "http://data.legilux.public.lu/filestore/eli/etat/leg/code/civil/"
                            "20251226/fr/xml/eli-etat-leg-code-civil-20251226-fr-xml.xml"
                        ),
                    },
                },
            ]
        }
    }
    ref = adapter.parse_discovery(payload)
    assert ref.source_url.endswith(".xml")


def test_ordinary_normalization_matches_fixture() -> None:
    adapter = _load_adapter()
    content = (FIXTURES / "ordinary-source.xml").read_bytes()
    expected = (FIXTURES / "expected-ordinary.md").read_text(encoding="utf-8")
    body = adapter.normalize_bytes(content).body
    assert body == expected
    assert '<a id="art-1er"></a>' in body
    assert '<a id="art-2"></a>' in body
    assert '<a id="art-13"></a>' in body


def test_complex_normalization_matches_fixture() -> None:
    adapter = _load_adapter()
    content = (FIXTURES / "complex-source.xml").read_bytes()
    expected = (FIXTURES / "expected-complex.md").read_text(encoding="utf-8")
    assert adapter.normalize_bytes(content).body == expected


def test_normalization_is_deterministic() -> None:
    adapter = _load_adapter()
    content = (FIXTURES / "ordinary-source.xml").read_bytes()
    first = adapter.normalize_bytes(content).body
    second = adapter.normalize_bytes(content).body
    assert first == second


def test_invalid_browser_shell_rejected() -> None:
    adapter = _load_adapter()
    content = (FIXTURES / "invalid-response.html").read_bytes()
    with pytest.raises(LexError) as exc:
        adapter.normalize_bytes(content)
    assert exc.value.code == ErrorCode.LEX_INVALID_DATA


def test_anchor_normalization() -> None:
    assert normalize_anchor("art_13") == "art-13"
    assert normalize_anchor("art_1er") == "art-1er"
    assert normalize_anchor("Art. 13.") == "art-13"


def test_provision_extraction_nested_without_neighbors() -> None:
    adapter = _load_adapter()
    body = adapter.normalize_bytes((FIXTURES / "ordinary-source.xml").read_bytes()).body
    markdown = (
        "---\n"
        "id: lu/code-civil\n"
        "country: lu\n"
        "title: Code civil\n"
        "language: fr\n"
        "document_type: code\n"
        "status: official_consolidation\n"
        "official_id: Code civil\n"
        "source_url: https://example.test/source.xml\n"
        "source_file: source.xml\n"
        "source_sha256: " + ("a" * 64) + "\n"
        "source_license: CC-BY-4.0\n"
        "source_attribution: Service central de législation, Luxembourg\n"
        "source_terms_url: https://data.legilux.public.lu/home/intro\n"
        "rights_reviewed_at: '2026-07-21'\n"
        "retrieved_at: '2026-07-21T12:00:00Z'\n"
        "---\n\n"
        f"{body}"
    )
    extracted = extract_provision(markdown, "art-13")
    assert "provision: art-13" in extracted
    assert "Art. 13." in extracted
    assert "Art. 1er." not in extracted
    assert "Art. 2." not in extracted
