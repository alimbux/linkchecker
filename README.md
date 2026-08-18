# mdcheck

A cross-platform CLI utility that recursively scans a directory for Markdown
files, extracts every link, and checks:

- whether local files and directories exist;
- whether `file://` URIs resolve correctly;
- whether external HTTP/HTTPS resources are reachable;
- whether local Markdown anchors (`#heading`) exist.

It prints a readable, colored report (or JSON for CI) and returns exit codes
suitable for CI pipelines.

## Installation

Requires Python 3.11+.

```bash
pip install -e .
```

This installs the `mdcheck` command:

```bash
mdcheck --help
```

## Usage

```bash
mdcheck [PATH] [OPTIONS]
```

`PATH` may be a directory to scan recursively, a single Markdown file, or
omitted to scan the current directory.

### Examples

```bash
mdcheck .
mdcheck docs/
mdcheck README.md
mdcheck . --timeout 10 --workers 8
mdcheck . --no-external
mdcheck . --format json --output report.json
```

### Options

```text
--timeout FLOAT          Timeout for one HTTP request; default: 5 seconds
--workers INTEGER        Maximum concurrent HTTP checks; default: 10
--retries INTEGER        Retry count for transient failures; default: 1
--no-external            Do not check HTTP/HTTPS links
--no-local               Do not check local links
--check-anchors          Check Markdown anchors; enabled by default
--no-check-anchors       Do not check anchors
--include GLOB           Additional include pattern; may be repeated
--exclude GLOB           Exclude pattern; may be repeated
--ignore-url PATTERN     Ignore URL by glob or regex; may be repeated
--user-agent STRING      HTTP User-Agent value
--format FORMAT          Report format: console or json; default: console
--output PATH            Write the report to a file
--no-color               Disable ANSI colors
--quiet                  Show only errors and the summary
--verbose                Show every checked link
--version                Show the program version
--help                   Show help
```

Default exclusions (always applied, in addition to any `--exclude` patterns):

```text
.git/**
node_modules/**
.venv/**
venv/**
dist/**
build/**
__pycache__/**
```

## What gets checked

- Inline links: `[text](target)`
- Reference links: `[text][ref]` with a matching `[ref]: target` definition
- Autolinks: `<https://example.com>`, `<file:///tmp/example.txt>`
- URLs inside HTML `<a href="...">` tags

Images (`![alt](image.png)`), links inside fenced/inline code, links inside
HTML comments, empty links, and syntactically incomplete links are never
extracted. `mailto:`, `tel:`, `javascript:`, and `data:` links are extracted
but reported as `SKIPPED` (unsupported scheme). Template placeholders such as
`${BASE_URL}/docs` or `{{ url }}` are reported as `SKIPPED` rather than
broken.

## Result statuses

| Status    | Meaning                                                          |
|-----------|-------------------------------------------------------------------|
| `OK`      | The link resolved successfully.                                   |
| `WARNING` | HTTP `401`/`403`, or `429` after retries were exhausted.           |
| `BROKEN`  | Local path / anchor missing, or an HTTP `4xx`/`5xx` failure.       |
| `TIMEOUT` | The request did not complete within `--timeout`.                  |
| `ERROR`   | DNS failure, TLS failure, connection error, or too many redirects.|
| `INVALID` | A malformed URL or unsupported/unknown link target.                |
| `SKIPPED` | Disabled by a flag, ignored by `--ignore-url`, unsupported scheme, or a template placeholder. |

## Exit codes

```text
0 — no problematic links were found
1 — at least one BROKEN, TIMEOUT, ERROR, or INVALID result was found
2 — startup or configuration error (bad path, bad option, unwritable --output)
130 — interrupted with Ctrl+C
```

`WARNING` and `SKIPPED` results alone never produce exit code `1`.

## Progress indicator

While links are being checked, mdcheck shows a live progress bar (spinner,
bar, percentage, elapsed time) on stderr — it never touches stdout, so it
never corrupts `--format json` output or a report written with `--output`.
It's automatically disabled when `--quiet` is used or when stderr isn't a
terminal (e.g. redirected to a file or a CI log).

## Problems table sizing

The console problems table fits itself to the real terminal width instead
of using a fixed size. `File`, `Details`, and `Target` share the available
width proportionally — `Target` always gets the largest share, since links
and paths are usually the longest field — and none of them are truncated
with an ellipsis; long values wrap onto extra lines instead.

## JSON report

With `--format json`, stdout contains **only** valid JSON; progress and
diagnostics go to stderr. Shape:

```json
{
  "summary": {
    "files_scanned": 24,
    "links_found": 138,
    "unique_targets_checked": 121,
    "ok": 127,
    "warnings": 2,
    "broken": 3,
    "timeouts": 1,
    "errors": 1,
    "invalid": 0,
    "skipped": 4,
    "duration_ms": 2840
  },
  "results": [
    {
      "source_file": "docs/start.md",
      "line": 18,
      "link_text": "Old documentation",
      "original_target": "https://example.com/old",
      "normalized_target": "https://example.com/old",
      "link_type": "HTTPS",
      "status": "BROKEN",
      "http_status": 404,
      "message": "Not Found",
      "final_url": "https://example.com/old",
      "elapsed_ms": 143
    }
  ]
}
```

## HTTP checking behavior

- Sends `HEAD` first; falls back to a streamed `GET` (reading at most 64 KiB)
  whenever `HEAD` doesn't return a successful (`2xx`/`3xx`) status — not just
  `405`/`501`. Some servers (e.g. Figma) answer `HEAD` with an unrelated error
  status while `GET` succeeds.
- Follows up to 5 redirects; a redirect loop or exceeded limit is `ERROR`.
- Retries only transient failures (timeouts, connection errors, DNS hiccups,
  `429`, `502`/`503`/`504`) with a short exponential backoff, honoring
  `Retry-After` up to an internal maximum delay. `400`, `401`, `403`, `404`,
  and other permanent failures are never retried.
- Deduplicates identical normalized URLs — each unique URL is requested once,
  and the result is applied to every occurrence in the report.
- Sends `User-Agent: mdcheck/<version> (+https://example.invalid/mdcheck)`
  (override with `--user-agent`) and `Accept: text/html,application/xhtml+xml,*/*`.
  Never sends cookies or authentication data.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

All HTTP tests use `httpx.MockTransport` — the test suite makes no real
network requests.

## Known limitations

- Image links (`![alt](src)`) are never checked (out of scope for v1).
- No JavaScript execution or HTML rendering — link discovery is
  regex/text-based, not a full Markdown/HTML parser, so unusual or deeply
  nested inline constructs may not be extracted perfectly.
- `file://host/path` URIs pointing at a *remote* host are not fetched; they
  are reported as `SKIPPED`.
- Windows drive-letter paths (`C:\docs\guide.md`) are classified and
  normalized correctly on any OS, but existence checks against them only
  make sense when actually running on Windows.
- Anchor slug generation follows common GitHub-style rules (lowercase,
  punctuation stripped, spaces to hyphens, duplicate suffixes) but does not
  claim byte-for-byte parity with every Markdown renderer's heading-ID
  algorithm.
- `--retries` and backoff apply only to HTTP/HTTPS checks; local file and
  anchor checks are synchronous filesystem operations with no retry concept.
