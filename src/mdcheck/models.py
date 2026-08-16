"""Enums and dataclasses shared across mdcheck."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class LinkType(enum.StrEnum):
    LOCAL_FILE = "LOCAL_FILE"
    LOCAL_DIRECTORY = "LOCAL_DIRECTORY"
    LOCAL_ANCHOR = "LOCAL_ANCHOR"
    FILE_URI = "FILE_URI"
    HTTP = "HTTP"
    HTTPS = "HTTPS"
    UNSUPPORTED = "UNSUPPORTED"
    TEMPLATE = "TEMPLATE"
    INVALID = "INVALID"


class Status(enum.StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    BROKEN = "BROKEN"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    INVALID = "INVALID"
    SKIPPED = "SKIPPED"


# Statuses that cause exit code 1 when present.
FAILING_STATUSES = frozenset({Status.BROKEN, Status.TIMEOUT, Status.ERROR, Status.INVALID})


@dataclass(frozen=True)
class Link:
    """A link as extracted from a Markdown source file, before validation."""

    source_file: str
    line: int
    link_text: str
    original_target: str
    normalized_target: str
    link_type: LinkType


@dataclass
class LinkResult:
    """The outcome of validating a single extracted link."""

    source_file: str
    line: int
    link_text: str
    original_target: str
    normalized_target: str
    link_type: LinkType
    status: Status
    http_status: int | None = None
    message: str | None = None
    final_url: str | None = None
    elapsed_ms: float | None = None

    @classmethod
    def from_link(cls, link: Link, status: Status, **kwargs: Any) -> LinkResult:
        return cls(
            source_file=link.source_file,
            line=link.line,
            link_text=link.link_text,
            original_target=link.original_target,
            normalized_target=link.normalized_target,
            link_type=link.link_type,
            status=status,
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "line": self.line,
            "link_text": self.link_text,
            "original_target": self.original_target,
            "normalized_target": self.normalized_target,
            "link_type": self.link_type.value,
            "status": self.status.value,
            "http_status": self.http_status,
            "message": self.message,
            "final_url": self.final_url,
            "elapsed_ms": self.elapsed_ms,
        }
