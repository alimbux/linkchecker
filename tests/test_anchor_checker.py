from __future__ import annotations

from mdcheck.anchor_checker import check_anchor, extract_headings, generate_slugs, slugify
from mdcheck.models import Link, LinkType, Status


def _link(target):
    return Link(
        source_file="f.md",
        line=1,
        link_text="text",
        original_target=target,
        normalized_target="",
        link_type=LinkType.LOCAL_ANCHOR,
    )


def test_slugify_basic():
    assert slugify("Installation Guide") == "installation-guide"


def test_slugify_lowercases_and_removes_punctuation():
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_collapses_whitespace():
    assert slugify("Too    Many   Spaces") == "too-many-spaces"


def test_slugify_preserves_unicode_letters():
    assert slugify("Héllo Wörld") == "héllo-wörld"


def test_slugify_strips_markdown_formatting():
    assert slugify("**Bold** and `code`") == "bold-and-code"


def test_extract_headings_ignores_fenced_code():
    text = "# Real Heading\n\n```\n# Not a heading\n```\n\n## Another\n"
    headings = extract_headings(text)
    assert headings == ["Real Heading", "Another"]


def test_generate_slugs_duplicates_get_suffix():
    slugs = generate_slugs(["Overview", "Overview", "Overview"])
    assert slugs == ["overview", "overview-1", "overview-2"]


def test_check_anchor_in_current_file(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Installation\n", encoding="utf-8")
    link = _link("#installation")
    result = check_anchor(link, source, "installation")
    assert result.status == Status.OK


def test_check_anchor_in_another_file(tmp_path):
    guide = tmp_path / "guide.md"
    guide.write_text("# Configuration\n", encoding="utf-8")
    link = _link("guide.md#configuration")
    result = check_anchor(link, guide, "configuration")
    assert result.status == Status.OK


def test_check_missing_anchor(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Installation\n", encoding="utf-8")
    link = _link("#missing")
    result = check_anchor(link, source, "missing")
    assert result.status == Status.BROKEN
    assert "missing" in result.message


def test_heading_with_spaces(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Getting Started Guide\n", encoding="utf-8")
    link = _link("#getting-started-guide")
    result = check_anchor(link, source, "getting-started-guide")
    assert result.status == Status.OK


def test_unicode_heading(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Héllo Wörld\n", encoding="utf-8")
    link = _link("#héllo-wörld")
    result = check_anchor(link, source, "héllo-wörld")
    assert result.status == Status.OK


def test_duplicate_headings(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Overview\n\n## Overview\n", encoding="utf-8")
    link = _link("#overview-1")
    result = check_anchor(link, source, "overview-1")
    assert result.status == Status.OK


def test_markdown_formatting_inside_heading(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# **Important** Notes\n", encoding="utf-8")
    link = _link("#important-notes")
    result = check_anchor(link, source, "important-notes")
    assert result.status == Status.OK


def test_empty_fragment_is_valid(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Anything\n", encoding="utf-8")
    link = _link("guide.md#")
    result = check_anchor(link, source, "")
    assert result.status == Status.OK


def test_anchor_checking_disabled(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Installation\n", encoding="utf-8")
    link = _link("#missing")
    result = check_anchor(link, source, "missing", enabled=False)
    assert result.status == Status.SKIPPED
