"""Unit tests for pdf2markdown.converters.

Covers:
  - _clean_whitespace: newline-collapsing edge cases.
  - run_conversion: backend dispatch, log forwarding, whitespace post-processing,
    and error handling for unknown backends.
  - convert_llamaparse: API-key injection from the options dict.
"""

from pathlib import Path
from typing import Literal
from unittest.mock import ANY, MagicMock, patch

import pytest

from pdf2markdown.converters import (
    _clean_whitespace,
    convert_llamaparse,
    run_conversion,
)


def _noop_log(msg: str) -> None:
    """No-op log callable; avoids repeating ``lambda msg: None`` in tests."""


# ---------------------------------------------------------------------------
# _clean_whitespace
# ---------------------------------------------------------------------------


def test_clean_whitespace_collapses_newlines():
    """Three or more consecutive newlines are collapsed to exactly two."""
    result = _clean_whitespace("line1\n\n\n\nline2")
    assert result == "line1\n\nline2"


def test_clean_whitespace_leaves_double_newline():
    """Two consecutive newlines are left untouched."""
    result = _clean_whitespace("line1\n\nline2")
    assert result == "line1\n\nline2"


def test_clean_whitespace_collapses_trailing_newlines():
    """Trailing runs of three or more newlines are collapsed to two."""
    assert _clean_whitespace("a\n\n\n") == "a\n\n"


def test_clean_whitespace_empty_string():
    """An empty string is returned unchanged."""
    assert _clean_whitespace("") == ""


def test_clean_whitespace_exactly_two_newlines():
    """Exactly two newlines between tokens are preserved as-is."""
    assert _clean_whitespace("a\n\nb") == "a\n\nb"


# ---------------------------------------------------------------------------
# run_conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["docling", "pymupdf4llm", "marker", "llamaparse"])
def test_run_conversion_dispatches_to_correct_backend(
    tmp_path: Path,
    backend: Literal["docling", "pymupdf4llm", "marker", "llamaparse"],
):
    """run_conversion calls the backend function registered under options["backend"].

    Only dispatch is tested here — not arguments, output, or post-processing.
    clean_whitespace=False prevents the whitespace step from running so it
    does not obscure whether the right backend was reached.
    """
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")
    mock_fn = MagicMock(return_value="markdown")

    with patch.dict("pdf2markdown.converters.BACKENDS", {backend: mock_fn}):
        run_conversion(
            pdf_path,
            {"backend": backend, "clean_whitespace": False},
            _noop_log,
        )

    mock_fn.assert_called_once()


def test_run_conversion_forwards_log_to_backend(tmp_path: Path):
    """Messages the backend emits via log() reach the original caller's callback.

    run_conversion wraps the caller's log in an internal _log function. This
    test confirms the wrapper forwards messages rather than swallowing them.
    A plain list (received.append) is used as the callback so the messages
    can be inspected after the call.
    """
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")
    received = []

    def fake_backend(path, opts, log):
        log("hello from backend")
        return "markdown"

    with patch.dict("pdf2markdown.converters.BACKENDS", {"docling": fake_backend}):
        run_conversion(pdf_path, {"backend": "docling"}, received.append)

    assert any("hello from backend" in msg for msg in received)


def test_run_conversion_unknown_backend_raises(tmp_path: Path):
    """A ValueError is raised when options["backend"] is not in BACKENDS.

    The error message must contain the unknown name so the caller can
    identify the mistake without reading source code.
    """
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")

    with pytest.raises(ValueError, match="nonexistent"):
        run_conversion(pdf_path, {"backend": "nonexistent"}, _noop_log)


def test_run_conversion_applies_clean_whitespace(tmp_path: Path):
    """When clean_whitespace is True, runs of 3+ newlines in backend
    output are collapsed.
    """
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")

    with patch.dict(
        "pdf2markdown.converters.BACKENDS",
        {"docling": lambda path, opts, log: "a\n\n\n\nb"},
    ):
        result = run_conversion(
            pdf_path, {"backend": "docling", "clean_whitespace": True}, _noop_log
        )

    assert result == "a\n\nb"


def test_run_conversion_skips_clean_whitespace(tmp_path: Path):
    """When clean_whitespace=False, backend output is returned verbatim."""
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")

    with patch.dict(
        "pdf2markdown.converters.BACKENDS",
        {"docling": lambda path, opts, log: "a\n\n\n\nb"},
    ):
        result = run_conversion(
            pdf_path, {"backend": "docling", "clean_whitespace": False}, _noop_log
        )

    assert result == "a\n\n\n\nb"


# ---------------------------------------------------------------------------
# convert_llamaparse
# ---------------------------------------------------------------------------


def test_convert_llamaparse_passes_api_key_from_options(tmp_path: Path):
    """API key supplied in options["llamaparse_api_key"] is forwarded to LlamaParse.

    The parser is instantiated with the exact key, result_type=ANY (controlled
    by the backend), and verbose=False.
    """
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")
    mock_result = MagicMock()
    mock_result.markdown_full = "# Hello"
    mock_client = MagicMock()
    mock_client.parsing.parse.return_value = mock_result

    with patch("llama_cloud.LlamaCloud", return_value=mock_client) as mock_cls:
        result = convert_llamaparse(
            pdf_path, {"llamaparse_api_key": "llx-testkey"}, _noop_log
        )

    mock_cls.assert_called_once_with(api_key="llx-testkey")
    mock_client.parsing.parse.assert_called_once_with(
        upload_file=ANY,
        tier="fast",
        version="latest",
        expand=["markdown_full"],
        verbose=False,
    )
    assert result == "# Hello"
