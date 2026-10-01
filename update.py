import urllib.request
import urllib.error
import json
import os
import re
import time
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

BASE_URL = "https://eetimes.itmedia.co.jp"
SOURCE_URL = "https://eetimes.itmedia.co.jp/"
OUTPUT = "rss-data.json"

MAX_ITEMS = 50
TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

JST = timezone(timedelta(hours=9))

ARTICLE_PATTERN = re.compile(
    r"/ee/(?:articles|spv)/(\d{2})(\d{2})/(\d{2})/"
)


class LinkParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current_href = None
        self.current_text = []
        self.links = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "a":
            return

        attrs = dict(attrs)
        href = attrs.get("href")

        if href:
            self.current_href = href
            self.current_text = []

    def handle_data(self, data):

        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag):

        if tag.lower() != "a":
            return

        if self.current_href is not None:

            text = " ".join(self.current_text)
            text = re.sub(r"\s+", " ", text).strip()

            self.links.append(
                (self.current_href, text)
            )

        self.current_href = None
        self.current_text = []


def normalize_url(url):

    if not url:
        return None

    url = url.strip()

    if url.startswith("//"):
        url = "https:" + url

    elif url.startswith("/"):
        url = urljoin(BASE_URL, url)

    elif not url.startswith("http"):
        url = urljoin(BASE_URL + "/", url)

    return url.split("#")[0]


def is_article_url(url):

    if not url:
        return False

    if not url.startswith(BASE_URL + "/ee/"):
        return False

    return ARTICLE_PATTERN.search(url) is not None


def date_from_url(url):

    match = ARTICLE_PATTERN.search(url)

    if not match:
        return None

    yy = int(match.group(1))
    mm = int(match.group(2))
    dd = int(match.group(3))

    try:

        return datetime(
            2000 + yy,
            mm,
            dd,
            0,
            0,
            0,
            tzinfo=JST
        )

    except ValueError:

        return None


def detect_charset(data, content_type):

    if content_type:

        match = re.search(
            r"charset\s*=\s*[\"']?([\w.-]+)",
            content_type,
            re.I
        )

        if match:
            return match.group(1).strip()

    head = data[:10000]

    match = re.search(
        rb'<meta[^>]+charset\s*=\s*["\']?\s*([A-Za-z0-9._-]+)',
        head,
        re.I
    )

    if match:

        return match.group(1).decode(
            "ascii",
            errors="ignore"
        ).strip()

    match = re.search(
        rb'<meta[^>]+content\s*=\s*["\'][^"\']*charset\s*=\s*'
        rb'([A-Za-z0-9._-]+)',
        head,
        re.I
    )

    if match:

        return match.group(1).decode(
            "ascii",
            errors="ignore"
        ).strip()

    return None


def decode_html(data, content_type):

    charset = detect_charset(
        data,
        content_type
    )

    candidates = []

    if charset:
        candidates.append(charset)

    candidates.extend([
        "utf-8",
        "cp932",
        "shift_jis",
        "euc_jp"
    ])

    tried = set()

    best_html = None
    best_charset = None
    best_replacements = 10 ** 9

    for candidate in candidates:

        candidate_key = candidate.lower()

        if candidate_key in tried:
            continue

        tried.add(candidate_key)

        try:

            html = data.decode(
                candidate,
                errors="replace"
            )

            replacements = html.count("�")

            print(
                "文字コード:",
                candidate,
                " / �:",
                replacements
            )

            if replacements < best_replacements:

                best_html = html
                best_charset = candidate
                best_replacements = replacements

            if replacements == 0:

                print(
                    "使用文字コード:",
                    candidate
                )

                return html

        except Exception:
            pass

    if best_html is not None:

        print(
            "使用文字コード:",
            best_charset
        )

        return best_html

    return data.decode(
        "utf-8",
        errors="replace"
    )


def fetch_url(url):

    print()
    print("取得開始:")
    print(url)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT
        ) as response:

            data = response.read()

            content_type = response.headers.get(
                "Content-Type",
                ""
            )

            print(
                "Content-Type:",
                content_type
            )

            print(
                "取得成功:",
                len(data),
                "bytes"
            )

            return decode_html(
                data,
                content_type
            )

    except urllib.error.HTTPError as e:

        print(
            "HTTPエラー:",
            e.code,
            e.reason
        )

    except urllib.error.URLError as e:

        print(
            "URLエラー:",
            e.reason
        )

    except TimeoutError:

        print("タイムアウト")

    except Exception as e:

        print(
            "予期しないエラー:",
            repr(e)
        )

    return None


def clean_title(title):

    if not title:
        return ""

    title = re.sub(
        r"<[^>]+>",
        "",
        title
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    ).strip()

    title = re.sub(
        r"\s*\|\s*EE Times Japan\s*$",
        "",
        title,
        flags=re.I
    )

    return title.strip()


def extract_article_info(
    url,
    fallback_title=""
):

    html = fetch_url(url)

    if not html:

        fallback_date = date_from_url(url)

        if not fallback_title:
            return None

        return {
            "title": clean_title(fallback_title),
            "link": url,
            "pubDate": (
                fallback_date.strftime(
                    "%a, %d %b %Y 00:00:00 +0900"
                )
                if fallback_date
                else ""
            ),
            "_date": (
                fallback_date.isoformat()
                if fallback_date
                else ""
            )
        }

    title = None

    title_patterns = [

        r'<meta[^>]+property=["\']og:title["\']'
        r'[^>]+content=["\'](.*?)["\']',

        r'<meta[^>]+content=["\'](.*?)["\']'
        r'[^>]+property=["\']og:title["\']'
    ]

    for pattern in title_patterns:

        match = re.search(
            pattern,
            html,
            re.I | re.S
        )

        if match:

            title = match.group(1).strip()
            break

    if not title:

        match = re.search(
            r"<title[^>]*>(.*?)</title>",
            html,
            re.I | re.S
        )

        if match:

            title = match.group(1).strip()

    if not title:
        title = fallback_title

    title = clean_title(title)

    if not title:
        return None

    article_date = date_from_url(url)

    if article_date:

        pub_date = article_date.strftime(
            "%a, %d %b %Y 00:00:00 +0900"
        )

        sort_date = article_date.isoformat()

    else:

        pub_date = ""
        sort_date = ""

    return {
        "title": title,
        "link": url,
        "pubDate": pub_date,
        "_date": sort_date
    }


def main():

    print("========================================")
    print("EE Times Japan 直接取得")
    print("RSSは使用しません")
    print("取得元：トップページ")
    print("Top Stories + 新着記事")
    print("========================================")

    html = fetch_url(
        SOURCE_URL
    )

    if not html:

        print(
            "トップページを取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    parser = LinkParser()

    try:

        parser.feed(html)

    except Exception as e:

        print(
            "HTML解析エラー:",
            repr(e)
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    candidate_articles = {}

    for href, text in parser.links:

        url = normalize_url(href)

        if not is_article_url(url):
            continue

        if url not in candidate_articles:

            candidate_articles[url] = text

        else:

            old_text = candidate_articles[url]

            if len(text) > len(old_text):
                candidate_articles[url] = text

    print("========================================")

    print(
        "トップページから取得した記事URL:",
        len(candidate_articles)
    )

    print("========================================")

    if not candidate_articles:

        print(
            "記事URLを取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    candidates = list(
        candidate_articles.items()
    )

    candidates.sort(
        key=lambda item: (
            date_from_url(item[0])
            or datetime(
                2000,
                1,
                1,
                tzinfo=JST
            )
        ),
        reverse=True
    )

    print(
        "記事ページ確認数:",
        len(candidates)
    )

    articles = []

    for index, (
        url,
        listing_title
    ) in enumerate(
        candidates,
        1
    ):

        print("----------------------------------------")

        print(
            "記事",
            index,
            "/",
            len(candidates)
        )

        print(
            "URL:",
            url
        )

        print(
            "一覧タイトル:",
            listing_title
        )

        article = extract_article_info(
            url,
            listing_title
        )

        if article:
            articles.append(article)

        time.sleep(0.2)

    if not articles:

        print(
            "記事を1件も取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    unique_articles = {}

    for article in articles:

        unique_articles[
            article["link"]
        ] = article

    articles = list(
        unique_articles.values()
    )

    articles.sort(
        key=lambda article: (
            article.get(
                "_date",
                ""
            )
        ),
        reverse=True
    )

    articles = articles[
        :MAX_ITEMS
    ]

    print("========================================")
    print("最終保存記事一覧")
    print("========================================")

    for index, article in enumerate(
        articles,
        1
    ):

        print(
            index,
            "|",
            article["pubDate"],
            "|",
            article["title"]
        )

        print(
            "   ",
            article["link"]
        )

    print("========================================")

    print(
        "保存記事数:",
        len(articles)
    )

    for article in articles:

        article.pop(
            "_date",
            None
        )

    temp_file = OUTPUT + ".tmp"

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                articles,
                f,
                ensure_ascii=False,
                indent=2
            )

            f.write("\n")

        os.replace(
            temp_file,
            OUTPUT
        )

        print(
            "JSON更新完了"
        )

        print(
            "保存記事数:",
            len(articles)
        )

    except Exception as e:

        print(
            "JSON保存エラー:",
            repr(e)
        )

        try:

            if os.path.exists(
                temp_file
            ):

                os.remove(
                    temp_file
                )

        except Exception:
            pass

        print(
            "既存JSONは変更しません。"
        )


if __name__ == "__main__":
    main()
