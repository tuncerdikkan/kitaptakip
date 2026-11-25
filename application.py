import os
from functools import wraps
from urllib.parse import quote

from flask import Flask, redirect, render_template, request, session, url_for

import db
import scraper


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gelistirme-anahtari")

STATUS_LABELS = {"okunacak": "Okunacak", "okunuyor": "Okunuyor", "okundu": "Okundu"}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def initialize_database():
    db.init_db()


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == "test" and request.form.get("password") == "123":
            session["logged_in"] = True
            return redirect(url_for("library"))
        error = "Kullanıcı adı veya şifre hatalı."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def library():
    active_status = request.args.get("raf", "okunuyor")
    if active_status not in STATUS_LABELS:
        active_status = "okunuyor"
    books = db.get_books(active_status)
    return render_template("library.html", books=books, active_status=active_status,
                           status_labels=STATUS_LABELS)


@app.route("/ara")
@login_required
def search():
    query = request.args.get("q", "").strip()
    results = []
    message = None
    if query:
        try:
            results = scraper.search_books(query)
            if not results:
                message = "Kitap bulunamadı, elle ekleyebilirsin"
        except Exception:
            message = "Şu an kitap aranamıyor, elle ekleyebilirsin"
    return render_template("search.html", query=query, results=results, message=message)


@app.route("/ekle/<durum>", methods=["POST"])
@login_required
def add_from_search(durum):
    if durum not in STATUS_LABELS:
        return redirect(url_for("search"))
    link = request.form.get("link", "")
    isbn = request.form.get("isbn", "")
    try:
        if link:
            details = scraper.get_book_details(link)
        else:
            details = {}
    except Exception:
        details = {}
    cover_path = scraper.download_cover(
        request.form.get("cover", ""),
        request.form.get("title", ""),
    )
    today = db.datetime.now(db.TZ).date().isoformat()
    start_date = today if durum in ("okunuyor", "okundu") else None
    finish_date = today if durum == "okundu" else None
    book_id = db.add_book({
        "title": request.form.get("title", "").strip(),
        "author": request.form.get("author", "").strip(),
        "publisher": request.form.get("publisher", "").strip(),
        "cover_path": cover_path,
        "external_url": link,
        "page_count": details.get("page_count") or request.form.get("page_count", type=int),
        "isbn": details.get("isbn") or isbn,
        "publish_year": details.get("publish_year"),
        "status": durum,
        "start_date": start_date,
        "finish_date": finish_date,
    })
    if book_id:
        return redirect(url_for("library", raf=durum))
    return redirect(url_for("library", raf=durum))


@app.route("/kitap/elle-ekle", methods=["GET", "POST"])
@login_required
def add_manual():
    error = None
    if request.method == "POST":
        page_count = request.form.get("page_count", type=int)
        if not page_count or page_count < 1:
            error = "Sayfa sayısı 0'dan büyük olmalıdır."
        else:
            status = request.form.get("status", "okunacak")
            today = db.datetime.now(db.TZ).date().isoformat()
            start_date = request.form.get("start_date", "").strip() or (
                today if status in ("okunuyor", "okundu") else None
            )
            finish_date = request.form.get("finish_date", "").strip() or (
                today if status == "okundu" else None
            )
            book_id = db.add_book({
                "title": request.form["title"].strip(),
                "author": request.form.get("author", "").strip(),
                "publisher": request.form.get("publisher", "").strip(),
                "cover_path": "",
                "external_url": request.form.get("external_url", "").strip(),
                "page_count": page_count,
                "isbn": request.form.get("isbn", "").strip(),
                "publish_year": request.form.get("publish_year", type=int),
                "status": status,
                "start_date": start_date,
                "finish_date": finish_date,
            })
            if book_id:
                return redirect(url_for("library", raf=request.form.get("status", "okunacak")))
            error = "Bu kitap zaten kitaplığınıza ekli."
    return render_template("manual.html", error=error)


@app.route("/kitap/<int:book_id>/durum", methods=["POST"])
@login_required
def update_status(book_id):
    status = request.form.get("status")
    if status in STATUS_LABELS:
        db.update_status(book_id, status)
    return redirect(request.referrer or url_for("library"))


@app.route("/kitap/<int:book_id>/sil", methods=["POST"])
@login_required
def delete_book(book_id):
    db.delete_book(book_id)
    return redirect(request.referrer or url_for("library"))


@app.route("/kitap/<int:book_id>/okuma", methods=["POST"])
@login_required
def add_reading(book_id):
    pages = request.form.get("pages", type=int)
    result = db.add_reading(book_id, pages)
    if not result["success"]:
        session["flash_error"] = result["error"]
    return redirect(request.referrer or url_for("library"))


@app.route("/okuma/<int:reading_id>/sil", methods=["POST"])
@login_required
def delete_reading(reading_id):
    db.delete_reading(reading_id)
    return redirect(request.referrer or url_for("library"))


@app.route("/kitap/<int:book_id>/puan", methods=["POST"])
@login_required
def update_rating(book_id):
    rating = request.form.get("rating", type=int)
    note = request.form.get("note", "").strip()
    db.update_rating(book_id, rating, note)
    return redirect(request.referrer or url_for("library"))


@app.route("/kitap/<int:book_id>/tarihler", methods=["POST"])
@login_required
def update_dates(book_id):
    result = db.update_dates(
        book_id,
        request.form.get("start_date", "").strip(),
        request.form.get("finish_date", "").strip(),
    )
    if not result["success"]:
        session["flash_error"] = result["error"]
    return redirect(request.referrer or url_for("library"))


@app.route("/istatistik")
@login_required
def statistics():
    data = db.get_statistics()
    goal = db.get_setting("annual_goal", 24)
    return render_template("statistics.html", data=data, goal=goal)


@app.route("/ayarlar", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        goal = request.form.get("annual_goal", type=int)
        if goal and goal > 0:
            db.set_setting("annual_goal", goal)
    return redirect(url_for("statistics")) if request.method == "POST" else render_template(
        "settings.html", goal=db.get_setting("annual_goal", 24)
    )


@app.context_processor
def global_context():
    return {
        "logged_in": session.get("logged_in", False),
        "flash_error": session.pop("flash_error", None),
        "status_labels": STATUS_LABELS,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=True)
