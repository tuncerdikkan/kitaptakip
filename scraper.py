import os
import re
from urllib.parse import quote
from urllib.parse import urljoin

import requests
import truststore
from bs4 import BeautifulSoup

truststore.inject_into_ssl()

BASE_URL = "https://www.kitapyurdu.com/"
SEARCH_URL = BASE_URL + "index.php?route=product/search&filter_name="
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
TIMEOUT = 5


def _session():
    return requests.Session()


def search_books(query):
    response = _session().get(SEARCH_URL + quote(query), headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for card in soup.select(".ky-product"):
        title_tag = card.select_one("a.ky-product-title")
        if not title_tag:
            continue
        author_tag = card.select_one(".ky-product-author a")
        publisher_tag = card.select_one(".ky-product-publisher a")
        cover_tag = card.select_one("a.ky-product-cover img")
        cover = ""
        if cover_tag:
            cover = cover_tag.get("data-src") or cover_tag.get("src") or ""
            if cover.startswith("//"):
                cover = "https:" + cover
            elif cover.startswith("/"):
                cover = urljoin(BASE_URL, cover)
        results.append({
            "title": title_tag.get_text(" ", strip=True),
            "author": author_tag.get_text(" ", strip=True) if author_tag else "",
            "publisher": publisher_tag.get_text(" ", strip=True) if publisher_tag else "",
            "cover": cover,
            "link": urljoin(BASE_URL, title_tag.get("href", "")),
        })
    return results


def get_book_details(link):
    response = _session().get(link, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    details = {"page_count": None, "isbn": None, "publish_year": None}
    for item in soup.select(".ky-pd-attributes__item"):
        text = item.get_text(" ", strip=True)
        match = re.search(r"(\d[\d.]*)", text)
        if "Sayfa Sayısı" in text and match:
            details["page_count"] = int(match.group(1).replace(".", ""))
        elif "ISBN" in text:
            isbn_match = re.search(r"[\dXx-]+", text)
            if isbn_match:
                details["isbn"] = isbn_match.group(0)
        elif "Yayın Yılı" in text or "Basım Yılı" in text:
            year_match = re.search(r"(19|20)\d{2}", text)
            if year_match:
                details["publish_year"] = int(year_match.group(0))
    return details


def download_cover(url, title):
    if not url:
        return ""
    cover_dir = os.path.join(os.path.dirname(__file__), "static", "kapaklar")
    os.makedirs(cover_dir, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-").lower() or "kitap"
    filename = safe_name[:80] + ".jpg"
    path = os.path.join(cover_dir, filename)
    try:
        response = _session().get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        with open(path, "wb") as cover_file:
            cover_file.write(response.content)
        return "/static/kapaklar/" + filename
    except Exception:
        return ""
