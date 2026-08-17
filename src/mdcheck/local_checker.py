"""Validation of local filesystem paths and ``file://`` URIs."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from mdcheck.models import Link, LinkResult, LinkType, Status

ABSOLUTE_RE = re.compile(r"^[A-Za-z]:/|^/")
WINDOWS_PATH_IN_FILE_URI_RE = re.compile(r"^/[A-Za-z]:")


def resolve_local_path(source_path: Path, normalized_target: str) -> Path:
    """Resolve a normalized local target against the file that referenced it."""
    if not normalized_target:
        return source_path
    if ABSOLUTE_RE.match(normalized_target):
        return Path(normalized_target)
    return source_path.parent / normalized_target


def _missing_result(link: Link, target_path: Path) -> LinkResult | None:
    """A BROKEN result if ``target_path`` doesn't exist, else None."""
    try:
        is_symlink = target_path.is_symlink()
    except OSError:
        is_symlink = False
    try:
        exists = target_path.exists()
    except OSError:
        exists = False

    if is_symlink and not exists:
        return LinkResult.from_link(link, Status.BROKEN, message="broken symbolic link")
    if not exists:
        return LinkResult.from_link(link, Status.BROKEN, message="no such file or directory")
    return None


def check_local(link: Link, source_path: Path, *, enabled: bool = True) -> LinkResult:
    if not enabled:
        return LinkResult.from_link(link, Status.SKIPPED, message="local link checking disabled")

    if not link.normalized_target:
        return LinkResult.from_link(link, Status.BROKEN, message="empty local target")

    target_path = resolve_local_path(source_path, link.normalized_target)

    missing = _missing_result(link, target_path)
    if missing is not None:
        return missing

    try:
        is_dir = target_path.is_dir()
    except OSError:
        is_dir = False

    link_type = LinkType.LOCAL_DIRECTORY if is_dir else LinkType.LOCAL_FILE
    result = LinkResult.from_link(link, Status.OK)
    result.link_type = link_type
    return result


def check_file_uri(link: Link, *, enabled: bool = True) -> LinkResult:
    if not enabled:
        return LinkResult.from_link(link, Status.SKIPPED, message="local link checking disabled")

    parsed = urlsplit(link.original_target)
    host = parsed.netloc
    if host and host.lower() != "localhost":
        return LinkResult.from_link(link, Status.SKIPPED, message="remote file URI is unsupported")

    path = unquote(parsed.path)
    if WINDOWS_PATH_IN_FILE_URI_RE.match(path):
        path = path[1:]
    if not path:
        return LinkResult.from_link(link, Status.INVALID, message="malformed file:// URI")

    target_path = Path(path)
    missing = _missing_result(link, target_path)
    return missing if missing is not None else LinkResult.from_link(link, Status.OK)
