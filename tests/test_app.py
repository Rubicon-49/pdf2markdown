import io
from concurrent.futures import Future

import pytest

from pdf2markdown.app import app
from pdf2markdown.job_store import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("pdf2markdown.app.DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr("pdf2markdown.app.UPLOAD_FOLDER", tmp_path)
    monkeypatch.setattr("pdf2markdown.app.OUTPUT_FOLDER", tmp_path)
    init_db(tmp_path / "test.db")

    def sync_submit(fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future

    monkeypatch.setattr("pdf2markdown.app._executor.submit", sync_submit)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index(client):
    response = client.get("/")
    assert response.status_code == 200


def test_convert_no_file(client):
    response = client.post("/convert")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_convert_wrong_filetype(client):
    data = {"file": (io.BytesIO(b"hello"), "document.txt")}
    response = client.post("/convert", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_convert_success(client, monkeypatch):
    monkeypatch.setattr("pdf2markdown.app.run_conversion", lambda *a, **kw: "# Hello")
    pdf_bytes = io.BytesIO(b"%PDF-1.4 fake content")
    data = {"file": (pdf_bytes, "test.pdf"), "backend": "docling"}
    response = client.post("/convert", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert "job_id" in response.get_json()


def test_status_unknown_job(client):
    response = client.get("/status/doesnotexist")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Job not found"


def test_status_known_job(client, monkeypatch):
    monkeypatch.setattr("pdf2markdown.app.run_conversion", lambda *a, **kw: "# Hello")
    pdf_bytes = io.BytesIO(b"%PDF-1.4 fake content")
    data = {"file": (pdf_bytes, "test.pdf"), "backend": "docling"}
    job_id = client.post(
        "/convert",
        data=data,
        content_type="multipart/form-data"
    ).get_json()["job_id"]
    response = client.get(f"/status/{job_id}")
    assert response.status_code == 200
    job = response.get_json()
    assert job["status"] == "done"
    assert "filename" in job
    assert "log" in job
    assert isinstance(job["log"], list)


def test_list_jobs(client):
    response = client.get("/jobs")
    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_download_unknown_job(client):
    response = client.get("/download/doesnotexist")
    assert response.status_code == 404


def test_download_job_not_ready(client, monkeypatch):
    monkeypatch.setattr("pdf2markdown.app._executor.submit", lambda *a, **kw: None)
    pdf_bytes = io.BytesIO(b"%PDF-1.4 fake content")
    data = {"file": (pdf_bytes, "test.pdf"), "backend": "docling"}
    job_id = client.post(
        "/convert", data=data, content_type="multipart/form-data"
    ).get_json()["job_id"]

    response = client.get(f"/download/{job_id}")
    assert response.status_code == 404


def test_download_completed_job(client, monkeypatch):
    monkeypatch.setattr("pdf2markdown.app.run_conversion", lambda *a, **kw: "# Hello")
    pdf_bytes = io.BytesIO(b"%PDF-1.4 fake content")
    data = {"file": (pdf_bytes, "test.pdf"), "backend": "docling"}
    job_id = client.post(
        "/convert",
        data=data,
        content_type="multipart/form-data"
    ).get_json()["job_id"]

    response = client.get(f"/download/{job_id}")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert b"# Hello" in response.data


def test_convert_invalid_filename(client):
    data = {"file": (io.BytesIO(b"%PDF-1.4"), "...")}
    response = client.post("/convert", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_convert_invalid_backend(client):
    pdf_bytes = io.BytesIO(b"%PDF-1.4 fake content")
    data = {"file": (pdf_bytes, "test.pdf"), "backend": "invalid"}
    job_id = client.post(
        "/convert", data=data, content_type="multipart/form-data"
    ).get_json()["job_id"]

    job = client.get(f"/status/{job_id}").get_json()
    assert job["status"] == "error"
    assert "invalid" in job["error"]
