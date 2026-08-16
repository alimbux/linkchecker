"""Runtime configuration for a single mdcheck run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git/**",
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "dist/**",
    "build/**",
    "__pycache__/**",
)

DEFAULT_USER_AGENT = "mdcheck/{version} (+https://example.invalid/mdcheck)"

DEFAULT_TIMEOUT = 5.0
DEFAULT_WORKERS = 10
DEFAULT_RETRIES = 1


@dataclass
class Config:
    path: Path
    timeout: float = DEFAULT_TIMEOUT
    workers: int = DEFAULT_WORKERS
    retries: int = DEFAULT_RETRIES
    check_external: bool = True
    check_local: bool = True
    check_anchors: bool = True
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    ignore_url: list[str] = field(default_factory=list)
    user_agent: str = ""
    format: str = "console"
    output: Path | None = None
    no_color: bool = False
    quiet: bool = False
    verbose: bool = False

    @property
    def all_excludes(self) -> list[str]:
        return [*DEFAULT_EXCLUDES, *self.exclude]
