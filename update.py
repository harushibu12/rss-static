import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://eetimes.itmedia.co.jp"
OUTPUT = "rss-data.json"

MAX_ITEMS = 50
TIMEOUT = 30

JST = timezone(timedelta(hours=9))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


# --------------------------------------------------
# EE Timesの記事URL
# 現在の形式：
# /ee/articles/2610/07/news026.html
# --------------------------------------------------

ARTICLE_PATTERN = re.compile(
    r"/ee/(?:articles|spv)/(\d{2})(\d{2})/(\d{2})/"
)


# --------------------------------------------------
# 文字コード判定・デコード
# --------------------------------------------------

def detect_charset(data, content_type=""):
    m = re.search(
        r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)",
        content_type or "",
        re.IGNORECASE
    )

    if m:
        return m.group(1)

    head = data[:5000].decode("ascii", errors="ignore")

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

    detected = detect_charset(data, content_type)

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
        enc_lower = enc.lower()

        if enc_lower in seen:
            continue

        seen.add(enc_lower)

        try:
            text = data.decode(enc)
            candidates.append(
                (text.count("\ufffd"), text, enc)
            )
        except Exception:
            pass

    if not candidates:
        return data.decode("utf-8", errors="replace")

    candidates.sort(key=lambda x: x[0])

    text = candidates[0][1]
    used_encoding = candidates[0][2]

    print("文字コード:", used_encoding)

    return text


# --------------------------------------------------
# HTTP取得
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
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache"
        }
    )

    with urlopen(req, timeout=TIMEOUT) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")

    return decode_html(data, content_type)


# --------------------------------------------------
# トップページ解析
# --------------------------------------------------

class SectionParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.current_heading = None
        self.heading_buffer = ""

        self.active_section = None

        self.top_found = False
        self.new_found = False

        self.links = []

        self.current_href = None

    def handle_starttag(self, tag, attrs):

        tag = tag.lower()
        attrs = dict(attrs)

        # 見出し
        if tag in ("h1", "h2", "h3"):
            self.current_heading = tag
            self.heading_buffer = ""
            return

        # リンク
        if tag == "a":

            href = attrs.get("href")

            if href:
                self.current_href = href

    def handle_endtag(self, tag):

        tag = tag.lower()

        # 見出し終了
        if self.current_heading == tag:

            text = re.sub(
                r"\s+",
                " ",
                self.heading_buffer
            ).strip()

            if text == "Top Stories":

                self.active_section = "top"
                self.top_found = True

            elif text == "新着記事":

                if not self.new_found:
                    self.active_section = "new"
                    self.new_found = True
                else:
                    self.active_section = None

            else:

                if self.active_section in ("top", "new"):
                    self.active_section = None

            self.current_heading = None
            self.heading_buffer = ""

        # リンク終了
        if tag == "a":

            if (
                self.current_href
                and self.active_section in ("top", "new")
            ):
                self.links.append(
                    (
                        self.current_href,
                        self.active_section
                    )
                )

            self.current_href = None

    def handle_data(self, data):

        if self.current_heading:
            self.heading_buffer += data


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
        url = BASE_URL.rstrip("/") + url

    elif not url.startswith("http"):
        return None

    if not ARTICLE_PATTERN.search(url):
        return None

    return url.split("#")[0]


# --------------------------------------------------
# URLの日付を取得
# --------------------------------------------------

def fallback_date_from_url(url):

    m = ARTICLE_PATTERN.search(url)

    if not m:
        return None

    yy, month, day = m.groups()

    year = 2000 + int(yy)

    try:
        return datetime(
            year,
            int(month),
            int(day),
            0,
            0,
            0,
            tzinfo=JST
        )

    except Exception:
        return None


# --------------------------------------------------
# 記事公開日時取得
# --------------------------------------------------

def extract_published_datetime(html):

    patterns = [

        r'<meta[^>]+property=["\']article:published_time["\']'
        r'[^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\']'
        r'[^>]+property=["\']article:published_time["\']',

        r'"datePublished"\s*:\s*"([^"]+)"',

        r"'datePublished'\s*:\s*'([^']+)'",

        r'"publishDate"\s*:\s*"([^"]+)"',

        r"'publishDate'\s*:\s*'([^']+)'",

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

        value = m.group(1).strip()

        value = value.replace(
            "Z",
            "+00:00"
        )

        try:

            dt = datetime.fromisoformat(value)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)

            return dt.astimezone(JST)

        except Exception:
            pass

    # 日本語表記
    patterns_jp = [

        r"(\d{4})年(\d{1,2})月(\d{1,2})日"
        r"\s*(\d{1,2}):(\d{2})",

        r"(\d{4})/(\d{1,2})/(\d{1,2})"
        r"\s*(\d{1,2}):(\d{2})",

        r"(\d{4})-(\d{1,2})-(\d{1,2})"
        r"\s*(\d{1,2}):(\d{2})",
    ]

    for pattern in patterns_jp:

        m = re.search(
            pattern,
            html
        )

        if not m:
            continue

        try:

            year, month, day, hour, minute = map(
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

        r'<meta[^>]+property=["\']og:title["\']'
        r'[^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\']'
        r'[^>]+property=["\']og:title["\']',

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

        if title:

            title = re.sub(
                r"\s*[|｜]\s*EE Times Japan.*$",
                "",
                title,
                flags=re.IGNORECASE
            ).strip()

            return title

    return ""


# --------------------------------------------------
# 記事1件取得
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

        published = extract_published_datetime(html)

        if published is None:

            published = fallback_date_from_url(url)

            if published is None:

                print(
                    "公開日時・URL日付とも取得失敗:",
                    url
                )

                return None

            print(
                "公開日時なし → URL日付:",
                title
            )

        else:

            print(
                "公開日時取得:",
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
            "_datetime": published.isoformat()
        }

    except Exception as e:

        print(
            "記事取得失敗:",
            url,
            str(e)
        )

        return None


# --------------------------------------------------
# 既存JSON
# --------------------------------------------------

def load_existing():

    if not os.path.exists(OUTPUT):
        return None

    try:

        with open(
            OUTPUT,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return None


# --------------------------------------------------
# メイン
# --------------------------------------------------

def main():

    print("EE Times取得開始")

    # ----------------------------------------------
    # トップページ取得
    # ----------------------------------------------

    try:

        html = fetch_html(BASE_URL)

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

    # ----------------------------------------------
    # HTML解析
    # ----------------------------------------------

    parser = SectionParser()

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
        "Top Stories:",
        parser.top_found
    )

    print(
        "新着記事:",
        parser.new_found
    )

    # ----------------------------------------------
    # セクション確認
    # ----------------------------------------------

    if not parser.top_found or not parser.new_found:

        print(
            "必要なセクションを確認できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # ----------------------------------------------
    # URL抽出
    # ----------------------------------------------

    urls = []

    seen = set()

    for href, section in parser.links:

        url = normalize_url(href)

        if not url:
            continue

        if url in seen:
            continue

        seen.add(url)

        urls.append(
            (url, section)
        )

    print(
        "対象記事URL:",
        len(urls)
    )

    for url, section in urls:

        print(
            section,
            url
        )

    if not urls:

        print(
            "記事URLがありません。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # ----------------------------------------------
    # 各記事取得
    # ----------------------------------------------

    articles = []

    for index, (url, section) in enumerate(
        urls,
        1
    ):

        print(
            f"[{index}/{len(urls)}]",
            url
        )

        article = fetch_article(url)

        if article:

            article["_section"] = section

            articles.append(article)

        time.sleep(0.2)

    # ----------------------------------------------
    # 1件も取得できなかった場合
    # ----------------------------------------------

    if not articles:

        print(
            "記事を1件も取得できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # ----------------------------------------------
    # 重複削除
    # ----------------------------------------------

    unique = {}

    for article in articles:

        unique[
            article["link"]
        ] = article

    articles = list(
        unique.values()
    )

    # ----------------------------------------------
    # 新しい順
    # ----------------------------------------------

    articles.sort(
        key=lambda x: x.get(
            "_datetime",
            ""
        ),
        reverse=True
    )

    articles = articles[
        :MAX_ITEMS
    ]

    # ----------------------------------------------
    # RSS用JSONに整形
    # ----------------------------------------------

    output_items = []

    for article in articles:

        output_items.append({
            "title": article["title"],
            "link": article["link"],
            "pubDate": article["pubDate"]
        })

    # ----------------------------------------------
    # 一時ファイルに保存
    # ----------------------------------------------

    temp_file = OUTPUT + ".tmp"

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

        # 保存成功後に本体を置き換え
        os.replace(
            temp_file,
            OUTPUT
        )

    except Exception as e:

        print(
            "JSON保存失敗:",
            str(e)
        )

        if os.path.exists(temp_file):

            try:
                os.remove(temp_file)
            except Exception:
                pass

        print(
            "既存JSONを維持します。"
        )

        return

    # ----------------------------------------------
    # 完了
    # ----------------------------------------------

    print()

    print(
        "取得完了:",
        len(output_items),
        "件"
    )

    print(
        "最新記事:"
    )

    if output_items:

        print(
            output_items[0]["pubDate"],
            output_items[0]["title"]
        )

        print(
            output_items[0]["link"]
        )


if __name__ == "__main__":
    main()
