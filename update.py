import json
import re
import time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
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


# --------------------------------
# HTML文字コード判定
# --------------------------------

def decode_html(data):

    candidates = []

    for enc in (
        "utf-8",
        "cp932",
        "shift_jis",
        "euc_jp"
    ):
        try:
            text = data.decode(enc)
            candidates.append(
                (text.count("\ufffd"), text)
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

    return candidates[0][1]


# --------------------------------
# HTML取得
# --------------------------------

def fetch_html(url):

    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "*/*;q=0.8"
            ),
            "Accept-Language":
                "ja,en-US;q=0.9,en;q=0.8",
            "Cache-Control":
                "no-cache"
        }
    )

    with urlopen(
        req,
        timeout=TIMEOUT
    ) as response:

        data = response.read()

    return decode_html(data)


# --------------------------------
# URL正規化
# --------------------------------

def normalize_url(href):

    if not href:
        return None

    href = href.strip()

    if href.startswith("//"):
        href = "https:" + href

    elif href.startswith("/"):
        href = urljoin(
            BASE_URL,
            href
        )

    elif not href.startswith("http"):
        href = urljoin(
            BASE_URL,
            href
        )

    parts = urlsplit(href)

    # フラグメント・クエリを除去
    href = urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        "",
        ""
    ))

    if not href.startswith(
        "https://eetimes.itmedia.co.jp/"
    ):
        return None

    # EE Timesの記事ページだけ
    if "/ee/articles/" not in href:
        return None

    # 実際の記事URL形式
    if not re.search(
        r"/ee/articles/\d{4}/\d{2}/\d{2}/[^/]+\.html$",
        href
    ):
        return None

    return href


# --------------------------------
# トップページから記事URLを取得
# --------------------------------

def extract_article_urls(html):

    urls = []

    # hrefをすべて調べる
    for match in re.finditer(
        r'href\s*=\s*["\']([^"\']+)["\']',
        html,
        re.IGNORECASE
    ):

        href = match.group(1)

        url = normalize_url(href)

        if not url:
            continue

        if url not in urls:
            urls.append(url)

    return urls


# --------------------------------
# HTMLタグ除去
# --------------------------------

def clean_html_text(text):

    text = re.sub(
        r"<[^>]+>",
        "",
        text
    )

    text = text.replace(
        "&amp;",
        "&"
    )

    text = text.replace(
        "&lt;",
        "<"
    )

    text = text.replace(
        "&gt;",
        ">"
    )

    text = text.replace(
        "&quot;",
        '"'
    )

    text = text.replace(
        "&#39;",
        "'"
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# --------------------------------
# 記事タイトル取得
# --------------------------------

def extract_title(html):

    patterns = [

        # og:title
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',

        # title
        r"<title[^>]*>(.*?)</title>"
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            html,
            re.IGNORECASE |
            re.DOTALL
        )

        if not m:
            continue

        title = clean_html_text(
            m.group(1)
        )

        # サイト名を除去
        title = re.sub(
            r"\s*\|\s*EE Times Japan\s*$",
            "",
            title,
            flags=re.IGNORECASE
        )

        title = re.sub(
            r"\s*-\s*EE Times Japan\s*$",
            "",
            title,
            flags=re.IGNORECASE
        )

        title = title.strip()

        if title:
            return title

    return None


# --------------------------------
# 公開日時取得
# --------------------------------

def extract_datetime(html):

    patterns = [

        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',

        r'"datePublished"\s*:\s*"([^"]+)"',

        r'"publishDate"\s*:\s*"([^"]+)"',

        r'(\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})',

        r'(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})',

        r'(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})'
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            html,
            re.IGNORECASE |
            re.DOTALL
        )

        if not m:
            continue

        value = m.group(1).strip()

        # ISO形式
        try:

            dt = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00"
                )
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=JST
                )

            return dt.astimezone(JST)

        except Exception:
            pass

        # 日本語形式
        m2 = re.match(
            r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})",
            value
        )

        if m2:

            try:

                return datetime(
                    int(m2.group(1)),
                    int(m2.group(2)),
                    int(m2.group(3)),
                    int(m2.group(4)),
                    int(m2.group(5)),
                    tzinfo=JST
                )

            except Exception:
                pass

        # yyyy/mm/dd
        m2 = re.match(
            r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})",
            value
        )

        if m2:

            try:

                return datetime(
                    int(m2.group(1)),
                    int(m2.group(2)),
                    int(m2.group(3)),
                    int(m2.group(4)),
                    int(m2.group(5)),
                    tzinfo=JST
                )

            except Exception:
                pass

        # yyyy-mm-dd
        m2 = re.match(
            r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})",
            value
        )

        if m2:

            try:

                return datetime(
                    int(m2.group(1)),
                    int(m2.group(2)),
                    int(m2.group(3)),
                    int(m2.group(4)),
                    int(m2.group(5)),
                    tzinfo=JST
                )

            except Exception:
                pass

    return None


# --------------------------------
# 1記事取得
# --------------------------------

def fetch_article(url):

    try:

        html = fetch_html(url)

        title = extract_title(html)

        if not title:
            print(
                "タイトル取得失敗:",
                url
            )
            return None

        dt = extract_datetime(html)

        if dt is None:

            # 日時が取れない場合は
            # URLの日付を使う
            m = re.search(
                r"/articles/(\d{2})(\d{2})/(\d{2})/",
                url
            )

            if m:

                year = 2000 + int(m.group(1))
                month = int(m.group(2))
                day = int(m.group(3))

                dt = datetime(
                    year,
                    month,
                    day,
                    tzinfo=JST
                )

            else:

                dt = datetime(
                    1970,
                    1,
                    1,
                    tzinfo=JST
                )

        return {
            "title": title,
            "link": url,
            "pubDate":
                dt.strftime(
                    "%a, %d %b %Y %H:%M:%S +0900"
                ),
            "_dt": dt
        }

    except Exception as e:

        print(
            "記事取得失敗:",
            url,
            str(e)
        )

        return None


# --------------------------------
# メイン
# --------------------------------

def main():

    print("================================")
    print("EE Times取得開始")
    print("================================")

    # --------------------------------
    # トップページ取得
    # --------------------------------

    try:

        html = fetch_html(
            BASE_URL
        )

        print(
            "トップページ取得成功:",
            len(html),
            "bytes相当"
        )

    except Exception as e:

        print(
            "トップページ取得失敗:",
            str(e)
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # --------------------------------
    # 記事URLを取得
    # --------------------------------

    urls = extract_article_urls(
        html
    )

    print(
        "記事URL候補:",
        len(urls)
    )

    if not urls:

        print(
            "記事URLがありません。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # --------------------------------
    # 記事取得
    # --------------------------------

    items = []

    total = len(urls)

    for number, url in enumerate(
        urls,
        1
    ):

        print(
            f"[{number}/{total}]",
            url
        )

        item = fetch_article(
            url
        )

        if item:

            print(
                "  →",
                item["title"]
            )

            items.append(
                item
            )

        time.sleep(
            0.2
        )

    # --------------------------------
    # 日付順
    # --------------------------------

    items.sort(
        key=lambda x: x["_dt"],
        reverse=True
    )

    # 最大50件
    items = items[:MAX_ITEMS]

    if not items:

        print(
            "記事を取得できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # --------------------------------
    # RSS用JSONに変換
    # --------------------------------

    for item in items:

        del item["_dt"]

    # --------------------------------
    # 保存
    # --------------------------------

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            items,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("--------------------------------")
    print(
        "取得成功:",
        len(items),
        "件"
    )

    print(
        "最新記事:",
        items[0]["title"]
    )

    print(
        items[0]["link"]
    )

    print(
        "JSON更新完了"
    )


if __name__ == "__main__":
    main()
