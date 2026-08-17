"""Console (rich) and JSON reporting."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

from rich.box import HEAVY_HEAD
from rich.console import Console
from rich.table import Table

from mdcheck.models import LinkResult, Status

STATUS_STYLES: dict[Status, str] = {
    Status.OK: "green",
    Status.WARNING: "yellow",
    Status.SKIPPED: "yellow",
    Status.BROKEN: "red",
    Status.ERROR: "red",
    Status.INVALID: "red",
    Status.TIMEOUT: "bright_magenta",
}


def build_summary(
    *,
    files_scanned: int,
    links_found: int,
    results: list[LinkResult],
    duration_ms: float,
) -> dict[str, Any]:
    unique_targets = {r.normalized_target for r in results}
    counts = dict.fromkeys(Status, 0)
    for r in results:
        counts[r.status] += 1
    return {
        "files_scanned": files_scanned,
        "links_found": links_found,
        "unique_targets_checked": len(unique_targets),
        "ok": counts[Status.OK],
        "warnings": counts[Status.WARNING],
        "broken": counts[Status.BROKEN],
        "timeouts": counts[Status.TIMEOUT],
        "errors": counts[Status.ERROR],
        "invalid": counts[Status.INVALID],
        "skipped": counts[Status.SKIPPED],
        "duration_ms": round(duration_ms),
    }


def _details(result: LinkResult) -> str:
    parts = []
    if result.http_status is not None:
        parts.append(str(result.http_status))
    if result.message:
        parts.append(result.message)
    return " - ".join(parts) if parts else ""


def render_console(
    summary: dict[str, Any],
    results: list[LinkResult],
    *,
    no_color: bool = False,
    quiet: bool = False,
    verbose: bool = False,
    file=None,
) -> str:
    if verbose:
        shown = results
    else:
        shown = [r for r in results if r.status != Status.OK]

    # The Target column never wraps, so the console must be wide enough to
    # fit the longest link on one line instead of squeezing every column.
    longest_target = max((len(r.normalized_target or r.original_target) for r in shown), default=0)
    console_width = max(100, longest_target + 60)

    buffer = StringIO()
    console = Console(
        file=buffer,
        force_terminal=not no_color,
        no_color=no_color,
        color_system=None if no_color else "standard",
        width=console_width,
        highlight=False,
    )

    if not quiet:
        console.print("[bold]Markdown Link Checker[/bold]\n")
        console.print(f"Scanned:  {summary['files_scanned']} files")
        console.print(f"Found:    {summary['links_found']} links")
        console.print(f"Checked:  {summary['unique_targets_checked']} unique targets")
        console.print(f"Broken:   {summary['broken']}")
        console.print(f"Warnings: {summary['warnings']}")
        console.print(f"Skipped:  {summary['skipped']}")
        if summary["timeouts"]:
            console.print(f"Timeouts: {summary['timeouts']}")
        if summary["errors"]:
            console.print(f"Errors:   {summary['errors']}")
        if summary["invalid"]:
            console.print(f"Invalid:  {summary['invalid']}")
        console.print(f"Duration: {summary['duration_ms'] / 1000:.2f}s")
        console.print()

    if shown:
        table = Table(box=HEAVY_HEAD, header_style="bold")
        table.add_column("File")
        table.add_column("Line", justify="right")
        table.add_column("Status")
        table.add_column("Details", overflow="fold")
        table.add_column("Target", overflow="ignore", no_wrap=True)
        for r in shown:
            style = STATUS_STYLES.get(r.status, "")
            table.add_row(
                r.source_file,
                str(r.line),
                f"[{style}]{r.status.value}[/{style}]" if style else r.status.value,
                _details(r),
                r.normalized_target or r.original_target,
            )
        console.print(table)
    elif not quiet:
        console.print("[green]No problems found.[/green]")

    return buffer.getvalue()


def render_json(summary: dict[str, Any], results: list[LinkResult]) -> str:
    payload = {
        "summary": summary,
        "results": [r.to_dict() for r in results],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
