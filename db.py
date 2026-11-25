import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "data", "kitap.db"))
TZ = ZoneInfo("Europe/Istanbul")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT,
                publisher TEXT,
                cover_path TEXT,
                external_url TEXT,
                page_count INTEGER CHECK(page_count > 0),
                isbn TEXT,
                publish_year INTEGER,
                status TEXT NOT NULL CHECK(status IN ('okunacak','okunuyor','okundu')),
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                note TEXT,
                start_date TEXT,
                finish_date TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                pages_read INTEGER NOT NULL,
                read_at TEXT NOT NULL,
                FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(books)").fetchall()
        }
        if "start_date" not in columns:
            connection.execute("ALTER TABLE books ADD COLUMN start_date TEXT")


def add_book(data):
    with get_connection() as connection:
        duplicate = connection.execute(
            "SELECT id FROM books WHERE isbn IS NOT NULL AND isbn = ?",
            (data.get("isbn"),),
        ).fetchone() if data.get("isbn") else None
        if duplicate:
            return None
        duplicate = connection.execute(
            "SELECT id FROM books WHERE lower(title)=lower(?)",
            (data["title"],),
        ).fetchone()
        if duplicate:
            return None
        cursor = connection.execute("""
            INSERT INTO books
            (title, author, publisher, cover_path, external_url, page_count, isbn,
             publish_year, status, start_date, finish_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["title"], data.get("author"), data.get("publisher"),
            data.get("cover_path"), data.get("external_url"), data.get("page_count"),
            data.get("isbn"), data.get("publish_year"), data["status"],
            data.get("start_date"), data.get("finish_date"),
            datetime.now(TZ).isoformat(),
        ))
        return cursor.lastrowid


def get_books(status=None):
    with get_connection() as connection:
        if status:
            rows = connection.execute(
                "SELECT * FROM books WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
        books = [dict(row) for row in rows]
        for book in books:
            latest = connection.execute(
                "SELECT COALESCE(MAX(pages_read), 0) AS pages FROM readings WHERE book_id=?",
                (book["id"],),
            ).fetchone()
            book["pages_read"] = latest["pages"] if latest else 0
            if book["status"] == "okundu" and book["page_count"]:
                book["pages_read"] = book["page_count"]
            latest_reading = connection.execute(
                "SELECT id FROM readings WHERE book_id=? ORDER BY read_at DESC, id DESC LIMIT 1",
                (book["id"],),
            ).fetchone()
            book["latest_reading_id"] = latest_reading["id"] if latest_reading else None
        for book in books:
            book["estimate_days"] = estimate_finish_days(book["id"])
        return books


def get_book(book_id):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not row:
            return None
        book = dict(row)
        book["readings"] = [dict(r) for r in connection.execute(
            "SELECT * FROM readings WHERE book_id=? ORDER BY read_at DESC", (book_id,)
        ).fetchall()]
        if book["status"] == "okundu" and book["page_count"]:
            book["pages_read"] = book["page_count"]
        else:
            latest = connection.execute(
                "SELECT COALESCE(MAX(pages_read), 0) AS pages "
                "FROM readings WHERE book_id=?",
                (book_id,),
            ).fetchone()
            book["pages_read"] = latest["pages"] if latest else 0
        return book


def delete_book(book_id):
    with get_connection() as connection:
        connection.execute("DELETE FROM readings WHERE book_id=?", (book_id,))
        connection.execute("DELETE FROM books WHERE id=?", (book_id,))


def update_status(book_id, status):
    with get_connection() as connection:
        today = datetime.now(TZ).date().isoformat()
        finish_date = today if status == "okundu" else None
        book = connection.execute(
            "SELECT page_count, start_date FROM books WHERE id=?", (book_id,)
        ).fetchone()
        start_date = None
        if status in ("okunuyor", "okundu"):
            start_date = book["start_date"] or today
        if status == "okundu":
            latest = connection.execute(
                "SELECT COALESCE(MAX(pages_read), 0) AS pages FROM readings WHERE book_id=?",
                (book_id,),
            ).fetchone()
            if book and book["page_count"] and (
                not latest or latest["pages"] != book["page_count"]
            ):
                connection.execute(
                    "INSERT INTO readings (book_id, pages_read, read_at) VALUES (?, ?, ?)",
                    (book_id, book["page_count"], datetime.now(TZ).isoformat()),
                )
        connection.execute(
            "UPDATE books SET status=?, start_date=COALESCE(start_date, ?), "
            "finish_date=? WHERE id=?",
            (status, start_date, finish_date, book_id),
        )


def add_reading(book_id, pages):
    if not pages or pages < 0:
        return {"success": False, "error": "Okunan sayfa 0 veya daha büyük olmalıdır."}
    with get_connection() as connection:
        book = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not book:
            return {"success": False, "error": "Kitap bulunamadı."}
        previous = connection.execute(
            "SELECT COALESCE(MAX(pages_read), 0) AS pages FROM readings WHERE book_id=?",
            (book_id,),
        ).fetchone()["pages"]
        if pages < previous:
            return {"success": False, "error": "Okunan sayfa önceki kayıttan küçük olamaz."}
        if pages > book["page_count"]:
            return {"success": False, "error": "Okunan sayfa toplam sayfa sayısını aşamaz."}
        connection.execute(
            "INSERT INTO readings (book_id, pages_read, read_at) VALUES (?, ?, ?)",
            (book_id, pages, datetime.now(TZ).isoformat()),
        )
        if pages == 0:
            connection.execute(
                "UPDATE books SET status='okunacak', finish_date=NULL WHERE id=?",
                (book_id,),
            )
        elif pages == book["page_count"]:
            connection.execute(
                "UPDATE books SET status='okundu', "
                "start_date=COALESCE(start_date, ?), finish_date=? WHERE id=?",
                (
                    datetime.now(TZ).date().isoformat(),
                    datetime.now(TZ).date().isoformat(),
                    book_id,
                ),
            )
        elif pages > 0:
            today = datetime.now(TZ).date().isoformat()
            connection.execute(
                "UPDATE books SET status='okunuyor', "
                "start_date=COALESCE(start_date, ?) WHERE id=?",
                (today, book_id),
            )
    return {"success": True}


def delete_reading(reading_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT book_id FROM readings WHERE id=?", (reading_id,)
        ).fetchone()
        if not row:
            return
        book_id = row["book_id"]
        connection.execute("DELETE FROM readings WHERE id=?", (reading_id,))
        latest = connection.execute(
            "SELECT COALESCE(MAX(pages_read), 0) AS pages FROM readings WHERE book_id=?",
            (book_id,),
        ).fetchone()["pages"]
        book = connection.execute(
            "SELECT page_count FROM books WHERE id=?", (book_id,)
        ).fetchone()
        status = "okundu" if latest == book["page_count"] else (
            "okunuyor" if latest > 0 else "okunacak"
        )
        finish_date = datetime.now(TZ).date().isoformat() if status == "okundu" else None
        connection.execute(
            "UPDATE books SET status=?, finish_date=? WHERE id=?",
            (status, finish_date, book_id),
        )


def update_rating(book_id, rating, note):
    with get_connection() as connection:
        if rating is not None:
            rating = max(1, min(5, rating))
        connection.execute(
            "UPDATE books SET rating=?, note=? WHERE id=?",
            (rating, note, book_id),
        )


def update_dates(book_id, start_date=None, finish_date=None):
    if start_date and finish_date and finish_date < start_date:
        return {"success": False, "error": "Bitiş tarihi başlangıç tarihinden önce olamaz."}
    with get_connection() as connection:
        connection.execute(
            "UPDATE books SET start_date=?, finish_date=? WHERE id=?",
            (start_date or None, finish_date or None, book_id),
        )
    return {"success": True}


def get_setting(key, default=None):
    with get_connection() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return row["value"]


def set_setting(key, value):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def estimate_finish_days(book_id):
    with get_connection() as connection:
        book = connection.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not book:
            return None
        cutoff = (datetime.now(TZ) - timedelta(days=7)).isoformat()
        rows = connection.execute(
            "SELECT pages_read, read_at FROM readings "
            "WHERE book_id=? AND read_at>=? ORDER BY read_at",
            (book_id, cutoff),
        ).fetchall()
        if len(rows) < 2:
            return None
        daily_total = rows[-1]["pages_read"] - rows[0]["pages_read"]
        if daily_total <= 0:
            return None
        elapsed = max(
            1,
            (datetime.fromisoformat(rows[-1]["read_at"]) -
             datetime.fromisoformat(rows[0]["read_at"])).total_seconds() / 86400,
        )
        remaining = book["page_count"] - rows[-1]["pages_read"]
        if remaining <= 0:
            return 0
        rate = daily_total / elapsed
        return max(0, round(remaining / rate))


def get_statistics():
    now = datetime.now(TZ)
    year = now.year
    with get_connection() as connection:
        finished = connection.execute(
            "SELECT COUNT(*) AS count FROM books "
            "WHERE status='okundu' AND substr(finish_date,1,4)=?",
            (str(year),),
        ).fetchone()["count"]
        monthly = []
        for month in range(1, 13):
            count = connection.execute(
                "SELECT COALESCE(SUM(pages_read), 0) AS pages FROM readings "
                "WHERE substr(read_at,1,7)=?",
                (f"{year}-{month:02d}",),
            ).fetchone()["pages"]
            monthly.append(count)
        streak = 0
        streak_row = connection.execute(
            "SELECT DISTINCT substr(read_at,1,10) AS day FROM readings ORDER BY day DESC"
        ).fetchall()
        dates = [datetime.strptime(row["day"], "%Y-%m-%d").date() for row in streak_row]
        if dates:
            current = now.date()
            if dates[0] not in (current, current - timedelta(days=1)):
                streak = 0
            else:
                streak = 1
                for previous, following in zip(dates, dates[1:]):
                    if previous - following == timedelta(days=1):
                        streak += 1
                    else:
                        break
    return {"finished": finished, "monthly": monthly, "streak": streak}
