from __future__ import annotations

import json

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
