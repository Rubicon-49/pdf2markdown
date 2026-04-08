"""
converters.py — All PDF-to-Markdown backend logic1
.

Each backend function receives:
    pdf_path : pathlib.Path  — path to the source PDF
    options  : dict          — backend-specific options
    log      : callable(str) — append a status message for the UI

Returns:
    str — the converted Markdown text
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_whitespace(text: str) -> str:
    """Collapse 3+ consecutive newlines down to 2.

    Args:
        text: Raw Markdown string produced by a backend.

    Returns:
        The same string with runs of 3 or more newlines replaced by 2.
    """
    return re.sub(r"\n{3,}", "\n\n", text)


# ---------------------------------------------------------------------------
# Backend: Docling
# ---------------------------------------------------------------------------


def convert_docling(pdf_path: Path, options: dict, log) -> str:
    """Convert a PDF to Markdown using the Docling backend.

    Docling provides high-quality layout and table extraction and runs on
    CPU or GPU automatically. The first run downloads ~600 MB of models.

    Args:
        pdf_path: Path to the source PDF file.
        options: Supports ``ocr`` (bool) and ``tables`` (bool).
        log: Callable that appends a status string to the job log.

    Returns:
        Markdown string exported from the Docling document model.
    """
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    device = (
        AcceleratorDevice.CUDA
        if options.get("device", "gpu") == "gpu"
        else AcceleratorDevice.CPU
    )
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=4, device=device
    )
    pipeline_options.do_ocr = options.get("ocr", False)
    pipeline_options.do_table_structure = options.get("tables", True)

    log(
        f"Device: {'GPU' if device == AcceleratorDevice.CUDA else 'CPU'} | "
        f"OCR: {'on' if pipeline_options.do_ocr else 'off'} | "
        f"Tables: {'on' if pipeline_options.do_table_structure else 'off'}"
    )
    log("Converting with Docling…")

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()


# ---------------------------------------------------------------------------
# Backend: PyMuPDF4LLM
# ---------------------------------------------------------------------------


def convert_pymupdf4llm(pdf_path: Path, options: dict, log) -> str:
    """Convert a PDF to Markdown using PyMuPDF4LLM.

    CPU-only and very fast. Best suited for clean, text-based PDFs without
    complex layouts or tables.

    Args:
        pdf_path: Path to the source PDF file.
        options: Unused by this backend; present for interface consistency.
        log: Callable that appends a status string to the job log.

    Returns:
        Markdown string produced by ``pymupdf4llm.to_markdown``.
    """
    import pymupdf4llm

    log("Converting with PyMuPDF4LLM…")
    return cast(str, pymupdf4llm.to_markdown(str(pdf_path)))


# ---------------------------------------------------------------------------
# Backend: Marker
# Marker's default batch sizes use ~3 GB VRAM.
# batch_multiplier=1 keeps it safe on a 6 GB card.
# ---------------------------------------------------------------------------


def convert_marker(pdf_path: Path, options: dict, log) -> str:
    """Convert a PDF to Markdown using the Marker backend.

    Marker uses ML models (~1.5 GB download on first run) and is well-suited
    for scanned or complex PDFs. ``batch_multiplier=1`` keeps VRAM usage
    within 3 GB, safe for a 6 GB card.

    Args:
        pdf_path: Path to the source PDF file.
        options: Unused by this backend; present for interface consistency.
        log: Callable that appends a status string to the job log.

    Returns:
        Markdown string extracted by Marker's ``text_from_rendered``.
    """
    import os

    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    os.environ["TORCH_DEVICE"] = (
        "cuda" if options.get("device", "gpu") == "gpu" else "cpu"
    )
    log(f"Device: {os.environ['TORCH_DEVICE'].upper()}")

    log("Loading Marker models (first run downloads ~1.5 GB)…")
    artifact_dict = create_model_dict()

    log("Converting with Marker…")
    converter = PdfConverter(artifact_dict=artifact_dict)
    rendered = converter(str(pdf_path))
    markdown, _, _ = text_from_rendered(rendered)
    return markdown


# ---------------------------------------------------------------------------
# Backend: LlamaParse (cloud API — requires LLAMA_CLOUD_API_KEY)
# ---------------------------------------------------------------------------


def convert_llamaparse(pdf_path: Path, options: dict, log) -> str:
    """Convert a PDF to Markdown via the LlamaParse cloud API.

    Requires a ``LLAMA_CLOUD_API_KEY`` — either passed in ``options`` or set
    as an environment variable. No local models are downloaded; the file is
    uploaded to LlamaIndex's cloud service.

    Args:
        pdf_path: Path to the source PDF file.
        options: Supports ``llamaparse_api_key`` (str | None). Falls back to
            the ``LLAMA_CLOUD_API_KEY`` environment variable.
        log: Callable that appends a status string to the job log.

    Returns:
        Markdown string assembled from all pages returned by the API.

    Raises:
        ValueError: If no API key is found in ``options`` or the environment.
    """

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    import os

    from llama_parse import LlamaParse
    from llama_parse.utils import ResultType

    api_key = options.get("llamaparse_api_key") or os.environ.get("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise ValueError(
            "LlamaParse requires an API key. Set LLAMA_CLOUD_API_KEY in your "
            "environment or .env file, or paste it in the UI."
        )

    log("Uploading to LlamaParse cloud API…")
    parser = LlamaParse(
        api_key=api_key,
        result_type=ResultType.MD,
        verbose=False,
    )

    documents = parser.load_data(str(pdf_path))
    log(f"LlamaParse returned {len(documents)} page(s)")
    return "\n\n".join(doc.text for doc in documents)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

BACKENDS = {
    "docling": convert_docling,
    "pymupdf4llm": convert_pymupdf4llm,
    "marker": convert_marker,
    "llamaparse": convert_llamaparse,
}


def run_conversion(pdf_path: Path, options: dict, log) -> str:
    """Dispatch a PDF conversion to the requested backend and post-process the result.

    This is the single entry point called by the Flask worker thread. It
    selects the backend function from ``BACKENDS``, runs it, and optionally
    applies whitespace normalisation.

    Args:
        pdf_path: Path to the source PDF file.
        options: Dict with at minimum a ``backend`` key. Additional keys are
            forwarded to the backend (see individual ``convert_*`` functions).
            ``clean_whitespace`` (bool, default ``True``) controls
            post-processing.
        log: Callable that appends a status string to the job log.

    Returns:
        Final Markdown string ready to be written to disk.

    Raises:
        ValueError: If ``options["backend"]`` is not a key in ``BACKENDS``.
    """
    backend = options.get("backend", "docling")
    fn = BACKENDS.get(backend)
    if fn is None:
        raise ValueError(
            f"Unknown backend '{backend}'." f"Valid options: {list(BACKENDS)}"
        )
    logger.debug("run_conversion: backend=%s, file=%s", backend, pdf_path.name)

    log(f"File: {pdf_path.name}")
    log(f"Backend: {backend}")

    markdown = fn(pdf_path, options, log)

    if options.get("clean_whitespace", True):
        markdown = _clean_whitespace(markdown)

    return markdown
