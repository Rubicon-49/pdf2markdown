"""
app.py — Flask web server. Contains only routing and job management.
All PDF conversion logic lives in converters.py.
"""

import logging
import platform
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import torch
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from pdf2markdown.converters import run_conversion
from pdf2markdown.job_store import (
    append_log,
    create_job,
    get_job,
    init_db,
    purge_old_jobs,
    update_job,
)
from pdf2markdown.job_store import (
    list_jobs as db_list_jobs,
)
from pdf2markdown.log_setup import setup_logging
from pdf2markdown.utils import find_project_root

PROJECT_ROOT = find_project_root()
setup_logging(PROJECT_ROOT)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))

UPLOAD_FOLDER = PROJECT_ROOT / "uploads"
OUTPUT_FOLDER = PROJECT_ROOT / "outputs"
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

DB_PATH = PROJECT_ROOT / "jobs.db"
init_db(DB_PATH)
purge_old_jobs(DB_PATH)

# Single-worker executor prevents concurrent GPU-heavy jobs from running in parallel
_executor = ThreadPoolExecutor(max_workers=1)

# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


def _worker(job_id: str, pdf_path: Path, options: dict) -> None:
    """Run a conversion job in a background thread and update the job store.

    Appends human-readable status messages to job store and
    mirrors them to the Python logger. On success the job entry is updated
    with ``status="done"``, ``output_file``, ``preview``, and ``stats``.
    On failure ``status="error"`` and ``error`` are set instead.

    Args:
        job_id: Short unique identifier for the job (8-char UUID prefix).
        pdf_path: Absolute path to the uploaded PDF file.
        options: Conversion options forwarded to ``run_conversion``
            (backend name, ocr, tables, clean_whitespace, etc.).
    """
    update_job(DB_PATH, job_id, status="running")
    logger.info("[%s] Job started — file: %s", job_id, pdf_path.name)

    def log(msg: str):
        append_log(DB_PATH, job_id, msg)
        logger.info("[%s] %s", job_id, msg)

    try:
        markdown = run_conversion(pdf_path, options, log)

        out_path = OUTPUT_FOLDER / f"{job_id}_{pdf_path.stem}.md"
        out_path.write_text(markdown, encoding="utf-8")

        word_count = len(markdown.split())
        line_count = markdown.count("\n")
        log(f"Done — {word_count:,} words, {line_count:,} lines")

        update_job(
            DB_PATH,
            job_id,
            status="done",
            output_file=str(out_path),
            preview=markdown[:3000],
            stats={"words": word_count, "lines": line_count},
        )
        logger.info(
            "[%s] Job completed — %s words, %s lines", job_id, word_count, line_count
        )

    except Exception as exc:
        update_job(DB_PATH, job_id, status="error", error=str(exc))
        log(f"Error: {exc}")
        logger.exception("[%s] Job failed", job_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index() -> str:
    """Serve the main browser UI.

    Returns:
        Rendered HTML string for ``templates/index.html``.
    """
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    """Accept a PDF upload, enqueue a conversion job, and return the job ID.

    Expects a ``multipart/form-data`` POST with:
        - ``file``: the PDF file.
        - ``backend``: one of ``docling``, ``pymupdf4llm``, ``marker``,
          ``llamaparse`` (default: ``docling``).
        - ``ocr``: ``"true"`` / ``"false"`` (default: ``"false"``).
        - ``tables``: ``"true"`` / ``"false"`` (default: ``"true"``).
        - ``clean_whitespace``: ``"true"`` / ``"false"`` (default: ``"true"``).
        - ``llamaparse_api_key``: optional; falls back to ``LLAMA_CLOUD_API_KEY``
          env var.

    Returns:
        JSON ``{"job_id": str}`` with HTTP 200 on success.
        JSON ``{"error": str}`` with HTTP 400 if validation fails.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename provided"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    backend = request.form.get("backend", "docling")

    options: dict = {
        "backend": backend,
        "ocr": request.form.get("ocr") == "true",
        "tables": request.form.get("tables", "true") == "true",
        "clean_whitespace": request.form.get("clean_whitespace", "true") == "true",
        "device": request.form.get("device", "gpu"),
        # LlamaParse: key from form (fallback to env variable inside converter)
        "llamaparse_api_key": request.form.get("llamaparse_api_key", "").strip()
        or None,
    }

    job_id = str(uuid.uuid4())[:8]
    safe_file = secure_filename(file.filename)
    if not safe_file:
        return jsonify({"error": "Invalid filename"}), 400
    pdf_path = UPLOAD_FOLDER / f"{job_id}_{safe_file}"
    create_job(DB_PATH, job_id, file.filename)
    file.save(pdf_path)

    logger.info(
        "[%s] Queued — file: %s, backend: %s", job_id, file.filename, options["backend"]
    )

    _executor.submit(_worker, job_id, pdf_path, options)

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    """Return the current state of a conversion job.

    Args:
        job_id: The job identifier returned by ``/convert``.

    Returns:
        JSON representation of the job dict (status, log, stats, etc.)
        with HTTP 200, or ``{"error": "Job not found"}`` with HTTP 404.
    """
    job = get_job(DB_PATH, job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/download/<job_id>")
def download(job_id: str):
    """Stream the finished Markdown file as a download.

    Args:
        job_id: The job identifier returned by ``/convert``.

    Returns:
        The ``.md`` file as an attachment with HTTP 200, or
        ``{"error": ...}`` with HTTP 404 if the job is unknown or not yet done.
    """
    job = get_job(DB_PATH, job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "Not ready or job unknown"}), 404
    return send_file(job["output_file"], as_attachment=True)


@app.route("/jobs")
def list_jobs():
    """List all known jobs with their current status.

    Returns:
        JSON array of objects, each containing ``job_id``, ``filename``,
        and ``status``.
    """
    return jsonify(db_list_jobs(DB_PATH))

@app.route("/system")
def system_info():
    gpu = torch.cuda.is_available()
    return jsonify(
        {
            "os": f"{platform.system()} {platform.release()}",
            "gpu_available": gpu,
            "gpu_name": torch.cuda.get_device_name(0) if gpu else None,
            "gpu_vram_mb": (
                torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
                if gpu
                else None
            ),
        }
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
