"""Unit tests for pdf2markdown.pdf_pipeline.

Covers:
  - merge_markdown: joiner, trimming, empty input.
  - count_pages / split_pdf: round-trip through a real PyMuPDF doc.
  - convert_pdf_pages: single-page short-circuit and multi-page event order.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from pdf2markdown.pdf_pipeline import (
    convert_pdf_pages,
    count_pages,
    merge_markdown,
    split_pdf,
)

# ---------------------------------------------------------------------------
# merge_markdown
# ---------------------------------------------------------------------------


def test_merge_markdown_joins_with_horizontal_rule():
    merged = merge_markdown(["# A", "# B", "# C"])
    assert merged == "# A\n\n---\n\n# B\n\n---\n\n# C\n"


def test_merge_markdown_strips_trailing_whitespace_per_page():
    merged = merge_markdown(["a\n\n\n", "b\n"])
    assert merged == "a\n\n---\n\nb\n"


def test_merge_markdown_single_page_no_separator():
    assert merge_markdown(["only"]) == "only\n"


def test_merge_markdown_empty_list():
    assert merge_markdown([]) == "\n"


# ---------------------------------------------------------------------------
# count_pages / split_pdf — use a real two-page PyMuPDF document
# ---------------------------------------------------------------------------


@pytest.fixture
def two_page_pdf(tmp_path: Path) -> Path:
    """Build a minimal 2-page PDF on disk using PyMuPDF."""
    import pymupdf

    target = tmp_path / "two_pages.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.new_page()
        doc.save(target)
    return target


def test_count_pages_returns_actual_page_count(two_page_pdf: Path):
    assert count_pages(two_page_pdf) == 2


def test_split_pdf_produces_one_pdf_per_page(two_page_pdf: Path, tmp_path: Path):
    out_dir = tmp_path / "split"
    pages = split_pdf(two_page_pdf, out_dir)

    assert len(pages) == 2
    assert pages[0].name == "two_pages_page_001.pdf"
    assert pages[1].name == "two_pages_page_002.pdf"
    assert all(count_pages(p) == 1 for p in pages)


# ---------------------------------------------------------------------------
# convert_pdf_pages
# ---------------------------------------------------------------------------


def _noop_log(_: str) -> None:
    """Discard log messages."""


def test_convert_pdf_pages_single_page_short_circuits(tmp_path: Path):
    """A 1-page PDF must NOT be split — run_conversion is called once."""
    import pymupdf

    pdf = tmp_path / "single.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(pdf)

    with patch(
        "pdf2markdown.pdf_pipeline.run_conversion", return_value="# Single"
    ) as mock_run:
        events = list(convert_pdf_pages(pdf, {"backend": "x"}, tmp_path, _noop_log))

    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == pdf  # NOT a split page
    assert [e.status for e in events] == ["start", "done"]
    assert events[-1].markdown == "# Single"
    assert events[-1].page == 1 and events[-1].total == 1


def test_convert_pdf_pages_multi_page_yields_start_done_per_page(
    two_page_pdf: Path, tmp_path: Path
):
    """Two-page PDF: events arrive as start/done pairs in page order."""

    def fake_run(path: Path, opts: dict, log) -> str:
        return f"## {path.stem}"

    with patch("pdf2markdown.pdf_pipeline.run_conversion", side_effect=fake_run):
        events = list(
            convert_pdf_pages(two_page_pdf, {"backend": "x"}, tmp_path, _noop_log)
        )

    assert [(e.page, e.status) for e in events] == [
        (1, "start"),
        (1, "done"),
        (2, "start"),
        (2, "done"),
    ]
    done_events = [e for e in events if e.status == "done"]
    assert done_events[0].markdown == "## two_pages_page_001"
    assert done_events[1].markdown == "## two_pages_page_002"
    assert all(e.elapsed is not None for e in done_events)


def test_convert_pdf_pages_forwards_options(two_page_pdf: Path, tmp_path: Path):
    """Options dict is passed through to run_conversion for each page."""
    seen_opts = []

    def fake_run(path: Path, opts: dict, log) -> str:
        seen_opts.append(opts)
        return ""

    with patch("pdf2markdown.pdf_pipeline.run_conversion", side_effect=fake_run):
        list(
            convert_pdf_pages(
                two_page_pdf,
                {"backend": "docling", "ocr": True},
                tmp_path,
                _noop_log,
            )
        )

    assert len(seen_opts) == 2
    assert all(o == {"backend": "docling", "ocr": True} for o in seen_opts)
