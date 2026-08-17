"""Markdown link extraction.

Extracts inline links, reference-style links, autolinks, and HTML ``<a href>``
links from Markdown source text, while ignoring images, fenced code blocks,
inline code spans, and HTML comments.
"""

from __future__ import annotations

import bisect
import posixpath
import re
from urllib.parse import unquote

from mdcheck.models import Link, LinkType

FENCE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)*?\1", re.DOTALL)
AUTOLINK_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.\-]*:[^<>\s]+)>")
HTML_A_RE = re.compile(
    r"<a\b[^>]*?\bhref\s*=\s*(\"([^\"]*)\"|'([^']*)')[^>]*>(.*?)</a\s*>|"
    r"<a\b[^>]*?\bhref\s*=\s*(\"([^\"]*)\"|'([^']*)')[^>]*/?>",
    re.IGNORECASE | re.DOTALL,
)
TAG_STRIP_RE = re.compile(r"<[^>]*>")
REF_DEF_RE = re.compile(
    r"^[ \t]{0,3}\[(?P<ref>[^\]]+)\]:[ \t]*"
    r"(?P<target><[^>\n]*>|\S+)"
    r'[ \t]*(?:"(?P<t1>[^"]*)"|\'(?P<t2>[^\']*)\'|\((?P<t3>[^)]*)\))?[ \t]*$',
    re.MULTILINE,
)
TEMPLATE_RE = re.compile(r"\$\{[^}]*\}|\{\{[^}]*\}\}")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")


def mask_fenced_code_blocks(text: str) -> str:
    """Blank out fenced (``` or ~~~) code blocks, preserving offsets/lines."""
    lines = text.split("\n")
    out_lines: list[str] = []
    fence_char = None
    fence_len = 0
    in_fence = False
    for line in lines:
        m = FENCE_RE.match(line)
        if in_fence:
            if m and m.group(2)[0] == fence_char and len(m.group(2)) >= fence_len:
                in_fence = False
            out_lines.append(" " * len(line))
            continue
        if m:
            in_fence = True
            fence_char = m.group(2)[0]
            fence_len = len(m.group(2))
            out_lines.append(" " * len(line))
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def mask_text(text: str) -> str:
    """Blank out fenced code blocks, inline code spans, and HTML comments.

    Replaces masked characters with spaces (never removing characters), so
    string offsets and line numbers of the surrounding text are preserved.
    """
    masked = mask_fenced_code_blocks(text)
    masked = HTML_COMMENT_RE.sub(lambda m: _blank(m.group(0)), masked)
    masked = INLINE_CODE_RE.sub(lambda m: _blank(m.group(0)), masked)
    return masked


def _blank(s: str) -> str:
    return "".join(ch if ch == "\n" else " " for ch in s)


def is_template(target: str) -> bool:
    return bool(TEMPLATE_RE.search(target))


def classify_target(target: str) -> LinkType:
    if is_template(target):
        return LinkType.TEMPLATE
    stripped = target.strip()
    if not stripped:
        return LinkType.INVALID
    if stripped.startswith("#"):
        return LinkType.LOCAL_ANCHOR
    if WINDOWS_DRIVE_RE.match(stripped):
        return LinkType.LOCAL_FILE
    scheme_match = SCHEME_RE.match(stripped)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme == "http":
            return LinkType.HTTP
        if scheme == "https":
            return LinkType.HTTPS
        if scheme == "file":
            return LinkType.FILE_URI
        if scheme in ("mailto", "tel", "javascript", "data"):
            return LinkType.UNSUPPORTED
        return LinkType.INVALID
    return LinkType.LOCAL_FILE


def split_target(target: str) -> tuple[str, str | None, str | None]:
    """Split a local target into (path_part, query, fragment)."""
    if "#" in target:
        path_part, _, fragment = target.partition("#")
    else:
        path_part, fragment = target, None
    if "?" in path_part:
        path_part, _, query = path_part.partition("?")
    else:
        query = None
    return path_part, query, fragment


def normalize_local_target(path_part: str) -> str:
    """URL-decode and normalize ``.``/``..`` segments, preserving case."""
    decoded = unquote(path_part)
    posix_style = decoded.replace("\\", "/")
    if not posix_style:
        return ""
    normalized = posixpath.normpath(posix_style)
    if normalized == ".":
        return ""
    # posixpath.normpath collapses a leading "//" oddly; keep it simple for
    # single leading slashes (the common case for absolute paths).
    if posix_style.startswith("/") and not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def normalize_target(target: str, link_type: LinkType) -> str:
    if link_type in (LinkType.LOCAL_FILE, LinkType.LOCAL_DIRECTORY, LinkType.LOCAL_ANCHOR):
        path_part, _query, _fragment = split_target(target)
        return normalize_local_target(path_part)
    return target.strip()


def _strip_inline_formatting(text: str) -> str:
    text = TAG_STRIP_RE.sub("", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_~]+", "", text)
    return text.strip()


class _LineIndex:
    def __init__(self, text: str) -> None:
        self._starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self._starts.append(i + 1)

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self._starts, offset)


def _find_matching(s: str, start: int, open_ch: str, close_ch: str) -> int:
    """Find the index closing the bracket/paren pair opened at ``s[start]``."""
    depth = 0
    i = start
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_matching_bracket(s: str, start: int) -> int:
    return _find_matching(s, start, "[", "]")


def _find_matching_paren(s: str, start: int) -> int:
    return _find_matching(s, start, "(", ")")


TRAILING_TITLE_RE = re.compile(r"""\s+("[^"]*"|'[^']*')\s*$""")


def _parse_link_destination(content: str) -> str:
    content = content.strip()
    if content.startswith("<"):
        end = content.find(">")
        if end != -1:
            return content[1:end]
    m = TRAILING_TITLE_RE.search(content)
    if m:
        return content[: m.start()].strip()
    return content


def extract_links(source_file: str, text: str) -> list[Link]:
    """Extract all checkable links from a single Markdown document."""
    masked = mask_text(text)

    # 1. Collect reference-link definitions, then blank those lines out so
    #    they aren't re-parsed as ordinary links.
    references: dict[str, str] = {}
    spans_to_blank: list[tuple[int, int]] = []
    for m in REF_DEF_RE.finditer(masked):
        ref_key = m.group("ref").strip().lower()
        target = _parse_link_destination(m.group("target"))
        references.setdefault(ref_key, target)
        spans_to_blank.append(m.span())

    if spans_to_blank:
        chars = list(masked)
        for start, end in spans_to_blank:
            for i in range(start, end):
                if chars[i] != "\n":
                    chars[i] = " "
        masked = "".join(chars)

    line_index = _LineIndex(text)
    links: list[Link] = []
    n = len(masked)
    i = 0

    def add(offset: int, link_text: str, target: str) -> None:
        target = target.strip()
        if not target:
            return
        link_type = classify_target(target)
        normalized = normalize_target(target, link_type)
        links.append(
            Link(
                source_file=source_file,
                line=line_index.line_of(offset),
                link_text=link_text.strip(),
                original_target=target,
                normalized_target=normalized,
                link_type=link_type,
            )
        )

    while i < n:
        ch = masked[i]

        if ch == "<":
            m = AUTOLINK_RE.match(masked, i)
            if m:
                target = m.group(1)
                add(i, target, target)
                i = m.end()
                continue

        if ch == "!" and i + 1 < n and masked[i + 1] == "[":
            close = _find_matching_bracket(masked, i + 1)
            if close != -1:
                if close + 1 < n and masked[close + 1] == "(":
                    paren_close = _find_matching_paren(masked, close + 1)
                    if paren_close != -1:
                        i = paren_close + 1
                        continue
                i = close + 1
                continue

        if ch == "[":
            close = _find_matching_bracket(masked, i)
            if close != -1:
                link_text = masked[i + 1 : close]
                rest_start = close + 1
                if rest_start < n and masked[rest_start] == "(":
                    paren_close = _find_matching_paren(masked, rest_start)
                    if paren_close != -1:
                        inner = masked[rest_start + 1 : paren_close]
                        target = _parse_link_destination(inner)
                        add(i, link_text, target)
                        i = paren_close + 1
                        continue
                if rest_start < n and masked[rest_start] == "[":
                    close2 = _find_matching_bracket(masked, rest_start)
                    if close2 != -1:
                        ref_label = masked[rest_start + 1 : close2].strip()
                        ref_key = (ref_label or link_text).strip().lower()
                        if ref_key in references:
                            add(i, link_text, references[ref_key])
                            i = close2 + 1
                            continue
                ref_key = link_text.strip().lower()
                if ref_key in references:
                    add(i, link_text, references[ref_key])
                    i = close + 1
                    continue
                i = close + 1
                continue

        i += 1

    for m in HTML_A_RE.finditer(masked):
        href = m.group(2) or m.group(3) or m.group(6) or m.group(7)
        if href is None:
            continue
        inner_html = m.group(4) or ""
        link_text = _strip_inline_formatting(inner_html) if inner_html else ""
        add(m.start(), link_text, href)

    links.sort(key=lambda link: (link.line, link.source_file))
    return links
