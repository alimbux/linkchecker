"""Heading extraction, slug generation, and anchor validation."""

from __future__ import annotations

import re
from pathlib import Path

from mdcheck.models import Link, LinkResult, Status
from mdcheck.parser import mask_fenced_code_blocks

ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$", re.MULTILINE)
INLINE_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
TAG_RE = re.compile(r"<[^>]*>")
PUNCTUATION_RE = re.compile(r"[^\w\s-]", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")


def slugify(heading: str) -> str:
    """Generate a GitHub-style slug for a single heading's text."""
    text = INLINE_LINK_RE.sub(r"\1", heading)
    text = TAG_RE.sub("", text)
    text = re.sub(r"[`*_~]+", "", text)
    text = text.strip().lower()
    text = PUNCTUATION_RE.sub("", text)
    text = WHITESPACE_RE.sub("-", text.strip())
    return text


def extract_headings(text: str) -> list[str]:
    """Extract raw ATX heading text (in document order), ignoring code fences."""
    masked = mask_fenced_code_blocks(text)
    headings = []
    for m in ATX_HEADING_RE.finditer(masked):
        headings.append((m.group(2) or "").strip())
    return headings


def generate_slugs(headings: list[str]) -> list[str]:
    """Slugify headings, disambiguating duplicates with -1, -2, ..."""
    seen: dict[str, int] = {}
    slugs = []
    for heading in headings:
        base = slugify(heading)
        count = seen.get(base, 0)
        seen[base] = count + 1
        slugs.append(base if count == 0 else f"{base}-{count}")
    return slugs


def file_anchors(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    except UnicodeDecodeError:
        return set()
    return set(generate_slugs(extract_headings(text)))


def check_anchor(
    link: Link,
    target_path: Path,
    fragment: str,
    *,
    enabled: bool = True,
    anchors_cache: dict[Path, set[str]] | None = None,
) -> LinkResult:
    if not enabled:
        return LinkResult.from_link(link, Status.SKIPPED, message="anchor checking disabled")

    if fragment == "":
        return LinkResult.from_link(link, Status.OK)

    cache = anchors_cache if anchors_cache is not None else {}
    resolved = target_path.resolve() if target_path.exists() else target_path
    if resolved not in cache:
        cache[resolved] = file_anchors(target_path)
    anchors = cache[resolved]

    if fragment in anchors:
        return LinkResult.from_link(link, Status.OK)
    return LinkResult.from_link(link, Status.BROKEN, message=f"anchor not found: #{fragment}")
