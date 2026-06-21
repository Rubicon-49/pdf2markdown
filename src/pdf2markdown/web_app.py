"""web_app.py — FastAPI + HTMX UI for pdf2markdown.

Endpoints:

* ``GET  /``                — main page (Jinja template).
* ``POST /convert``         — accept upload + options, start a background
                              job, return ``job_id`` as plain text.
* ``GET  /events/{job_id}`` — Server-Sent Events stream of per-page progress.
* ``GET  /download/{job_id}`` — final merged Markdown as a file download.
* ``GET  /preview/{job_id}``  — first 3 000 chars of the merged Markdown.

The HTML is rendered server-side; the client uses HTMX's SSE extension to
swap progress fragments into the page as each page completes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pdf2markdown.log_setup import setup_logging
from pdf2markdown.pdf_pipeline import (
    PageProgress,
    convert_pdf_pages,
    merge_markdown,
)
from pdf2markdown.utils import find_project_root

PROJECT_ROOT = find_project_root()
setup_logging(PROJECT_ROOT)
logger = logging.getLogger(__name__)

load_dotenv(PROJECT_ROOT / ".env")

PACKAGE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

UPLOADS = PROJECT_ROOT / "uploads"
OUTPUTS = PROJECT_ROOT / "outputs"
UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

_BACKEND_INFO: dict[str, str] = {
    "docling": (
        "High-quality layout & table extraction. GPU or CPU. "
        "First run downloads ~600 MB of models."
    ),
    "pymupdf4llm": (
        "CPU-only, very fast. Best for clean text-based PDFs without "
        "complex layouts or tables."
    ),
    "marker": (
        "ML-based OCR for scanned or photographed pages. "
        "GPU recommended. First run downloads ~1.5 GB of models."
    ),
    "llamaparse": (
        "Cloud API — no local models required. Needs a `LLAMA_CLOUD_API_KEY`."
    ),
}

BACKEND_LABELS = [
    ("docling", "Docling"),
    ("pymupdf4llm", "PyMuPDF"),
    ("marker", "Marker"),
    ("llamaparse", "LlamaParse"),
]

# ---------------------------------------------------------------------------
# Job store
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """In-memory record of one conversion job.

    Attributes:
        id: Random 16-char hex token used as the job's URL key.
        filename: Original uploaded filename (for display).
        queue: AsyncIterator-friendly queue of SSE event dicts.
        markdown: Final merged Markdown — populated when the job finishes.
        output_path: On-disk path of the final ``.md`` — populated on success.
        error: Error message if the job failed.
        done: ``True`` once the worker has emitted its terminal event.
    """

    id: str
    filename: str
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    markdown: str | None = None
    output_path: Path | None = None
    error: str | None = None
    done: bool = False


_JOBS: dict[str, Job] = {}


def _new_job(filename: str) -> Job:
    job = Job(id=secrets.token_hex(8), filename=filename)
    _JOBS[job.id] = job
    return job


def _get_job(job_id: str) -> Job:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _run_job_sync(job: Job, pdf_path: Path, options: dict[str, Any]) -> None:
    """Run one conversion job synchronously and push SSE events to ``job.queue``.

    Designed to be called via ``asyncio.to_thread`` from the request handler
    so it does not block the event loop.
    """

    def push(event: dict[str, Any]) -> None:
        job.queue.put_nowait(event)

    def log(msg: str) -> None:
        push({"event": "log", "data": {"message": msg}})

    work_dir = UPLOADS / f"job_{job.id}"
    work_dir.mkdir(exist_ok=True)
    pages_markdown: list[str] = []

    try:
        t0 = time.perf_counter()
        for progress in convert_pdf_pages(pdf_path, options, work_dir, log):
            _emit_progress(push, progress)
            if progress.status == "done" and progress.markdown is not None:
                pages_markdown.append(progress.markdown)

        merged = merge_markdown(pages_markdown)
        output_path = OUTPUTS / f"{pdf_path.stem}.md"
        output_path.write_text(merged, encoding="utf-8")

        elapsed = time.perf_counter() - t0
        job.markdown = merged
        job.output_path = output_path

        push(
            {
                "event": "done",
                "data": {
                    "words": len(merged.split()),
                    "lines": merged.count("\n"),
                    "elapsed": round(elapsed, 1),
                    "pages": len(pages_markdown),
                    "job_id": job.id,
                },
            }
        )
        logger.info(
            "Job %s done — pages: %d, words: %d, elapsed: %.1fs",
            job.id,
            len(pages_markdown),
            len(merged.split()),
            elapsed,
        )
    except Exception as exc:
        logger.exception("Job %s failed", job.id)
        job.error = str(exc)
        push({"event": "error", "data": {"message": str(exc)}})
    finally:
        job.done = True
        push({"event": "close", "data": {}})


def _emit_progress(push: Any, progress: PageProgress) -> None:
    """Translate a :class:`PageProgress` into an SSE event for the client."""
    payload: dict[str, Any] = {
        "page": progress.page,
        "total": progress.total,
        "status": progress.status,
    }
    if progress.elapsed is not None:
        payload["elapsed"] = round(progress.elapsed, 1)
    push({"event": "page", "data": payload})


# ---------------------------------------------------------------------------
# App + routes
# ---------------------------------------------------------------------------

app = FastAPI(title="pdf → markdown")
app.mount(
    "/static",
    StaticFiles(directory=str(PACKAGE_DIR / "static")),
    name="static",
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main page."""
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "backends": BACKEND_LABELS,
            "backend_info": _BACKEND_INFO,
        },
    )


@app.post("/convert", response_class=PlainTextResponse)
async def convert(
    pdf: UploadFile,
    backend: str = Form("docling"),
    ocr: str | None = Form(None),
    tables: str | None = Form(None),
    clean_whitespace: str | None = Form(None),
    device: str | None = Form(None),
    api_key: str = Form(""),
) -> PlainTextResponse:
    """Accept an uploaded PDF, queue a background job, return the job id.

    The HTML form checkboxes arrive as ``"on"`` or are absent; coerce to bool.
    """
    if pdf.filename is None or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file")

    job = _new_job(pdf.filename)

    saved = UPLOADS / f"job_{job.id}_{Path(pdf.filename).name}"
    saved.write_bytes(await pdf.read())

    options: dict[str, Any] = {
        "backend": backend,
        "ocr": ocr is not None,
        "tables": tables is not None,
        "clean_whitespace": clean_whitespace is not None,
        "device": "gpu" if device is not None else "cpu",
        "llamaparse_api_key": api_key.strip() or None,
    }
    logger.info("Job %s queued — file: %s, backend: %s", job.id, pdf.filename, backend)

    asyncio.create_task(asyncio.to_thread(_run_job_sync, job, saved, options))
    return PlainTextResponse(job.id)


@app.get("/events/{job_id}")
async def events(job_id: str) -> StreamingResponse:
    """Stream SSE progress events for a job until it emits ``close``."""
    job = _get_job(job_id)

    async def stream() -> AsyncIterator[bytes]:
        while True:
            event = await job.queue.get()
            name = event["event"]
            data = json.dumps(event["data"])
            yield f"event: {name}\ndata: {data}\n\n".encode()
            if name == "close":
                break

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/preview/{job_id}", response_class=HTMLResponse)
async def preview(request: Request, job_id: str) -> HTMLResponse:
    """Return the result-pane HTML fragment for a finished job (HTMX swap)."""
    job = _get_job(job_id)
    if not job.done or job.markdown is None:
        raise HTTPException(status_code=409, detail="Job not finished")
    return TEMPLATES.TemplateResponse(
        request,
        "_result.html",
        {
            "job_id": job.id,
            "filename": job.filename,
            "preview": job.markdown[:3000],
            "words": len(job.markdown.split()),
            "lines": job.markdown.count("\n"),
        },
    )


@app.get("/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    """Serve the final merged Markdown file."""
    job = _get_job(job_id)
    if job.output_path is None or not job.output_path.exists():
        raise HTTPException(status_code=404, detail="Output not available")
    return FileResponse(
        job.output_path,
        media_type="text/markdown",
        filename=job.output_path.name,
    )


@app.get("/backend-info/{backend}", response_class=HTMLResponse)
async def backend_info(request: Request, backend: str) -> HTMLResponse:
    """Return the small description/options panel for a chosen backend."""
    if backend not in _BACKEND_INFO:
        raise HTTPException(status_code=404, detail="Unknown backend")
    return TEMPLATES.TemplateResponse(
        request,
        "_backend_info.html",
        {
            "backend": backend,
            "info": _BACKEND_INFO[backend],
        },
    )
