import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://eetimes.itmedia.co.jp/"
OUTPUT = "rss-data.json"

MAX_ITEMS = 50
TIMEOUT = 30

JST = timezone(timedelta(hours=9))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


# ==================================================
# 文字コード判定
# ==================================================

def detect_charset(data, content_type=""):
    m = re.search(
        r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)",
        content_type or "",
        re.IGNORECASE
    )

    if m:
        return m.group(1)

    head = data[:5000].decode(
        "ascii",
        errors="ignore"
    )

    m = re.search(
        r'<meta[^>]+charset=["\']?\s*([A-Za-z0-9._-]+)',
        head,
        re.IGNORECASE
    )

    if m:
        return m.group(1)

    m = re.search(
        r'charset\s*=\s*["\']?\s*([A-Za-z0-9._-]+)',
        head,
        re.IGNORECASE
    )

    if m:
        return m.group(1)

    return None


def decode_html(data, content_type=""):
    candidates = []

    detected = detect_charset(
        data,
        content_type
    )

    encodings = []

    if detected:
        encodings.append(detected)

    encodings.extend([
        "utf-8",
        "cp932",
        "shift_jis",
        "euc_jp"
    ])

    seen = set()

    for enc in encodings:

        key = enc.lower()

        if key in seen:
            continue

        seen.add(key)

        try:
            text = data.decode(enc)

            candidates.append(
                (
                    text.count("\ufffd"),
                    text,
                    enc
                )
            )

        except Exception:
            pass

    if not candidates:
        return data.decode(
            "utf-8",
            errors="replace"
        )

    candidates.sort(
        key=lambda x: x[0]
    )

    text = candidates[0][1]

    print(
        "文字コード:",
        candidates[0][2]
    )

    return text


# ==================================================
# HTML取得
# ==================================================

def fetch_html(url):

    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache"
        }
    )

    with urlopen(
        req,
        timeout=TIMEOUT
    ) as response:

        data = response.read()

        content_type = response.headers.get(
            "Content-Type",
            ""
        )

    return decode_html(
        data,
        content_type
    )


# ==================================================
# 記事URL抽出
# ==================================================

def extract_article_urls(html):

    if not html:
        return []

    urls = []

    seen = set()

    pattern = re.compile(
        r'href\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE
    )

    for match in pattern.finditer(html):

        href = match.group(1).strip()

        if not href:
            continue

        # 相対URL
        if href.startswith("//"):

            url = "https:" + href

        elif href.startswith("/"):

            url = urljoin(
                BASE_URL,
                href
            )

        elif href.startswith("http"):

            url = href

        else:

            url = urljoin(
                BASE_URL,
                href
            )

        # EE Times以外は除外
        if not url.startswith(
            "https://eetimes.itmedia.co.jp/"
        ):
            continue

        # 記事URLだけ
        if "/ee/articles/" not in url:
            continue

        # subtop等は除外
        if "/subtop/" in url:
            continue

        # クエリ・アンカー除去
        url = url.split("?")[0]
        url = url.split("#")[0]

        if url in seen:
            continue

        seen.add(url)
        urls.append(url)

    return urls


# ==================================================
# タイトル取得
# ==================================================

def extract_title(html):

    patterns = [

        r'<meta[^>]+property=["\']og:title["\']'
        r'[^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\']'
        r'[^>]+property=["\']og:title["\']',

        r"<title[^>]*>(.*?)</title>"
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        if not m:
            continue

        title = m.group(1)

        # HTMLタグ除去
        title = re.sub(
            r"<[^>]+>",
            "",
            title
