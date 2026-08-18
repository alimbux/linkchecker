from __future__ import annotations

import json

import pytest

from mdcheck.models import Link, LinkResult, LinkType, Status
from mdcheck.reporter import build_summary, render_console, render_json


def _result(status, **kwargs):
    link = Link(
        source_file=kwargs.pop("source_file", "docs/start.md"),
        line=kwargs.pop("line", 18),
        link_text=kwargs.pop("link_text", "Old documentation"),
        original_target=kwargs.pop("original_target", "https://example.com/old"),
        normalized_target=kwargs.pop("normalized_target", "https://example.com/old"),
        link_type=kwargs.pop("link_type", LinkType.HTTPS),
    )
    return LinkResult.from_link(link, status, **kwargs)


def test_build_summary_counts():
    results = [
        _result(Status.OK),
        _result(Status.BROKEN, http_status=404, message="Not Found"),
        _result(Status.WARNING, http_status=401),
        _result(Status.SKIPPED, message="skip"),
    ]
    summary = build_summary(files_scanned=2, links_found=4, results=results, duration_ms=1234)
    assert summary["files_scanned"] == 2
    assert summary["links_found"] == 4
    assert summary["ok"] == 1
    assert summary["broken"] == 1
    assert summary["warnings"] == 1
    assert summary["skipped"] == 1
    assert summary["duration_ms"] == 1234


def test_json_output_is_valid_and_matches_schema():
    results = [_result(Status.BROKEN, http_status=404, message="Not Found")]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=143)
    text = render_json(summary, results)
    data = json.loads(text)
    assert data["summary"]["broken"] == 1
    result = data["results"][0]
    assert result["source_file"] == "docs/start.md"
    assert result["line"] == 18
    assert result["status"] == "BROKEN"
    assert result["http_status"] == 404
    assert result["final_url"] is None
    assert result["elapsed_ms"] is None


def test_json_valid_even_with_no_results():
    summary = build_summary(files_scanned=0, links_found=0, results=[], duration_ms=0)
    text = render_json(summary, [])
    data = json.loads(text)
    assert data["results"] == []


def test_console_report_contains_summary_and_table():
    results = [_result(Status.BROKEN, http_status=404, message="Not Found")]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=100)
    output = render_console(summary, results, no_color=True)
    assert "Markdown Link Checker" in output
    assert "Scanned:  1 files" in output
    assert "docs/start.md" in output
    assert "BROKEN" in output


def test_console_no_color_has_no_ansi_sequences():
    results = [_result(Status.BROKEN, http_status=404, message="Not Found")]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=100)
    output = render_console(summary, results, no_color=True)
    assert "\x1b[" not in output


def test_console_verbose_shows_ok_results():
    results = [_result(Status.OK)]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True, verbose=True)
    assert "OK" in output
    assert "docs/start.md" in output


def test_console_default_hides_ok_results():
    results = [_result(Status.OK)]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True, verbose=False)
    assert "No problems found." in output


def test_console_quiet_suppresses_summary_lines():
    results = [_result(Status.BROKEN, http_status=404, message="Not Found")]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True, quiet=True)
    assert "Scanned:" not in output
    assert "docs/start.md" in output


def test_console_target_column_is_last_and_wraps_long_links():
    long_url = "https://example.com/" + "a" * 150
    results = [
        _result(
            Status.BROKEN,
            http_status=404,
            message="Not Found",
            original_target=long_url,
            normalized_target=long_url,
        )
    ]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True)
    header_line = next(line for line in output.splitlines() if "File" in line and "Status" in line)
    assert header_line.index("Target") > header_line.index("Details")
    # A very long link must not stretch the console; it wraps onto multiple
    # table rows instead of appearing intact on a single line.
    assert long_url not in output
    assert "aaaa" in output


def test_console_file_column_wraps_long_paths_instead_of_truncating():
    long_path = "docs/" + "nested/" * 20 + "page.md"
    results = [_result(Status.BROKEN, http_status=404, message="Not Found", source_file=long_path)]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True)
    assert "..." not in output
    assert "page.md" in output


def test_console_file_and_target_do_not_starve_each_other():
    # A pathologically long File value (e.g. an absolute path from a
    # single-file scan) must not force the Target column down to an
    # unreadable, single-character width.
    long_path = "/private/var/" + "folders/" * 15 + "README.md"
    results = [_result(Status.BROKEN, http_status=404, message="Not Found", source_file=long_path)]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True, width=100)
    assert "example.com/old" in output


@pytest.mark.parametrize("width", [60, 100, 160])
def test_console_table_fits_within_requested_width(width):
    long_url = "https://example.com/" + "path/" * 10 + "page"
    results = [
        _result(
            Status.BROKEN,
            http_status=404,
            message="Not Found",
            original_target=long_url,
            normalized_target=long_url,
        )
    ]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True, width=width)
    table_lines = [
        line for line in output.splitlines() if line.strip().startswith(("┏", "┃", "┡", "│", "└"))
    ]
    assert table_lines
    for line in table_lines:
        assert len(line) <= width


def test_console_target_gets_the_largest_share_of_width():
    long_url = "https://example.com/" + "path/" * 10 + "page"
    results = [
        _result(
            Status.BROKEN,
            http_status=404,
            message="Not Found",
            source_file="a.md",
            original_target=long_url,
            normalized_target=long_url,
        )
    ]
    summary = build_summary(files_scanned=1, links_found=1, results=results, duration_ms=10)
    output = render_console(summary, results, no_color=True, width=120)
    header_line = next(line for line in output.splitlines() if "File" in line and "Status" in line)
    file_width = header_line.index("Line") - header_line.index("File")
    target_width = len(header_line) - header_line.index("Target")
    assert target_width > file_width
