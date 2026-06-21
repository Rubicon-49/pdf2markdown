"""Integration tests for pdf2markdown.web_app.

Uses FastAPI's TestClient. The conversion pipeline is patched so tests
exercise the HTTP layer (upload → SSE → preview → download) without
loading any real PDF backends.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pdf2markdown.pdf_pipeline import PageProgress


@pytest.fixture
def client() -> TestClient:
    from pdf2markdown.web_app import app

    return TestClient(app)


@pytest.fixture
def pdf_bytes() -> bytes:
    """Minimal one-byte payload — the conversion pipeline is patched."""
    return b"%PDF-1.4 fake"


# ---------------------------------------------------------------------------
# /
# ---------------------------------------------------------------------------


def test_index_renders_form_and_backends(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "PDF" in body and ".md" in body
    assert 'name="backend"' in body
    # All four backends are offered as radio buttons.
    for value in ("docling", "pymupdf4llm", "marker", "llamaparse"):
        assert f'value="{value}"' in body


# ---------------------------------------------------------------------------
# /backend-info/{backend}
# ---------------------------------------------------------------------------


def test_backend_info_returns_known_backend(client: TestClient):
    resp = client.get("/backend-info/pymupdf4llm")
    assert resp.status_code == 200
    assert "CPU-only" in resp.text


def test_backend_info_unknown_404(client: TestClient):
    resp = client.get("/backend-info/nope")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /convert  + /events  + /preview + /download
# ---------------------------------------------------------------------------


def _fake_pages(pdf_path: Path, *_: Any, **__: Any) -> Iterator[PageProgress]:
    yield PageProgress(page=1, total=2, status="start")
    yield PageProgress(page=1, total=2, status="done", markdown="# one", elapsed=0.1)
    yield PageProgress(page=2, total=2, status="start")
    yield PageProgress(page=2, total=2, status="done", markdown="# two", elapsed=0.2)


def test_convert_rejects_non_pdf(client: TestClient):
    resp = client.post(
        "/convert",
        files={"pdf": ("foo.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_full_flow_convert_to_download(
    client: TestClient, pdf_bytes: bytes, tmp_path: Path
):
    """End-to-end: upload → wait for job → preview → download."""
    with patch(
        "pdf2markdown.web_app.convert_pdf_pages", side_effect=_fake_pages
    ):
        resp = client.post(
            "/convert",
            files={"pdf": ("doc.pdf", pdf_bytes, "application/pdf")},
            data={"backend": "pymupdf4llm"},
        )
        assert resp.status_code == 200
        job_id = resp.text
        assert len(job_id) == 16  # secrets.token_hex(8)

        # Consume the SSE stream — pulls events until the worker emits 'close'.
        with client.stream("GET", f"/events/{job_id}") as stream:
            events: list[tuple[str, dict]] = []
            current_event = None
            for line in stream.iter_lines():
                if line.startswith("event: "):
                    current_event = line[len("event: ") :]
                elif line.startswith("data: ") and current_event is not None:
                    events.append((current_event, json.loads(line[len("data: ") :])))
                    if current_event == "close":
                        break
                    current_event = None

        names = [name for name, _ in events]
        assert "done" in names
        assert names[-1] == "close"

        done_data = next(d for n, d in events if n == "done")
        assert done_data["pages"] == 2
        assert done_data["job_id"] == job_id

        # Preview fragment includes the merged markdown.
        preview = client.get(f"/preview/{job_id}")
        assert preview.status_code == 200
        assert "# one" in preview.text and "# two" in preview.text

        # Download serves the .md file.
        dl = client.get(f"/download/{job_id}")
        assert dl.status_code == 200
        body = dl.text
        assert "# one" in body and "# two" in body
        assert "---" in body  # page separator


def test_events_unknown_job_404(client: TestClient):
    resp = client.get("/events/deadbeefdeadbeef")
    assert resp.status_code == 404


def test_preview_before_done_returns_409(client: TestClient):
    """Hitting /preview while the job is still running returns 409."""
    from pdf2markdown.web_app import _new_job

    job = _new_job("x.pdf")
    resp = client.get(f"/preview/{job.id}")
    assert resp.status_code == 409
