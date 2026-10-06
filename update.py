import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
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


# EE Timesの記事URL
ARTICLE_PATTERN = re.compile(
    r"/ee/(?:articles|spv)/(\d{4})/(\d{2})/(\d{2})/"
)


# --------------------------------------------------
# 文字コード判定
# --------------------------------------------------

def decode_html(data):

    candidates = []

    for enc in [
        "utf-8",
        "cp932",
        "shift_jis",
        "euc_jp",
    ]:

        try:

            text = data.decode(enc)

            candidates.append(
                (
                    text.count("\ufffd"),
                    text
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

    return candidates[0][1]


# --------------------------------------------------
# トップページからリンクを全部取得
# --------------------------------------------------

class LinkParser(HTMLParser):

    def __init__(self):

        super().__init__(
            convert_charrefs=True
        )

        self.links = []

    def handle_starttag(
        self,
        tag,
        attrs
    ):

        if tag.lower() != "a":
            return

        attrs = dict(attrs)

        href = attrs.get("href")

        if href:
            self.links.append(
                href
            )


# --------------------------------------------------
# URL正規化
# --------------------------------------------------

def normalize_url(url):

    if not url:
        return None

    url = url.strip()

    if url.startswith("//"):

        url = "https:" + url

    elif url.startswith("/"):

        url = (
            BASE_URL.rstrip("/")
            + url
        )

    elif not url.startswith("http"):

        return None

    # EE Times記事だけ
    if not ARTICLE_PATTERN.search(url):

        return None

    # #以降を削除
    url = url.split("#")[0]

    return url


# --------------------------------------------------
# HTML取得
# --------------------------------------------------

def fetch_html(url):

    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": (
                "ja,en-US;q=0.9,en;q=0.8"
            ),
            "Referer": BASE_URL,
        }
    )

    with urlopen(
        req,
        timeout=TIMEOUT
    ) as response:

        data = response.read()

    return decode_html(data)


# --------------------------------------------------
# URLの日付
# --------------------------------------------------

def fallback_date_from_url(url):

    m = ARTICLE_PATTERN.search(url)

    if not m:
        return None

    year, month, day = m.groups()

    return datetime(
        int(year),
        int(month),
        int(day),
        0,
        0,
        0,
        tzinfo=JST
    )


# --------------------------------------------------
# 公開日時取得
# --------------------------------------------------

def extract_published_datetime(html):

    patterns = [

        # Open Graph
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',

        # JSON-LD
        r'"datePublished"\s*:\s*"([^"]+)"',

        r"'datePublished'\s*:\s*'([^']+)'",

        # publishDate
        r'"publishDate"\s*:\s*"([^"]+)"',

        r"'publishDate'\s*:\s*'([^']+)'",

        # published_time
        r'"published_time"\s*:\s*"([^"]+)"',

        r"'published_time'\s*:\s*'([^']+)'",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            html,
            re.IGNORECASE
        )

        if not m:
            continue

        value = (
            m.group(1)
            .strip()
            .replace(
                "Z",
                "+00:00"
            )
        )

        try:

            dt = datetime.fromisoformat(
                value
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=JST
                )

            return dt.astimezone(JST)

        except Exception:
            pass

    # --------------------------------------------------
    # 日本語日時
    # --------------------------------------------------

    patterns_jp = [

        r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})",

        r"(\d{4})/(\d{1,2})/(\d{1,2})\s*(\d{1,2}):(\d{2})",

        r"(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{2})",
    ]

    for pattern in patterns_jp:

        m = re.search(
            pattern,
            html
        )

        if not m:
            continue

        try:

            (
                year,
                month,
                day,
                hour,
                minute
            ) = map(
                int,
                m.groups()
            )

            return datetime(
                year,
                month,
                day,
                hour,
                minute,
                tzinfo=JST
            )

        except Exception:
            pass

    return None


# --------------------------------------------------
# タイトル取得
# --------------------------------------------------

def extract_title(html):

    patterns = [

        # og:title
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',

        # title
        r"<title[^>]*>(.*?)</title>",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        if not m:
            continue

        title = re.sub(
            r"\s+",
            " ",
            m.group(1)
        ).strip()

        if not title:
            continue

        # サイト名を削除
        title = re.sub(
            r"\s*[|｜]\s*EE Times Japan.*$",
            "",
            title,
            flags=re.IGNORECASE
        ).strip()

        return title

    return ""


# --------------------------------------------------
# 記事取得
# --------------------------------------------------

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

        published = (
            extract_published_datetime(
                html
            )
        )

        # 公開日時が取れない場合
        # URLの日付を使用
        if published is None:

            published = (
                fallback_date_from_url(
                    url
                )
            )

            if published is None:

                return None

            print(
                "URL日付:",
                published.strftime(
                    "%Y-%m-%d"
                ),
                title
            )

        else:

            print(
                "公開日時:",
                published.strftime(
                    "%Y-%m-%d %H:%M"
                ),
                title
            )

        return {
            "title": title,
            "link": url,
            "pubDate": published.strftime(
                "%a, %d %b %Y %H:%M:%S %z"
            ),
            "_datetime": published.isoformat(),
        }

    except Exception as e:

        print(
            "記事取得失敗:",
            url,
            str(e)
        )

        return None


# --------------------------------------------------
# メイン
# --------------------------------------------------

def main():

    print(
        "================================"
    )

    print(
        "EE Times RSS更新開始"
    )

    print(
        "================================"
    )

    # --------------------------------------------------
    # トップページ取得
    # --------------------------------------------------

    try:

        html = fetch_html(
            BASE_URL
        )

        print(
            "トップページ取得成功:",
            len(html),
            "bytes"
        )

    except (
        HTTPError,
        URLError,
        TimeoutError,
        Exception
    ) as e:

        print(
            "トップページ取得失敗:",
            str(e)
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # --------------------------------------------------
    # リンク解析
    # --------------------------------------------------

    parser = LinkParser()

    try:

        parser.feed(html)

    except Exception as e:

        print(
            "HTML解析失敗:",
            str(e)
        )

        print(
            "既存JSONを維持します。"
        )

        return

    print(
        "トップページ内リンク数:",
        len(parser.links)
    )

    # --------------------------------------------------
    # EE Times記事だけ抽出
    # --------------------------------------------------

    urls = []

    seen = set()

    for href in parser.links:

        url = normalize_url(
            href
        )

        if not url:
            continue

        if url in seen:
            continue

        seen.add(url)

        urls.append(url)

    print(
        "EE Times記事URL:",
        len(urls)
    )

    # --------------------------------------------------
    # 記事URLがない場合
    # --------------------------------------------------

    if not urls:

        print(
            "記事URLが1件もありません。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # --------------------------------------------------
    # 記事取得
    # --------------------------------------------------

    articles = []

    for index, url in enumerate(
        urls,
        start=1
    ):

        print(
            f"[{index}/{len(urls)}]",
            url
        )

        article = fetch_article(
            url
        )

        if article:

            articles.append(
                article
            )

        # サイトへの連続アクセスを避ける
        time.sleep(0.2)

    # --------------------------------------------------
    # 取得失敗
    # --------------------------------------------------

    if not articles:

        print(
            "記事を1件も取得できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # --------------------------------------------------
    # 重複除去
    # --------------------------------------------------

    unique = {}

    for article in articles:

        unique[
            article["link"]
        ] = article

    articles = list(
        unique.values()
    )

    # --------------------------------------------------
    # 公開日時の新しい順
    # --------------------------------------------------

    articles.sort(
        key=lambda x: x.get(
            "_datetime",
            ""
        ),
        reverse=True
    )

    # --------------------------------------------------
    # 最大50件
    # --------------------------------------------------

    articles = articles[
        :MAX_ITEMS
    ]

    # --------------------------------------------------
    # JSON出力
    # --------------------------------------------------

    output_items = []

    for article in articles:

        output_items.append(
            {
                "title": article[
                    "title"
                ],
                "link": article[
                    "link"
                ],
                "pubDate": article[
                    "pubDate"
                ],
            }
        )

    # --------------------------------------------------
    # 最新記事確認
    # --------------------------------------------------

    print()
    print(
        "================================"
    )

    print(
        "取得完了:",
        len(output_items),
        "件"
    )

    print(
        "================================"
    )

    print(
        "最新記事:"
    )

    if output_items:

        print(
            output_items[0][
                "pubDate"
            ]
        )

        print(
            output_items[0][
                "title"
            ]
        )

        print(
            output_items[0][
                "link"
            ]
        )

    # --------------------------------------------------
    # 一時ファイルに保存
    # --------------------------------------------------

    temp_file = (
        OUTPUT + ".tmp"
    )

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                output_items,
                f,
                ensure_ascii=False,
                indent=2
            )

            f.write("\n")

        os.replace(
            temp_file,
            OUTPUT
        )

    except Exception as e:

        print(
            "JSON保存失敗:",
            str(e)
        )

        if os.path.exists(
            temp_file
        ):

            try:
                os.remove(
                    temp_file
                )
            except Exception:
                pass

        return

    print(
        "rss-data.jsonを更新しました。"
    )


if __name__ == "__main__":

    main()
