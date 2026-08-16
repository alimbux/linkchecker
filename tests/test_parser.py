from __future__ import annotations

from mdcheck.models import LinkType
from mdcheck.parser import extract_links


def _by_line(links, line):
    return [link for link in links if link.line == line]


def test_inline_link():
    links = extract_links("f.md", "[Docs](docs/guide.md)\n")
    assert len(links) == 1
    link = links[0]
    assert link.link_text == "Docs"
    assert link.original_target == "docs/guide.md"
    assert link.normalized_target == "docs/guide.md"
    assert link.link_type == LinkType.LOCAL_FILE
    assert link.line == 1


def test_reference_link():
    text = "[Documentation][docs]\n\n[docs]: ./guide.md\n"
    links = extract_links("f.md", text)
    assert len(links) == 1
    assert links[0].original_target == "./guide.md"
    assert links[0].normalized_target == "guide.md"
    assert links[0].line == 1


def test_reference_link_shortcut():
    text = "[docs]\n\n[docs]: ./guide.md\n"
    links = extract_links("f.md", text)
    assert len(links) == 1
    assert links[0].normalized_target == "guide.md"


def test_autolink():
    links = extract_links("f.md", "See <https://example.com> for details.\n")
    assert len(links) == 1
    assert links[0].original_target == "https://example.com"
    assert links[0].link_type == LinkType.HTTPS


def test_autolink_file_uri():
    links = extract_links("f.md", "<file:///tmp/example.txt>\n")
    assert len(links) == 1
    assert links[0].link_type == LinkType.FILE_URI


def test_html_href():
    links = extract_links("f.md", '<a href="https://example.com">Example</a>\n')
    assert len(links) == 1
    assert links[0].original_target == "https://example.com"
    assert links[0].link_text == "Example"
    assert links[0].link_type == LinkType.HTTPS


def test_multiple_links_on_one_line():
    links = extract_links("f.md", "[A](a.md) and [B](b.md)\n")
    assert [link.original_target for link in links] == ["a.md", "b.md"]
    assert all(link.line == 1 for link in links)


def test_multiline_markdown_link():
    text = "[Some\ntext](target.md)\n"
    links = extract_links("f.md", text)
    assert len(links) == 1
    assert links[0].original_target == "target.md"
    assert links[0].line == 1
    assert links[0].link_text == "Some\ntext"


def test_url_containing_parentheses():
    text = "[Wiki](https://en.wikipedia.org/wiki/Foo_(bar))\n"
    links = extract_links("f.md", text)
    assert len(links) == 1
    assert links[0].original_target == "https://en.wikipedia.org/wiki/Foo_(bar)"


def test_percent_encoded_url():
    text = "[File](../My%20Documents/report.pdf#page=2)\n"
    links = extract_links("f.md", text)
    assert len(links) == 1
    assert links[0].original_target == "../My%20Documents/report.pdf#page=2"
    assert links[0].normalized_target == "../My Documents/report.pdf"


def test_image_is_not_checked():
    links = extract_links("f.md", "![alt](image.png)\n")
    assert links == []


def test_image_alongside_link_is_not_confused():
    text = "![alt](image.png) and [text](page.md)\n"
    links = extract_links("f.md", text)
    assert [link.original_target for link in links] == ["page.md"]


def test_link_in_inline_code_not_checked():
    text = "Use `[fake](link.md)` here.\n"
    links = extract_links("f.md", text)
    assert links == []


def test_link_in_fenced_code_block_not_checked():
    text = "```\n[fake](link.md)\n```\n[real](real.md)\n"
    links = extract_links("f.md", text)
    assert [link.original_target for link in links] == ["real.md"]


def test_link_in_tilde_fenced_code_block_not_checked():
    text = "~~~\n[fake](link.md)\n~~~\n"
    links = extract_links("f.md", text)
    assert links == []


def test_link_in_html_comment_not_checked():
    text = "<!-- [fake](comment.md) -->\n[real](real.md)\n"
    links = extract_links("f.md", text)
    assert [link.original_target for link in links] == ["real.md"]


def test_template_link_dollar_brace():
    links = extract_links("f.md", "[Docs](${BASE_URL}/docs)\n")
    assert len(links) == 1
    assert links[0].link_type == LinkType.TEMPLATE


def test_template_link_double_brace():
    links = extract_links("f.md", "[Docs]({{ url }})\n")
    assert len(links) == 1
    assert links[0].link_type == LinkType.TEMPLATE


def test_empty_link_not_extracted():
    links = extract_links("f.md", "[Empty]()\n")
    assert links == []


def test_incomplete_link_not_extracted():
    links = extract_links("f.md", "[Incomplete](\n")
    assert links == []


def test_mailto_tel_javascript_data_are_unsupported():
    text = (
        "[Mail](mailto:test@example.com)\n"
        "[Call](tel:+1234567890)\n"
        "[JS](javascript:alert(1))\n"
        "[Data](data:text/plain;base64,SGVsbG8=)\n"
    )
    links = extract_links("f.md", text)
    assert len(links) == 4
    assert all(link.link_type == LinkType.UNSUPPORTED for link in links)


def test_local_anchor_classification():
    links = extract_links("f.md", "[Section](#installation)\n")
    assert links[0].link_type == LinkType.LOCAL_ANCHOR
    assert links[0].normalized_target == ""


def test_file_with_anchor_classification():
    links = extract_links("f.md", "[Other section](guide.md#configuration)\n")
    assert links[0].link_type == LinkType.LOCAL_FILE
    assert links[0].normalized_target == "guide.md"


def test_absolute_local_path():
    links = extract_links("f.md", "[Abs](/path/file.md)\n")
    assert links[0].link_type == LinkType.LOCAL_FILE
    assert links[0].normalized_target == "/path/file.md"


def test_relative_dotdot_path():
    links = extract_links("f.md", "[Rel](../guide.md)\n")
    assert links[0].link_type == LinkType.LOCAL_FILE
    assert links[0].normalized_target == "../guide.md"


def test_windows_drive_path_classified_local():
    links = extract_links("f.md", r"[Win](C:\docs\guide.md)" + "\n")
    assert links[0].link_type == LinkType.LOCAL_FILE


def test_http_and_https_classification():
    text = "[A](http://example.com)\n[B](https://example.com)\n"
    links = extract_links("f.md", text)
    assert links[0].link_type == LinkType.HTTP
    assert links[1].link_type == LinkType.HTTPS


def test_line_numbers_are_correct_for_multiple_lines():
    text = "line 1\n[A](a.md)\nline 3\n[B](b.md)\n"
    links = extract_links("f.md", text)
    assert [link.line for link in links] == [2, 4]


def test_unknown_scheme_is_invalid():
    links = extract_links("f.md", "[FTP](ftp://example.com/file)\n")
    assert links[0].link_type == LinkType.INVALID
