"""converters.py — All PDF-to-Markdown backend logic.

Each backend function accepts a ``pdf_path`` (Path), an ``options`` dict,
and a ``log`` callable for appending status messages to the UI, and returns
the converted Markdown as a string.
"""

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

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


def convert_docling(
    pdf_path: Path, options: dict[str, Any], log: Callable[[str], None]
) -> str:
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
    from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
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
    pipeline_options.ocr_options = EasyOcrOptions(lang=["en"], force_full_page_ocr=True)
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
    return cast(str, result.document.export_to_markdown())


# ---------------------------------------------------------------------------
# Backend: PyMuPDF4LLM
# ---------------------------------------------------------------------------


def convert_pymupdf4llm(
    pdf_path: Path, options: dict[str, Any], log: Callable[[str], None]
) -> str:
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
# batch_multiplier=0.5 keeps it well within 3 GB on a 6 GB card.
# ---------------------------------------------------------------------------


def convert_marker(
    pdf_path: Path, options: dict[str, Any], log: Callable[[str], None]
) -> str:
    """Convert a PDF to Markdown using the Marker backend.

    Marker uses ML models (~1.5 GB download on first run) and is well-suited
    for scanned or complex PDFs.

    Args:
        pdf_path: Path to the source PDF file.
        options: Supports ``device`` (``"gpu"`` or ``"cpu"``).
        log: Callable that appends a status string to the job log.

    Returns:
        Markdown string extracted by Marker's ``text_from_rendered``.

    Notes:
        Surya/Marker read ``TORCH_DEVICE`` and the ``*_BATCH_SIZE`` env vars
        once, at module-import time. They are set here *before* the marker
        imports so the first call wins. As a consequence, **switching device
        mid-process is not supported** — once marker has loaded on CUDA in
        this Python process, a later CPU call will still target CUDA.
        Restart the server to flip the device.
    """
    import gc
    import os

    use_gpu = options.get("device", "gpu") == "gpu"
    os.environ.setdefault("TORCH_DEVICE", "cuda" if use_gpu else "cpu")
    if use_gpu:
        # Surya's default DETECTOR_BATCH_SIZE on CUDA (36) blows past 6 GB on
        # dense image pages. Cap it conservatively for ≤6 GB cards.
        os.environ.setdefault("DETECTOR_BATCH_SIZE", "4")
        os.environ.setdefault("RECOGNITION_BATCH_SIZE", "16")

    from marker.config.parser import ConfigParser
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    log(f"Device: {os.environ['TORCH_DEVICE'].upper()}")
    log("Loading Marker models (first run downloads ~1.5 GB)…")
    artifact_dict = create_model_dict()

    log("Converting with Marker…")
    config = ConfigParser({"batch_multiplier": 0.5})
    converter = PdfConverter(
        artifact_dict=artifact_dict,
        config=config.generate_config_dict(),
    )
    try:
        rendered = converter(str(pdf_path))
        markdown, _, _ = text_from_rendered(rendered)
        return cast(str, markdown)
    finally:
        del converter, artifact_dict
        gc.collect()
        if use_gpu:
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
            except ImportError:
                pass


# ---------------------------------------------------------------------------
# Backend: LlamaParse (cloud API — requires LLAMA_CLOUD_API_KEY)
# ---------------------------------------------------------------------------


def convert_llamaparse(
    pdf_path: Path, options: dict[str, Any], log: Callable[[str], None]
) -> str:
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

    import os

    from llama_cloud import LlamaCloud

    api_key = options.get("llamaparse_api_key") or os.environ.get("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise ValueError(
            "LlamaParse requires an API key. Set LLAMA_CLOUD_API_KEY in your "
            "environment or .env file, or paste it in the UI."
        )

    log("Uploading to LlamaParse cloud API…")
    client = LlamaCloud(api_key=api_key)
    with Path.open(pdf_path, "rb") as filehandler:
        result = client.parsing.parse(
            upload_file=filehandler,
            tier="fast",
            version="latest",
            expand=["markdown_full"],
            verbose=False,
        )

    return result.markdown_full or ""


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

DOCUMENT_TYPE_PRESETS: dict[str, dict[str, Any]] = {
    "exercise_page": {
        "backend": "llamaparse",
        "ocr": True,
        "tables": True,
        "clean_whitespace": True,
    },
    "financial_report": {
        "backend": "pymupdf4llm",
        "ocr": False,
        "tables": True,
        "clean_whitespace": False,
    },
    "scanned_document": {
        "backend": "marker",
        "ocr": True,
        "tables": True,
        "clean_whitespace": True,
    },
    "general": {},
}

BACKENDS = {
    "docling": convert_docling,
    "pymupdf4llm": convert_pymupdf4llm,
    "marker": convert_marker,
    "llamaparse": convert_llamaparse,
}


def run_conversion(
    pdf_path: Path, options: dict[str, Any], log: Callable[[str], None]
) -> str:
    """Dispatch a PDF conversion to the requested backend and post-process the result.

    This is the single entry point called by the Gradio conversion handler. It
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
    doc_type = options.get("document_type", "general")
    preset = DOCUMENT_TYPE_PRESETS.get(doc_type, {})
    options = {**preset, **options}  # UI choices win over preset defaults

    backend = options.get("backend", "docling")
    fn = BACKENDS.get(backend)
    if fn is None:
        raise ValueError(
            f"Unknown backend '{backend}'." f"Valid options: {list(BACKENDS)}"
        )
    logger.debug("run_conversion: backend=%s, file=%s", backend, pdf_path.name)

    def _log(msg: str) -> None:
        logger.info("[%s] %s", pdf_path.name, msg)
        log(msg)

    _log(f"File: {pdf_path.name}")
    _log(f"Backend: {backend}")

    markdown = fn(pdf_path, options, _log)

    if options.get("clean_whitespace", True):
        markdown = _clean_whitespace(markdown)

    return markdown
