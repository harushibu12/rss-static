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

# EE Timesトップページのみ取得
# Top Stories + 新着記事をここから取得する
SOURCE_URL = "https://eetimes.itmedia.co.jp/"

OUTPUT = "rss-data.json"

# FC2へ表示する最大記事数
MAX_ITEMS = 50

TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

JST = timezone(timedelta(hours=9))


# =========================================================
# EE Times記事URL
# =========================================================

ARTICLE_PATTERN = re.compile(
    r"/ee/"
    r"(?:articles|spv)/"
    r"(\d{2})(\d{2})/"
    r"(\d{2})/"
)


# =========================================================
# HTMLリンク解析
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
            )

            text = re.sub(
                r"\s+",
                " ",
                text
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
# URL正規化
# =========================================================

def normalize_url(url):

    if not url:
        return None

    url = url.strip()

    if url.startswith("//"):

        url = "https:" + url

    elif url.startswith("/"):

        url = urljoin(
            BASE_URL,
            url
        )

    elif not url.startswith("http"):

        url = urljoin(
            BASE_URL + "/",
            url
        )

    # #以降を削除
    url = url.split("#")[0]

    return url


# =========================================================
# EE Timesの記事URLか判定
# =========================================================

def is_article_url(url):

    if not url:
        return False

    if not url.startswith(
        BASE_URL + "/ee/"
    ):
        return False

    return (
        ARTICLE_PATTERN.search(url)
        is not None
    )


# =========================================================
# URLから日付を取得
# =========================================================

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
            tzinfo=JST
        )

    except ValueError:

        return None


# =========================================================
# Webページ取得
# =========================================================

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
                "application/xhtml+xml"
            )
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

                html = data.decode(
                    charset
                )

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

        print(
            "タイムアウト"
        )

    except Exception as e:

        print(
            "予期しないエラー:",
            repr(e)
        )

    return None


# =========================================================
# 記事ページから情報取得
# =========================================================

def extract_article_info(
    url,
    fallback_title=""
):

    html = fetch_url(url)

    if not html:

        # ページ取得に失敗しても
        # URLから日付を取得できれば候補として残す

        fallback_date = date_from_url(
            url
        )

        if fallback_title:

            return {
                "title": fallback_title,
                "link": url,
                "pubDate": (
                    fallback_date.strftime(
                        "%a, %d %b %Y %H:%M:%S +0900"
                    )
                    if fallback_date
                    else ""
                ),
                "_datetime": (
                    fallback_date.isoformat()
                    if fallback_date
                    else ""
                )
            }

        return None

    # =====================================================
    # タイトル
    # =====================================================

    title = None

    # og:title
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

    # =====================================================
    # 公開日時
    # =====================================================

    pub_date = None

    # JSON-LD
    date_patterns = [

        r'"datePublished"\s*:\s*"([^"]+)"',

        r'"dateCreated"\s*:\s*"([^"]+)"'
    ]

    for pattern in date_patterns:

        match = re.search(
            pattern,
            html,
            re.I
        )

        if not match:
            continue

        value = match.group(1).strip()

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

                dt = dt.astimezone(
                    JST
                )

            pub_date = dt

            break

        except Exception:

            pass

    # =====================================================
    # ページ内の日本語日時
    # =====================================================

    if pub_date is None:

        match = re.search(
            r"(\d{4})年"
            r"(\d{1,2})月"
            r"(\d{1,2})日"
            r"(?:\s+(\d{1,2})時"
            r"(\d{2})分)?",
            html
        )

        if match:

            try:

                year = int(
                    match.group(1)
                )

                month = int(
                    match.group(2)
                )

                day = int(
                    match.group(3)
                )

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

    # =====================================================
    # 最終手段：URLの日付
    # =====================================================

    if pub_date is None:

        pub_date = date_from_url(
            url
        )

    # 一覧ページで取得したタイトルを保険として使用
    if not title:

        title = fallback_title

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

    print(
        "========================================"
    )

    print(
        "EE Times Japan 直接取得"
    )

    print(
        "RSSは使用しません"
    )

    print(
        "取得元：トップページ"
    )

    print(
        "Top Stories + 新着記事"
    )

    print(
        "========================================"
    )

    # =====================================================
    # トップページ取得
    # =====================================================

    html = fetch_url(
        SOURCE_URL
    )

    if not html:

        print()
        print(
            "トップページを取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    # =====================================================
    # リンク解析
    # =====================================================

    parser = LinkParser()

    try:

        parser.feed(
            html
        )

    except Exception as e:

        print()
        print(
            "HTML解析エラー:",
            repr(e)
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    # =====================================================
    # 記事URL収集
    # =====================================================

    candidate_articles = {}

    for href, text in parser.links:

        url = normalize_url(
            href
        )

        if not is_article_url(
            url
        ):
            continue

        # 同じ記事がTop Storiesと新着記事の
        # 両方にあっても1件だけにする
        if url not in candidate_articles:

            candidate_articles[url] = text

        else:

            # より長いタイトルが取れた方を採用
            old_text = candidate_articles[url]

            if len(text) > len(old_text):

                candidate_articles[url] = text

    print()
    print(
        "========================================"
    )

    print(
        "トップページから取得した記事URL:",
        len(candidate_articles)
    )

    print(
        "========================================"
    )

    # =====================================================
    # 記事URLが取れなかった場合
    # =====================================================

    if not candidate_articles:

        print(
            "記事URLを取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    # =====================================================
    # URLの日付で新しい順
    # =====================================================

    candidates = list(
        candidate_articles.items()
    )

    candidates.sort(
        key=lambda item: (
            date_from_url(
                item[0]
            )
            or datetime(
                2000,
                1,
                1,
                tzinfo=JST
            )
        ),
        reverse=True
    )

    print()
    print(
        "記事ページ確認数:",
        len(candidates)
    )

    # =====================================================
    # 各記事ページを確認
    # =====================================================

    articles = []

    for index, (
        url,
        listing_title
    ) in enumerate(
        candidates,
        1
    ):

        print()
        print(
            "----------------------------------------"
        )

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

            articles.append(
                article
            )

        # 連続アクセスを少し抑える
        time.sleep(
            0.2
        )

    # =====================================================
    # 取得0件なら既存JSONを維持
    # =====================================================

    if not articles:

        print()
        print(
            "記事を1件も取得できませんでした。"
        )

        print(
            "既存JSONは変更しません。"
        )

        return

    # =====================================================
    # URL重複排除
    # =====================================================

    unique_articles = {}

    for article in articles:

        unique_articles[
            article["link"]
        ] = article

    articles = list(
        unique_articles.values()
    )

    # =====================================================
    # 公開日時順
    # =====================================================

    articles.sort(
        key=lambda article: (
            article.get(
                "_datetime",
                ""
            )
        ),
        reverse=True
    )

    # =====================================================
    # 最新50件
    # =====================================================

    articles = articles[
        :MAX_ITEMS
    ]

    # =====================================================
    # 内部用フィールド削除
    # =====================================================

    for article in articles:

        article.pop(
            "_datetime",
            None
        )

    # =====================================================
    # 最終結果表示
    # =====================================================

    print()
    print(
        "========================================"
    )

    print(
        "最終保存記事一覧"
    )

    print(
        "========================================"
    )

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
        "========================================"
    )

    print(
        "保存記事数:",
        len(articles)
    )

    # =====================================================
    # JSONを安全に保存
    # =====================================================

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

            f.write(
                "\n"
            )

        # 正常に書き込めた場合のみ本番JSONを置換
        os.replace(
            temp_file,
            OUTPUT
        )

        print()
        print(
            "JSON更新完了"
        )

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

        # tmpファイルを削除
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


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":

    main()
