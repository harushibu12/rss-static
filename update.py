import json
import re
import time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin
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


# =========================================================
# EE Timesの記事URL
# 例：
# https://eetimes.itmedia.co.jp/ee/spv/2610/05/news046.html
# =========================================================

ARTICLE_PATTERN = re.compile(
    r"/ee/spv/\d{4}/\d{2}/\d{2}/[^?#\"']+\.html",
    re.IGNORECASE
)


# =========================================================
# HTMLリンク取得
# =========================================================

class LinkParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() != "a":
            return

        attrs = dict(attrs)

        href = attrs.get("href")

        if href:
            self.links.append(href)


# =========================================================
# 文字コード判定
# =========================================================

def decode_html(data):

    candidates = []

    for encoding in (
        "utf-8",
        "cp932",
        "shift_jis",
        "euc_jp"
    ):

        try:

            text = data.decode(encoding)

            bad_count = text.count("\ufffd")

            candidates.append(
                (bad_count, text)
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


# =========================================================
# HTML取得
# =========================================================

def fetch_html(url):

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }
    )

    with urlopen(
        request,
        timeout=TIMEOUT
    ) as response:

        data = response.read()

    return decode_html(data)


# =========================================================
# URLを記事URLに変換
# =========================================================

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

    # EE Times以外は除外
    if not href.startswith(
        "https://eetimes.itmedia.co.jp/"
    ):
        return None

    # 記事URL以外は除外
    if not ARTICLE_PATTERN.search(href):
        return None

    # #以降を削除
    href = href.split("#")[0]

    return href


# =========================================================
# URLから日付を取得
# =========================================================

def fallback_date_from_url(url):

    # /ee/spv/2610/05/news046.html

    match = re.search(
        r"/ee/spv/(\d{2})(\d{2})/(\d{2})/",
        url
    )

    if not match:
        return None

    year = 2000 + int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))

    try:

        return datetime(
            year,
            month,
            day,
            0,
            0,
            tzinfo=JST
        )

    except ValueError:

        return None


# =========================================================
# 公開日時取得
# =========================================================

def extract_published_datetime(html):

    patterns = [

        # article:published_time
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',

        # og:article:published_time
        r'<meta[^>]+property=["\']og:article:published_time["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:article:published_time["\']',

        # JSON-LD
        r'"datePublished"\s*:\s*"([^"]+)"',

        r'"publishDate"\s*:\s*"([^"]+)"',

        r'"published_time"\s*:\s*"([^"]+)"',

        # 日本語
        r'(\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})',

        # YYYY/MM/DD HH:MM
        r'(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})',

        # YYYY-MM-DD HH:MM
        r'(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})',
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        if not match:
            continue

        value = match.group(1).strip()

        # ---------------------------------------------
        # ISO形式
        # ---------------------------------------------

        try:

            iso_value = value.replace(
                "Z",
                "+00:00"
            )

            dt = datetime.fromisoformat(
                iso_value
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=JST
                )

            return dt.astimezone(JST)

        except Exception:
            pass

        # ---------------------------------------------
        # YYYY年MM月DD日 HH:MM
        # ---------------------------------------------

        match2 = re.match(
            r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})",
            value
        )

        if match2:

            try:

                return datetime(
                    int(match2.group(1)),
                    int(match2.group(2)),
                    int(match2.group(3)),
                    int(match2.group(4)),
                    int(match2.group(5)),
                    tzinfo=JST
                )

            except ValueError:
                pass

        # ---------------------------------------------
        # YYYY/MM/DD HH:MM
        # ---------------------------------------------

        match2 = re.match(
            r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})",
            value
        )

        if match2:

            try:

                return datetime(
                    int(match2.group(1)),
                    int(match2.group(2)),
                    int(match2.group(3)),
                    int(match2.group(4)),
                    int(match2.group(5)),
                    tzinfo=JST
                )

            except ValueError:
                pass

        # ---------------------------------------------
        # YYYY-MM-DD HH:MM
        # ---------------------------------------------

        match2 = re.match(
            r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})",
            value
        )

        if match2:

            try:

                return datetime(
                    int(match2.group(1)),
                    int(match2.group(2)),
                    int(match2.group(3)),
                    int(match2.group(4)),
                    int(match2.group(5)),
                    tzinfo=JST
                )

            except ValueError:
                pass

    return None


# =========================================================
# タイトル取得
# =========================================================

def extract_title(html):

    patterns = [

        # og:title
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',

        # title
        r"<title[^>]*>(.*?)</title>",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        if not match:
            continue

        title = match.group(1)

        title = re.sub(
            r"\s+",
            " ",
            title
        ).strip()

        title = re.sub(
            r"\s*\|\s*EE Times Japan\s*$",
            "",
            title,
            flags=re.IGNORECASE
        ).strip()

        if title:
            return title

    return None


# =========================================================
# 1記事取得
# =========================================================

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

        published = extract_published_datetime(
            html
        )

        # 公開日時が取れなければURLの日付
        if published is None:

            published = fallback_date_from_url(
                url
            )

        if published is None:

            published = datetime(
                1970,
                1,
                1,
                tzinfo=JST
            )

        return {
            "title": title,
            "link": url,
            "pubDate": published.strftime(
                "%a, %d %b %Y %H:%M:%S +0900"
            ),
            "_datetime": published.isoformat()
        }

    except Exception as e:

        print(
            "記事取得失敗:",
            url,
            str(e)
        )

        return None


# =========================================================
# メイン
# =========================================================

def main():

    print("================================")
    print("EE Times RSS更新開始")
    print("================================")

    # -----------------------------------------------------
    # トップページ
    # -----------------------------------------------------

    try:

        html = fetch_html(
            BASE_URL
        )

        print(
            "トップページ取得成功:",
            len(html),
            "bytes"
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

    # -----------------------------------------------------
    # リンク抽出
    # -----------------------------------------------------

    parser = LinkParser()

    parser.feed(html)

    print(
        "トップページ内リンク数:",
        len(parser.links)
    )

    # -----------------------------------------------------
    # EE Times記事URLだけ抽出
    # -----------------------------------------------------

    article_urls = []

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

        article_urls.append(url)

    print(
        "EE Times記事URL:",
        len(article_urls)
    )

    # -----------------------------------------------------
    # URLが0件ならJSONを壊さない
    # -----------------------------------------------------

    if not article_urls:

        print(
            "記事URLが1件もありません。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # -----------------------------------------------------
    # 記事取得
    # -----------------------------------------------------

    items = []

    for number, url in enumerate(
        article_urls,
        1
    ):

        print(
            f"[{number}/{len(article_urls)}]",
            url
        )

        item = fetch_article(
            url
        )

        if item:

            items.append(item)

        # サーバーに負荷をかけない
        time.sleep(0.2)

    # -----------------------------------------------------
    # URL重複排除
    # -----------------------------------------------------

    unique = {}

    for item in items:

        unique[item["link"]] = item

    items = list(
        unique.values()
    )

    # -----------------------------------------------------
    # 新しい順
    # -----------------------------------------------------

    items.sort(
        key=lambda item: item["_datetime"],
        reverse=True
    )

    # 最大50件
    items = items[:MAX_ITEMS]

    # 内部用日時を削除
    for item in items:

        del item["_datetime"]

    # -----------------------------------------------------
    # 取得結果
    # -----------------------------------------------------

    print("--------------------------------")

    print(
        "取得成功:",
        len(items),
        "件"
    )

    if not items:

        print(
            "記事を1件も取得できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    print(
        "最新記事:"
    )

    print(
        items[0]["pubDate"]
    )

    print(
        items[0]["title"]
    )

    print(
        items[0]["link"]
    )

    # -----------------------------------------------------
    # JSON保存
    # -----------------------------------------------------

    try:

        with open(
            OUTPUT,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                items,
                file,
                ensure_ascii=False,
                indent=2
            )

        print(
            "JSON更新完了:",
            OUTPUT
        )

    except Exception as e:

        print(
            "JSON保存失敗:",
            str(e)
        )

        print(
            "既存JSONを維持します。"
        )


if __name__ == "__main__":

    main()
