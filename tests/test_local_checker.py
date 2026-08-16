from __future__ import annotations

import sys

import pytest

from mdcheck.local_checker import check_file_uri, check_local
from mdcheck.models import Link, LinkType, Status
from mdcheck.parser import classify_target, normalize_target


def _link(source_file, line, target):
    link_type = classify_target(target)
    normalized = normalize_target(target, link_type)
    return Link(
        source_file=source_file,
        line=line,
        link_text="text",
        original_target=target,
        normalized_target=normalized,
        link_type=link_type,
    )


def test_existing_file(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    source = tmp_path / "README.md"
    link = _link("README.md", 1, "guide.md")
    result = check_local(link, source)
    assert result.status == Status.OK
    assert result.link_type == LinkType.LOCAL_FILE


def test_missing_file(tmp_path):
    source = tmp_path / "README.md"
    link = _link("README.md", 1, "missing.md")
    result = check_local(link, source)
    assert result.status == Status.BROKEN


def test_relative_to_nested_markdown_file(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "docs" / "index.md").write_text("# Index\n", encoding="utf-8")
    source = tmp_path / "docs" / "index.md"

    link = _link("docs/index.md", 1, "guide.md")
    result = check_local(link, source)

    assert result.status == Status.OK


def test_relative_to_nested_file_does_not_resolve_to_root(tmp_path):
    # A file at the project root with the same name must NOT satisfy the link;
    # the link must resolve relative to docs/, not the scan root.
    (tmp_path / "guide.md").write_text("# Root guide\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    source = tmp_path / "docs" / "index.md"
    source.write_text("# Index\n", encoding="utf-8")

    link = _link("docs/index.md", 1, "guide.md")
    result = check_local(link, source)

    assert result.status == Status.BROKEN


def test_path_with_dotdot(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "top.md").write_text("# Top\n", encoding="utf-8")
    source = tmp_path / "docs" / "index.md"

    link = _link("docs/index.md", 1, "../top.md")
    result = check_local(link, source)

    assert result.status == Status.OK


def test_filename_with_space_and_percent_encoding(tmp_path):
    (tmp_path / "My Documents").mkdir()
    (tmp_path / "My Documents" / "report.pdf").write_bytes(b"%PDF-1.4")
    source = tmp_path / "README.md"

    link = _link("README.md", 1, "My%20Documents/report.pdf")
    result = check_local(link, source)

    assert result.status == Status.OK


def test_unicode_path(tmp_path):
    (tmp_path / "café").mkdir()
    (tmp_path / "café" / "menu.md").write_text("# Menu\n", encoding="utf-8")
    source = tmp_path / "README.md"

    link = _link("README.md", 1, "café/menu.md")
    result = check_local(link, source)

    assert result.status == Status.OK


def test_fragment_excluded_from_filename(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    source = tmp_path / "README.md"

    link = _link("README.md", 1, "guide.md#section")
    assert link.normalized_target == "guide.md"
    result = check_local(link, source)

    assert result.status == Status.OK


def test_query_excluded_from_filename(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n", encoding="utf-8")
    source = tmp_path / "README.md"

    link = _link("README.md", 1, "guide.md?version=2")
    assert link.normalized_target == "guide.md"
    result = check_local(link, source)

    assert result.status == Status.OK


def test_absolute_path(tmp_path):
    target = tmp_path / "abs.md"
    target.write_text("# Abs\n", encoding="utf-8")
    source = tmp_path / "sub" / "README.md"

    link = _link("sub/README.md", 1, str(target))
    result = check_local(link, source)

    assert result.status == Status.OK


def test_existing_directory_is_valid(tmp_path):
    (tmp_path / "docs").mkdir()
    source = tmp_path / "README.md"

    link = _link("README.md", 1, "docs")
    result = check_local(link, source)

    assert result.status == Status.OK
    assert result.link_type == LinkType.LOCAL_DIRECTORY


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_broken_symlink_is_broken(tmp_path):
    target = tmp_path / "missing.md"
    link_path = tmp_path / "broken.md"
    link_path.symlink_to(target)
    source = tmp_path / "README.md"

    link = _link("README.md", 1, "broken.md")
    result = check_local(link, source)

    assert result.status == Status.BROKEN
    assert "symbolic link" in result.message


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_valid_symlink_is_ok(tmp_path):
    target = tmp_path / "real.md"
    target.write_text("# Real\n", encoding="utf-8")
    link_path = tmp_path / "sym.md"
    link_path.symlink_to(target)
    source = tmp_path / "README.md"

    link = _link("README.md", 1, "sym.md")
    result = check_local(link, source)

    assert result.status == Status.OK


def test_disabled_local_checking_is_skipped(tmp_path):
    source = tmp_path / "README.md"
    link = _link("README.md", 1, "missing.md")
    result = check_local(link, source, enabled=False)
    assert result.status == Status.SKIPPED


def test_file_uri_existing(tmp_path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF")
    link = _link("README.md", 1, f"file://{target}")
    result = check_file_uri(link)
    assert result.status == Status.OK


def test_file_uri_missing():
    link = _link("README.md", 1, "file:///no/such/file/exists.pdf")
    result = check_file_uri(link)
    assert result.status == Status.BROKEN


def test_file_uri_localhost(tmp_path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF")
    link = _link("README.md", 1, f"file://localhost{target}")
    result = check_file_uri(link)
    assert result.status == Status.OK


def test_file_uri_remote_host_is_skipped():
    link = _link("README.md", 1, "file://otherhost/tmp/report.pdf")
    result = check_file_uri(link)
    assert result.status == Status.SKIPPED
    assert "remote file URI is unsupported" in result.message


def test_file_uri_windows_drive():
    link = _link("README.md", 1, "file:///C:/docs/report.pdf")
    result = check_file_uri(link)
    # File does not exist on this machine, but the path must be parsed
    # without an extraneous leading slash before the drive letter.
    assert result.status == Status.BROKEN
    assert "report.pdf" in link.original_target
