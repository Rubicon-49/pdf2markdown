from unittest.mock import patch

import pytest

from pdf2markdown.converters import _clean_whitespace, run_conversion


def test_clean_whitespace_collapses_newlines():
    result = _clean_whitespace("line1\n\n\n\nline2")
    assert result == "line1\n\nline2"


def test_clean_whitespace_leaves_double_newline():
    result = _clean_whitespace("line1\n\nline2")
    assert result == "line1\n\nline2"


def test_run_conversion_unknown_backend(tmp_path):
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")
    options = {"backend": "nonexistent"}

    with pytest.raises(ValueError, match="nonexistent"):
        run_conversion(pdf_path, options, lambda msg: None)


def test_run_conversion_applies_clean_whitespace(tmp_path):
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")
    options = {"backend": "docling", "clean_whitespace": True}

    with patch.dict(
        "pdf2markdown.converters.BACKENDS",
        {"docling": lambda path, opts, log: "a\n\n\n\nb"},
    ):
        result = run_conversion(pdf_path, options, lambda msg: None)

    assert result == "a\n\nb"


def test_run_conversion_skips_clean_whitespace(tmp_path):
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"")
    options = {"backend": "docling", "clean_whitespace": False}

    with patch.dict(
        "pdf2markdown.converters.BACKENDS",
        {"docling": lambda path, opts, log: "a\n\n\n\nb"},
    ):
        result = run_conversion(pdf_path, options, lambda msg: None)

    assert result == "a\n\n\n\nb"


def test_clean_whitespace_empty_string():
    assert _clean_whitespace("") == ""


def test_clean_whitespace_exactly_two_newlines():
    assert _clean_whitespace("a\n\nb") == "a\n\nb"
