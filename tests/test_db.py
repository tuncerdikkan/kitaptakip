import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import db


def setup_function():
    handle, path = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    os.unlink(path)
    db.DB_PATH = path
    db.init_db()


def test_page_rules():
    book_id = db.add_book({
        "title": "Suç ve Ceza",
        "author": "Dostoyevski",
        "page_count": 500,
        "status": "okunuyor",
    })
    assert db.add_reading(book_id, 100)["success"]
    assert not db.add_reading(book_id, 50)["success"]
    assert not db.add_reading(book_id, 501)["success"]


def test_reading_completion_moves_to_read():
    book_id = db.add_book({
        "title": "Kurgu Kitabı",
        "page_count": 200,
        "status": "okunuyor",
    })
    assert db.add_reading(book_id, 200)["success"]
    assert db.get_book(book_id)["status"] == "okundu"
    assert db.get_book(book_id)["finish_date"]


def test_manual_read_status_fills_page_progress():
    book_id = db.add_book({
        "title": "Elle Tamamlanan Kitap",
        "page_count": 240,
        "status": "okunuyor",
    })
    db.update_status(book_id, "okundu")
    book = db.get_books("okundu")[0]
    assert book["pages_read"] == 240


def test_duplicate_books_are_rejected():
    data = {"title": "Bir Kitap", "page_count": 100, "status": "okunacak"}
    assert db.add_book(data)
    assert db.add_book(data) is None


def test_annual_goal_setting():
    db.set_setting("annual_goal", 24)
    assert db.get_setting("annual_goal", 24) == 24


def test_finish_estimate():
    book_id = db.add_book({
        "title": "Tahmin Kitabı",
        "page_count": 350,
        "status": "okunuyor",
    })
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    with db.get_connection() as connection:
        connection.execute(
            "INSERT INTO readings(book_id,pages_read,read_at) VALUES(?,?,?)",
            (book_id, 100, (now - timedelta(days=6)).isoformat()),
        )
        connection.execute(
            "INSERT INTO readings(book_id,pages_read,read_at) VALUES(?,?,?)",
            (book_id, 200, now.isoformat()),
        )
    estimate = db.estimate_finish_days(book_id)
    assert estimate is not None
    assert estimate == 9


def test_delete_book_removes_readings():
    book_id = db.add_book({
        "title": "Silinecek Kitap",
        "page_count": 300,
        "status": "okunuyor",
    })
    assert db.add_reading(book_id, 100)["success"]
    db.delete_book(book_id)
    assert db.get_book(book_id) is None
    with db.get_connection() as connection:
        readings = connection.execute(
            "SELECT COUNT(*) AS count FROM readings WHERE book_id=?", (book_id,)
        ).fetchone()["count"]
    assert readings == 0
