"""Markdown file discovery."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

MARKDOWN_SUFFIXES = {".md", ".markdown"}


@dataclass
class ScanError:
    """A non-fatal error encountered while walking the directory tree."""

    path: str
    message: str


def _matches_any(rel_posix: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(rel_posix, pattern):
            return True
        # Also allow matching against the bare filename, e.g. "*.md".
        if fnmatch.fnmatch(os.path.basename(rel_posix), pattern):
            return True
    return False


def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in MARKDOWN_SUFFIXES


def discover_files(
    root: Path,
    includes: list[str] | None = None,
    excludes: list[str] | None = None,
) -> tuple[list[Path], list[ScanError]]:
    """Discover Markdown files under ``root``.

    ``root`` may be a single file or a directory. Returns a sorted, deterministic
    list of discovered files plus any non-fatal errors encountered while walking.
    """
    includes = includes or []
    excludes = excludes or []
    errors: list[ScanError] = []

    if root.is_file():
        return [root], errors

    found: list[Path] = []

    def on_error(exc: OSError) -> None:
        errors.append(ScanError(path=str(getattr(exc, "filename", root)), message=str(exc)))

    for dirpath, dirnames, filenames in os.walk(root, onerror=on_error, followlinks=False):
        dir_path = Path(dirpath)

        # Filter out excluded/symlinked directories in-place so os.walk skips them.
        kept_dirnames = []
        for dirname in sorted(dirnames):
            child = dir_path / dirname
            try:
                rel = child.relative_to(root).as_posix()
            except ValueError:
                rel = dirname
            if child.is_symlink():
                continue
            if _matches_any(rel, list(excludes)):
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in sorted(filenames):
            file_path = dir_path / filename
            try:
                rel = file_path.relative_to(root).as_posix()
            except ValueError:
                rel = filename

            if _matches_any(rel, list(excludes)):
                continue

            is_extra_include = bool(includes) and _matches_any(rel, includes)

            if not _is_markdown(file_path) and not is_extra_include:
                continue

            if file_path.is_symlink() and not file_path.exists():
                # Broken symlink: report as a scan error rather than silently skipping.
                errors.append(ScanError(path=str(file_path), message="broken symbolic link"))
                continue

            found.append(file_path)

    found.sort(key=lambda p: p.as_posix())
    return found, errors
