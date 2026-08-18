"""Command-line interface and run orchestration for mdcheck."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from mdcheck import __version__, anchor_checker, local_checker, reporter, scanner
from mdcheck import parser as link_parser
from mdcheck.config import Config
from mdcheck.http_checker import HttpChecker
from mdcheck.models import FAILING_STATUSES, Link, LinkResult, LinkType, Status

app = typer.Typer(add_completion=False, no_args_is_help=False)

DEFAULT_USER_AGENT_TEMPLATE = "mdcheck/{version} (+https://example.invalid/mdcheck)"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mdcheck {__version__}")
        raise typer.Exit(code=0)


@app.command()
def main(
    path: Path = typer.Argument(Path("."), help="Directory or Markdown file to scan."),
    timeout: float = typer.Option(
        5.0, "--timeout", help="Timeout for one HTTP request; default: 5 seconds"
    ),
    workers: int = typer.Option(
        10, "--workers", help="Maximum concurrent HTTP checks; default: 10"
    ),
    retries: int = typer.Option(
        1, "--retries", help="Retry count for transient failures; default: 1"
    ),
    no_external: bool = typer.Option(False, "--no-external", help="Do not check HTTP/HTTPS links"),
    no_local: bool = typer.Option(False, "--no-local", help="Do not check local links"),
    check_anchors: bool = typer.Option(
        True,
        "--check-anchors/--no-check-anchors",
        help="Check Markdown anchors; enabled by default",
    ),
    include: list[str] = typer.Option(
        [], "--include", help="Additional include pattern; may be repeated"
    ),
    exclude: list[str] = typer.Option([], "--exclude", help="Exclude pattern; may be repeated"),
    ignore_url: list[str] = typer.Option(
        [], "--ignore-url", help="Ignore URL by glob or regex; may be repeated"
    ),
    user_agent: str = typer.Option(None, "--user-agent", help="HTTP User-Agent value"),
    output_format: str = typer.Option(
        "console", "--format", help="Report format: console or json; default: console"
    ),
    output: Path = typer.Option(None, "--output", help="Write the report to a file"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable ANSI colors"),
    quiet: bool = typer.Option(False, "--quiet", help="Show only errors and the summary"),
    verbose: bool = typer.Option(False, "--verbose", help="Show every checked link"),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the program version",
    ),
) -> None:
    """Recursively scan Markdown files and check their links."""
    if output_format not in ("console", "json"):
        typer.echo(
            f"Error: invalid --format {output_format!r}; expected 'console' or 'json'.", err=True
        )
        raise typer.Exit(code=2)
    if timeout <= 0:
        typer.echo("Error: --timeout must be positive.", err=True)
        raise typer.Exit(code=2)
    if workers <= 0:
        typer.echo("Error: --workers must be positive.", err=True)
        raise typer.Exit(code=2)
    if retries < 0:
        typer.echo("Error: --retries must not be negative.", err=True)
        raise typer.Exit(code=2)

    if not path.exists():
        typer.echo(f"Error: path does not exist: {path}", err=True)
        raise typer.Exit(code=2)

    if path.is_dir():
        try:
            next(iter(path.iterdir()), None)
        except OSError as exc:
            typer.echo(f"Error: cannot read directory {path}: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    resolved_agent = user_agent or DEFAULT_USER_AGENT_TEMPLATE.format(version=__version__)

    config = Config(
        path=path,
        timeout=timeout,
        workers=workers,
        retries=retries,
        check_external=not no_external,
        check_local=not no_local,
        check_anchors=check_anchors,
        include=list(include),
        exclude=list(exclude),
        ignore_url=list(ignore_url),
        user_agent=resolved_agent,
        format=output_format,
        output=output,
        no_color=no_color,
        quiet=quiet,
        verbose=verbose,
    )

    try:
        exit_code = asyncio.run(run(config))
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.", err=True)
        raise typer.Exit(code=130) from None
    except Exception as exc:  # noqa: BLE001 - never leak a traceback in normal mode
        if os.environ.get("MDCHECK_DEBUG"):
            raise
        typer.echo(f"Error: unexpected failure: {exc}", err=True)
        raise typer.Exit(code=2) from None

    raise typer.Exit(code=exit_code)


def _display_path(file_path: Path, root: Path) -> str:
    if root.is_file():
        return str(root)
    try:
        return file_path.relative_to(root).as_posix()
    except ValueError:
        return file_path.as_posix()


def _classify_and_check(
    link: Link,
    source_path: Path,
    config: Config,
    anchors_cache: dict[Path, set[str]],
) -> LinkResult | None:
    """Handle every link type except HTTP/HTTPS (those are batched separately)."""
    if link.link_type == LinkType.TEMPLATE:
        return LinkResult.from_link(link, Status.SKIPPED, message="template placeholder")

    if link.link_type == LinkType.UNSUPPORTED:
        return LinkResult.from_link(link, Status.SKIPPED, message="unsupported URL scheme")

    if link.link_type == LinkType.INVALID:
        return LinkResult.from_link(link, Status.INVALID, message="malformed or unsupported target")

    if link.link_type == LinkType.FILE_URI:
        return local_checker.check_file_uri(link, enabled=config.check_local)

    if link.link_type in (LinkType.LOCAL_FILE, LinkType.LOCAL_DIRECTORY, LinkType.LOCAL_ANCHOR):
        path_part, _query, fragment = link_parser.split_target(link.original_target)

        if link.link_type == LinkType.LOCAL_ANCHOR or not path_part:
            return anchor_checker.check_anchor(
                link,
                source_path,
                fragment or "",
                enabled=config.check_anchors,
                anchors_cache=anchors_cache,
            )

        local_result = local_checker.check_local(link, source_path, enabled=config.check_local)
        if not config.check_local:
            return local_result
        if local_result.status != Status.OK:
            return local_result
        if fragment is None or local_result.link_type == LinkType.LOCAL_DIRECTORY:
            return local_result

        target_path = local_checker.resolve_local_path(source_path, link.normalized_target)
        anchor_result = anchor_checker.check_anchor(
            link,
            target_path,
            fragment,
            enabled=config.check_anchors,
            anchors_cache=anchors_cache,
        )
        anchor_result.link_type = local_result.link_type
        return anchor_result

    return None


def _make_progress(config: Config) -> Progress:
    """A progress bar over stderr; disabled when quiet or output isn't a terminal."""
    progress_console = Console(file=sys.stderr, no_color=config.no_color)
    disable = config.quiet or not progress_console.is_terminal
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=progress_console,
        disable=disable,
    )


def _file_error(source_file: str, message: str) -> LinkResult:
    return LinkResult(
        source_file=source_file,
        line=0,
        link_text="",
        original_target="",
        normalized_target="",
        link_type=LinkType.INVALID,
        status=Status.ERROR,
        message=message,
    )


async def run(config: Config) -> int:
    start = time.monotonic()

    files, scan_errors = scanner.discover_files(config.path, config.include, config.all_excludes)

    results: list[LinkResult] = [_file_error(e.path, e.message) for e in scan_errors]

    all_links: list[tuple[Link, Path]] = []
    for file_path in files:
        label = _display_path(file_path, config.path)
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            results.append(_file_error(label, f"could not read file: {exc}"))
            continue
        for link in link_parser.extract_links(label, text):
            all_links.append((link, file_path))

    anchors_cache: dict[Path, set[str]] = {}
    http_links: list[Link] = []

    with _make_progress(config) as progress:
        task = progress.add_task("Checking links...", total=len(all_links) or 1)

        for link, source_path in all_links:
            if link.link_type in (LinkType.HTTP, LinkType.HTTPS):
                if not config.check_external:
                    results.append(
                        LinkResult.from_link(
                            link, Status.SKIPPED, message="external link checking disabled"
                        )
                    )
                    progress.advance(task)
                else:
                    http_links.append(link)
                continue

            result = _classify_and_check(link, source_path, config, anchors_cache)
            if result is not None:
                results.append(result)
            progress.advance(task)

        if http_links:
            checker = HttpChecker(
                timeout=config.timeout,
                workers=config.workers,
                retries=config.retries,
                user_agent=config.user_agent,
                ignore_url_patterns=config.ignore_url,
            )
            results.extend(
                await checker.check_links(
                    http_links, on_progress=lambda n: progress.advance(task, n)
                )
            )

    results.sort(key=lambda r: (r.source_file, r.line, r.original_target))

    duration_ms = (time.monotonic() - start) * 1000
    summary = reporter.build_summary(
        files_scanned=len(files),
        links_found=len(all_links),
        results=results,
        duration_ms=duration_ms,
    )

    use_color = (not config.no_color) and (config.output is None) and sys.stdout.isatty()

    if config.format == "json":
        output_text = reporter.render_json(summary, results)
    else:
        output_text = reporter.render_console(
            summary,
            results,
            no_color=not use_color,
            quiet=config.quiet,
            verbose=config.verbose,
        )

    if config.output is not None:
        try:
            config.output.write_text(output_text, encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Error: cannot write output file: {exc}", err=True)
            return 2
    else:
        sys.stdout.write(output_text)
        if config.format == "json" and not output_text.endswith("\n"):
            sys.stdout.write("\n")

    if any(r.status in FAILING_STATUSES for r in results):
        return 1
    return 0
