"""pdf_pipeline.py — Page-by-page PDF conversion pipeline.

Splits a multi-page PDF into single-page PDFs, runs the configured backend
on each page independently, then merges the per-page Markdown back into a
single document. Single-page PDFs are short-circuited and converted whole.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf2markdown.converters import run_conversion

logger = logging.getLogger(__name__)


def count_pages(pdf_path: Path) -> int:
    """Return the number of pages in a PDF using PyMuPDF.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Page count.
    """
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return int(doc.page_count)


def split_pdf(pdf_path: Path, out_dir: Path) -> list[Path]:
    """Split a PDF into one single-page PDF per source page.

    Output files are named ``<stem>_page_<NNN>.pdf`` (1-indexed, 3-digit
    zero-padded). ``out_dir`` is created if missing.

    Args:
        pdf_path: Source multi-page PDF.
        out_dir: Directory where single-page PDFs are written.

    Returns:
        Ordered list of paths to the per-page PDFs.
    """
    import pymupdf

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    pages: list[Path] = []

    with pymupdf.open(pdf_path) as src:
        for i in range(src.page_count):
            target = out_dir / f"{stem}_page_{i + 1:03d}.pdf"
            with pymupdf.open() as single:
                single.insert_pdf(src, from_page=i, to_page=i)
                single.save(target)
            pages.append(target)

    return pages


def merge_markdown(pages: list[str], page_break: str = "\n\n---\n\n") -> str:
    """Join per-page Markdown strings with a horizontal-rule separator.

    Args:
        pages: Markdown strings in page order.
        page_break: Separator inserted between pages. Defaults to a Markdown
            horizontal rule surrounded by blank lines.

    Returns:
        Single merged Markdown document.
    """
    return page_break.join(p.rstrip() for p in pages).strip() + "\n"


@dataclass
class PageProgress:
    """One page's progress event emitted by :func:`convert_pdf_pages`.

    Attributes:
        page: 1-indexed page number that this event refers to.
        total: Total number of pages in the source PDF.
        status: ``"start"`` when a page begins, ``"done"`` when finished.
        markdown: Per-page Markdown — populated only on ``status == "done"``.
        elapsed: Wall-clock seconds for this page — populated only on ``done``.
    """

    page: int
    total: int
    status: str
    markdown: str | None = None
    elapsed: float | None = None


def convert_pdf_pages(
    pdf_path: Path,
    options: dict[str, Any],
    work_dir: Path,
    log: Callable[[str], None],
) -> Iterator[PageProgress]:
    """Convert a PDF page-by-page, yielding progress as each page finishes.

    For a single-page PDF the file is converted whole (no split). For
    multi-page PDFs the file is split into per-page PDFs in ``work_dir``,
    each is converted independently via :func:`run_conversion`, and the
    final iteration carries ``page == total`` with the merged Markdown.

    Args:
        pdf_path: Source PDF.
        options: Backend options forwarded to ``run_conversion``.
        work_dir: Scratch directory for per-page PDFs.
        log: Callable for human-readable status messages.

    Yields:
        :class:`PageProgress` events: a ``"start"`` then a ``"done"`` event
        per page, in order.
    """
    import time

    total = count_pages(pdf_path)
    log(f"PDF has {total} page(s)")

    if total <= 1:
        yield PageProgress(page=1, total=1, status="start")
        t0 = time.perf_counter()
        markdown = run_conversion(pdf_path, options, log)
        yield PageProgress(
            page=1,
            total=1,
            status="done",
            markdown=markdown,
            elapsed=time.perf_counter() - t0,
        )
        return

    log("Splitting PDF into per-page PDFs…")
    page_paths = split_pdf(pdf_path, work_dir)

    for i, page_path in enumerate(page_paths, start=1):
        yield PageProgress(page=i, total=total, status="start")
        log(f"[page {i}/{total}] converting…")
        t0 = time.perf_counter()
        markdown = run_conversion(page_path, options, log)
        elapsed = time.perf_counter() - t0
        log(f"[page {i}/{total}] done in {elapsed:.1f}s")
        yield PageProgress(
            page=i,
            total=total,
            status="done",
            markdown=markdown,
            elapsed=elapsed,
        )
