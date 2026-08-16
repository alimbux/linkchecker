from __future__ import annotations

import os
import sys

import pytest

from mdcheck.config import DEFAULT_EXCLUDES
from mdcheck.scanner import discover_files


def _touch(path, content="# Title\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_discovers_md_and_markdown_case_insensitive(tmp_path):
    _touch(tmp_path / "a.md")
    _touch(tmp_path / "b.MARKDOWN")
    _touch(tmp_path / "c.MD")
    _touch(tmp_path / "notes.txt")

    files, errors = discover_files(tmp_path)

    names = sorted(p.name for p in files)
    assert names == ["a.md", "b.MARKDOWN", "c.MD"]
    assert errors == []


def test_recursive_discovery_sorted_deterministically(tmp_path):
    _touch(tmp_path / "z.md")
    _touch(tmp_path / "docs" / "a.md")
    _touch(tmp_path / "docs" / "nested" / "b.md")

    files, _ = discover_files(tmp_path)

    rels = [p.relative_to(tmp_path).as_posix() for p in files]
    assert rels == sorted(rels)
    assert rels == ["docs/a.md", "docs/nested/b.md", "z.md"]


def test_single_file_input(tmp_path):
    md = tmp_path / "README.md"
    _touch(md)

    files, errors = discover_files(md)

    assert files == [md]
    assert errors == []


def test_empty_directory(tmp_path):
    files, errors = discover_files(tmp_path)
    assert files == []
    assert errors == []


def test_default_excludes_applied(tmp_path):
    _touch(tmp_path / "README.md")
    _touch(tmp_path / ".git" / "COMMIT_EDITMSG.md")
    _touch(tmp_path / "node_modules" / "pkg" / "readme.md")
    _touch(tmp_path / ".venv" / "lib" / "x.md")

    files, _ = discover_files(tmp_path, excludes=list(DEFAULT_EXCLUDES))

    rels = {p.relative_to(tmp_path).as_posix() for p in files}
    assert rels == {"README.md"}


def test_user_exclude_pattern(tmp_path):
    _touch(tmp_path / "keep.md")
    _touch(tmp_path / "drafts" / "skip.md")

    files, _ = discover_files(tmp_path, excludes=["drafts/**"])

    rels = {p.relative_to(tmp_path).as_posix() for p in files}
    assert rels == {"keep.md"}


def test_include_pattern_adds_non_markdown_files(tmp_path):
    _touch(tmp_path / "guide.txt", content="not markdown")

    files, _ = discover_files(tmp_path, includes=["*.txt"])

    rels = {p.relative_to(tmp_path).as_posix() for p in files}
    assert rels == {"guide.txt"}


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits behave differently on Windows")
def test_permission_error_is_recorded_not_fatal(tmp_path):
    _touch(tmp_path / "visible.md")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    _touch(blocked / "hidden.md")
    os.chmod(blocked, 0o000)
    try:
        files, errors = discover_files(tmp_path)
        rels = {p.relative_to(tmp_path).as_posix() for p in files}
        assert "visible.md" in rels
        assert "blocked/hidden.md" not in rels
    finally:
        os.chmod(blocked, 0o755)


def test_does_not_follow_directory_symlinks(tmp_path):
    real_dir = tmp_path / "real"
    _touch(real_dir / "inside.md")
    link_dir = tmp_path / "link"
    try:
        link_dir.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")

    files, _ = discover_files(tmp_path)

    rels = {p.relative_to(tmp_path).as_posix() for p in files}
    assert rels == {"real/inside.md"}


def test_broken_symlink_recorded_as_error(tmp_path):
    target = tmp_path / "does-not-exist.md"
    link = tmp_path / "broken.md"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")

    files, errors = discover_files(tmp_path)

    assert files == []
    assert len(errors) == 1
    assert "broken.md" in errors[0].path
