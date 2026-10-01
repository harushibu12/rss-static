import urllib.request
import urllib.error
import json
import os
import re
import time
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin


# =========================================================
# 設定
# =========================================================

BASE_URL = "https://eetimes.itmedia.co.jp"

# RSSではなく、EE Times Japan本体を取得
SOURCE_URLS = [
    "https://eetimes.itmedia.co.jp/ee/",
    "https://eetimes.itmedia.co.jp/ee/subtop/domestic/index.html",
    "https://eetimes.itmedia.co.jp/ee/subtop/world/index.html",
    "https://eetimes.itmedia.co.jp/ee/subtop/technology/",
]

OUTPUT = "rss-data.json"

MAX_ITEMS = 50

TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

JST = timezone(timedelta(hours=9))


# =========================================================
# HTMLから記事URLを抽出
# =========================================================

class LinkParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

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

            text = " ".join(
                self.current_text
            ).strip()

            self.links.append(
                (
                    self.current_href,
                    text
                )
            )

        self.current_href = None
        self.current_text = []


# =========================================================
# ページ取得
# =========================================================

def fetch_url(url):

    print()
    print("取得開始:")
    print(url)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT
        ) as response:

            data = response.read()

            charset = (
                response.headers.get_content_charset()
                or "utf-8"
            )

            try:
                html = data.decode(charset)
            except UnicodeDecodeError:
                html = data.decode(
                    "utf-8",
                    errors="replace"
                )

            print(
                "取得成功:",
                len(data),
                "bytes"
            )

            return html

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


# =========================================================
# EE Timesの記事URLか判定
# =========================================================

ARTICLE_PATTERN = re.compile(
    r"/ee/(?:articles|spv)/"
    r"(\d{2})(\d{2})/"
    r"(\d{2})/"
)


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

    return url


def is_article_url(url):

    if not url:
        return False

    return ARTICLE_PATTERN.search(url) is not None


# =========================================================
# URLから記事日付を推定
# =========================================================

def date_from_url(url):

    match = ARTICLE_PATTERN.search(url)

    if not match:
        return None

    yy = int(match.group(1))
    mm = int(match.group(2))
    dd = int(match.group(3))

    year = 2000 + yy

    try:

        return datetime(
            year,
            mm,
            dd,
            tzinfo=JST
        )

    except ValueError:

        return None


# =========================================================
# 記事ページからタイトル・公開日時を取得
# =========================================================

def extract_article_info(url):

    html = fetch_url(url)

    if not html:
        return None

    # -----------------------------------------------------
    # タイトル
    # -----------------------------------------------------

    title = None

    # og:title
    match = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        html,
        re.I | re.S
    )

    if match:
        title = match.group(1).strip()

    # titleタグ
    if not title:

        match = re.search(
            r"<title[^>]*>(.*?)</title>",
            html,
            re.I | re.S
        )

        if match:
            title = re.sub(
                r"\s+",
                " ",
                match.group(1)
            ).strip()

    # -----------------------------------------------------
    # 公開日時
    # -----------------------------------------------------

    pub_date = None

    # JSON-LD
    patterns = [
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"dateCreated"\s*:\s*"([^"]+)"'
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.I
        )

        if match:

            value = match.group(1)

            try:

                value = value.replace(
                    "Z",
                    "+00:00"
                )

                dt = datetime.fromisoformat(
                    value
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=JST
                    )
                else:
                    dt = dt.astimezone(JST)

                pub_date = dt

                break

            except Exception:
                pass

    # -----------------------------------------------------
    # visible date
    # -----------------------------------------------------

    if pub_date is None:

        match = re.search(
            r"(\d{4})年(\d{1,2})月(\d{1,2})日"
            r"(?:\s+(\d{1,2})時(\d{2})分)?",
            html
        )

        if match:

            try:

                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))

                hour = (
                    int(match.group(4))
                    if match.group(4)
                    else 0
                )

                minute = (
                    int(match.group(5))
                    if match.group(5)
                    else 0
                )

                pub_date = datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    tzinfo=JST
                )

            except Exception:
                pass

    # URLの日付を最後の保険として使用
    if pub_date is None:
        pub_date = date_from_url(url)

    if not title:
        return None

    return {
        "title": title,
        "link": url,
        "pubDate": (
            pub_date.strftime(
                "%a, %d %b %Y %H:%M:%S +0900"
            )
            if pub_date
            else ""
        ),
        "_datetime": (
            pub_date.isoformat()
            if pub_date
            else ""
        )
    }


# =========================================================
# メイン処理
# =========================================================

def main():

    print("========================================")
    print("EE Times Japan 直接取得開始")
    print("RSSは使用しません")
    print("========================================")

    candidate_urls = {}

    # -----------------------------------------------------
    # 一覧ページから記事URLを収集
    # -----------------------------------------------------

    for source_url in SOURCE_URLS:

        html = fetch_url(source_url)

        if not html:
            continue

        parser = LinkParser()

        try:
            parser.feed(html)
        except Exception as e:
            print(
                "HTML解析エラー:",
                repr(e)
            )
            continue

        for href, text in parser.links:

            url = normalize_url(href)

            if not is_article_url(url):
                continue

            # EE Times本体以外を除外
            if not url.startswith(
                "https://eetimes.itmedia.co.jp/ee/"
            ):
                continue

            candidate_urls[url] = True

    print()
    print(
        "記事URL候補数:",
        len(candidate_urls)
    )

    if not candidate_urls:

        print(
            "記事URLを1件も取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    # -----------------------------------------------------
    # URLの日付で新しい順に並べる
    # 同日なら元のURL順
    # -----------------------------------------------------

    urls = list(candidate_urls.keys())

    urls.sort(
        key=lambda url: (
            date_from_url(url)
            or datetime(
                2000,
                1,
                1,
                tzinfo=JST
            )
        ),
        reverse=True
    )

    # 記事ページを大量に叩きすぎないよう候補を絞る
    urls = urls[:MAX_ITEMS * 2]

    print(
        "記事ページ確認対象:",
        len(urls)
    )

    # -----------------------------------------------------
    # 記事ページから正式なタイトル・公開日時を取得
    # -----------------------------------------------------

    articles = []

    for i, url in enumerate(urls, 1):

        print()
        print(
            "----- 記事",
            i,
            "/",
            len(urls),
            "-----"
        )

        article = extract_article_info(url)

        if article:

            articles.append(article)

        # サーバーへの連続アクセスを少し間隔を空ける
        time.sleep(0.2)

    # -----------------------------------------------------
    # 記事取得結果チェック
    # -----------------------------------------------------

    if not articles:

        print()
        print(
            "記事を1件も取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    # -----------------------------------------------------
    # 日時順
    # -----------------------------------------------------

    articles.sort(
        key=lambda x: x.get(
            "_datetime",
            ""
        ),
        reverse=True
    )

    articles = articles[:MAX_ITEMS]

    # 内部用フィールドを削除
    for article in articles:
        article.pop(
            "_datetime",
            None
        )

    # -----------------------------------------------------
    # 結果表示
    # -----------------------------------------------------

    print()
    print("========================================")
    print("取得した記事一覧")
    print("========================================")

    for i, article in enumerate(
        articles,
        1
    ):

        print(
            i,
            "|",
            article["pubDate"],
            "|",
            article["title"]
        )

    print("========================================")
    print(
        "保存記事数:",
        len(articles)
    )

    # -----------------------------------------------------
    # JSON保存
    # -----------------------------------------------------

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

        # 正常に書けた場合だけ本番ファイルを置き換える
        os.replace(
            temp_file,
            OUTPUT
        )

        print()
        print("JSON更新完了")
        print(
            "保存記事数:",
            len(articles)
        )

    except Exception as e:

        print()
        print(
            "JSON保存エラー:",
            repr(e)
        )

        # tmpだけ削除
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass

        print(
            "既存JSONは変更しません。"
        )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()
