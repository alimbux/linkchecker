from __future__ import annotations

import asyncio
import json
import os
from io import StringIO

import httpx
import pytest
from typer.testing import CliRunner

from mdcheck.cli import _make_progress, app
from mdcheck.cli import run as cli_run
from mdcheck.config import Config
from mdcheck.http_checker import HttpChecker

runner = CliRunner()


class _FakeTerminalStdout(StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def mock_http(monkeypatch):
    """Force every HttpChecker created during a CLI run to use a MockTransport."""

    def _install(handler):
        original_init = HttpChecker.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)

            async def noop_sleep(_delay):
                return None

            kwargs.setdefault("sleep_fn", noop_sleep)
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(HttpChecker, "__init__", patched_init)

    return _install


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scans_current_directory_by_default(tmp_path, monkeypatch):
    _write(tmp_path / "README.md", "# Title\n\n[Guide](guide.md)\n")
    _write(tmp_path / "guide.md", "# Guide\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--no-external"])

    assert result.exit_code == 0
    assert "Scanned:  2 files" in result.stdout


def test_single_input_file(tmp_path):
    md = tmp_path / "README.md"
    _write(md, "# Title\n\n[Missing](missing.md)\n")

    result = runner.invoke(app, [str(md), "--no-external"])

    assert result.exit_code == 1
    assert "Scanned:  1 files" in result.stdout
    assert "missing.md" in result.stdout


def test_nonexistent_path_exits_2(tmp_path):
    result = runner.invoke(app, [str(tmp_path / "does-not-exist")])
    assert result.exit_code == 2


def test_no_external_skips_http_checks(tmp_path, mock_http):
    _write(tmp_path / "README.md", "[Ext](https://example.com)\n")

    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200)

    mock_http(handler)

    result = runner.invoke(app, [str(tmp_path), "--no-external", "--verbose"])

    assert result.exit_code == 0
    assert calls["n"] == 0
    assert "SKIPPED" in result.stdout


def test_no_local_skips_local_checks(tmp_path):
    _write(tmp_path / "README.md", "[Missing](missing.md)\n")

    result = runner.invoke(app, [str(tmp_path), "--no-external", "--no-local", "--verbose"])

    assert result.exit_code == 0
    assert "SKIPPED" in result.stdout


def test_format_json_is_valid(tmp_path):
    _write(tmp_path / "README.md", "[Missing](missing.md)\n")

    result = runner.invoke(app, [str(tmp_path), "--no-external", "--format", "json"])

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["summary"]["broken"] == 1
    assert data["results"][0]["status"] == "BROKEN"


def test_json_valid_even_when_links_fail(tmp_path, mock_http):
    _write(
        tmp_path / "README.md",
        "[Missing](missing.md)\n[Bad](https://example.com/broken)\n[Anchor](#nope)\n",
    )

    def handler(request):
        return httpx.Response(404)

    mock_http(handler)

    result = runner.invoke(app, [str(tmp_path), "--format", "json"])

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert len(data["results"]) == 3
    statuses = {r["status"] for r in data["results"]}
    assert statuses == {"BROKEN"}


def test_output_writes_to_file(tmp_path):
    _write(tmp_path / "README.md", "# Title\n")
    out_file = tmp_path / "report.json"

    result = runner.invoke(
        app, [str(tmp_path), "--no-external", "--format", "json", "--output", str(out_file)]
    )

    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["summary"]["files_scanned"] == 1
    # stdout must stay clean when --output is used.
    assert result.stdout.strip() == ""


def test_exit_code_0_when_all_ok(tmp_path):
    _write(tmp_path / "README.md", "# Title\n\n[Anchor](#title)\n")

    result = runner.invoke(app, [str(tmp_path), "--no-external"])

    assert result.exit_code == 0


def test_exit_code_1_when_broken(tmp_path):
    _write(tmp_path / "README.md", "[Missing](missing.md)\n")

    result = runner.invoke(app, [str(tmp_path), "--no-external"])

    assert result.exit_code == 1


def test_exit_code_2_for_bad_option(tmp_path):
    _write(tmp_path / "README.md", "# Title\n")
    result = runner.invoke(app, [str(tmp_path), "--format", "yaml"])
    assert result.exit_code == 2


def test_no_color_has_no_ansi_sequences(tmp_path):
    _write(tmp_path / "README.md", "[Missing](missing.md)\n")

    result = runner.invoke(app, [str(tmp_path), "--no-external", "--no-color"])

    assert "\x1b[" not in result.stdout


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "mdcheck" in result.stdout


def test_warning_and_skipped_alone_do_not_fail(tmp_path, mock_http):
    _write(tmp_path / "README.md", "[Ext](https://example.com/protected)\n")

    def handler(request):
        return httpx.Response(401)

    mock_http(handler)

    result = runner.invoke(app, [str(tmp_path)])

    assert result.exit_code == 0


def test_keyboard_interrupt_exits_130(tmp_path, monkeypatch):
    _write(tmp_path / "README.md", "# Title\n")

    def raise_interrupt(coro, *args, **kwargs):
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr("mdcheck.cli.asyncio.run", raise_interrupt)

    result = runner.invoke(app, [str(tmp_path), "--no-external"])

    assert result.exit_code == 130
    assert "Interrupted" in result.stderr


def test_unexpected_exception_exits_2_without_traceback(tmp_path, monkeypatch):
    _write(tmp_path / "README.md", "# Title\n")

    def raise_boom(coro, *args, **kwargs):
        coro.close()
        raise RuntimeError("boom")

    monkeypatch.setattr("mdcheck.cli.asyncio.run", raise_boom)
    monkeypatch.delenv("MDCHECK_DEBUG", raising=False)

    result = runner.invoke(app, [str(tmp_path), "--no-external"])

    assert result.exit_code == 2
    assert "Traceback" not in result.stderr
    assert "unexpected failure: boom" in result.stderr


def test_progress_bar_disabled_when_not_a_terminal(tmp_path):
    config = Config(path=tmp_path)
    progress = _make_progress(config)
    assert progress.disable is True


def test_progress_bar_disabled_in_quiet_mode(tmp_path, monkeypatch):
    monkeypatch.setattr("rich.console.Console.is_terminal", property(lambda self: True))
    config = Config(path=tmp_path, quiet=True)
    progress = _make_progress(config)
    assert progress.disable is True


def test_progress_bar_enabled_on_a_real_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr("rich.console.Console.is_terminal", property(lambda self: True))
    config = Config(path=tmp_path, quiet=False)
    progress = _make_progress(config)
    assert progress.disable is False


def test_json_stdout_stays_clean_with_progress_forced_on(tmp_path, monkeypatch):
    monkeypatch.setattr("rich.console.Console.is_terminal", property(lambda self: True))
    _write(tmp_path / "README.md", "[Missing](missing.md)\n")

    result = runner.invoke(app, [str(tmp_path), "--no-external", "--format", "json"])

    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["summary"]["broken"] == 1


@pytest.mark.parametrize("width", [60, 140])
def test_console_table_uses_real_terminal_width(tmp_path, monkeypatch, width):
    long_target = "docs/" + "nested/" * 10 + "missing.md"
    _write(tmp_path / "README.md", f"[Bad]({long_target})\n")

    fake_stdout = _FakeTerminalStdout()
    monkeypatch.setattr("sys.stdout", fake_stdout)
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: os.terminal_size((width, 24)))

    config = Config(path=tmp_path, check_external=False, quiet=False, no_color=True)
    exit_code = asyncio.run(cli_run(config))

    assert exit_code == 1
    output = fake_stdout.getvalue()
    table_lines = [
        line for line in output.splitlines() if line.strip().startswith(("┏", "┃", "┡", "│", "└"))
    ]
    assert table_lines
    for line in table_lines:
        assert len(line) <= width
