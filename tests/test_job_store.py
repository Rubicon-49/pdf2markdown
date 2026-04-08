from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pdf2markdown.job_store import (
    append_log,
    create_job,
    get_job,
    init_db,
    list_jobs,
    purge_old_jobs,
    update_job,
)


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


def test_create_and_get_job(db):
    create_job(db, "abc12345", "report.pdf")
    job = get_job(db, "abc12345")

    assert job is not None
    assert job["job_id"] == "abc12345"
    assert job["filename"] == "report.pdf"
    assert job["status"] == "queued"
    assert job["log"] == []


def test_get_job_unknown(db):
    assert get_job(db, "doesnotexist") is None


def test_update_job_status(db):
    create_job(db, "abc12345", "report.pdf")
    update_job(db, "abc12345", status="running")

    job = get_job(db, "abc12345")
    assert job is not None
    assert job["status"] == "running"


def test_update_job_stats(db):
    create_job(db, "abc12345", "report.pdf")
    update_job(db, "abc12345", status="done", stats={"words": 100, "lines": 20})

    job = get_job(db, "abc12345")
    assert job is not None
    assert job["stats"] == {"words": 100, "lines": 20}


def test_append_log_order(db):
    create_job(db, "abc12345", "report.pdf")
    append_log(db, "abc12345", "Starting…")
    append_log(db, "abc12345", "Done")

    job = get_job(db, "abc12345")
    assert job is not None
    assert job["log"] == ["Starting…", "Done"]


def test_list_jobs(db):
    create_job(db, "aaaa1111", "a.pdf")
    create_job(db, "bbbb2222", "b.pdf")

    jobs = list_jobs(db)
    ids = [j["job_id"] for j in jobs]
    assert "aaaa1111" in ids
    assert "bbbb2222" in ids


def test_purge_old_jobs(db):
    create_job(db, "old11111", "old.pdf")
    create_job(db, "new22222", "new.pdf")

    # Manually backdate the old job
    import sqlite3

    conn = sqlite3.connect(db)
    old_date = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    conn.execute(
        "UPDATE jobs SET created_at = ? WHERE job_id = ?", (old_date, "old11111")
    )
    conn.commit()
    conn.close()

    purge_old_jobs(db, days=1)

    assert get_job(db, "old11111") is None
    assert get_job(db, "new22222") is not None


def test_purge_old_jobs_deletes_logs(db):
    import sqlite3

    create_job(db, "old11111", "old.pdf")
    append_log(db, "old11111", "some log")

    conn = sqlite3.connect(db)
    old_date = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    conn.execute(
        "UPDATE jobs SET created_at = ? WHERE job_id = ?", (old_date, "old11111")
    )
    conn.commit()
    conn.close()

    purge_old_jobs(db, days=1)

    conn = sqlite3.connect(db)
    logs = conn.execute(
        "SELECT * FROM job_logs WHERE job_id = ?", ("old11111",)
    ).fetchall()
    conn.close()
    assert logs == []


def test_list_jobs_order(db):
    create_job(db, "aaaa1111", "a.pdf")
    create_job(db, "bbbb2222", "b.pdf")
    jobs = list_jobs(db)
    ids = [j["job_id"] for j in jobs]
    assert ids.index("bbbb2222") < ids.index("aaaa1111")


def test_update_job_unknown_is_noop(db):
    update_job(db, "doesnotexist", status="running")
    assert get_job(db, "doesnotexist") is None
