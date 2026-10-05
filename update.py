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


ARTICLE_PATTERN = re.compile(
    r"/ee/(?:articles|spv)/(\d{4})/(\d{2})/(\d{2})/"
)


# --------------------------------------------------
# 文字コード判定
# --------------------------------------------------

def decode_html(data):
    candidates = []

    # HTTPヘッダー等で判定できる可能性のあるもの
    for enc in [
        "utf-8",
        "cp932",
        "shift_jis",
        "euc_jp",
    ]:
        try:
            text = data.decode(enc)
            candidates.append((text.count("\ufffd"), text))
        except Exception:
            pass

    if not candidates:
        return data.decode("utf-8", errors="replace")

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


# --------------------------------------------------
# Top Stories / 新着記事 のリンク取得
# --------------------------------------------------

class SectionParser(HTMLParser):

    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.current_tag = None
        self.text_buffer = ""

        self.active_section = None

        self.top_found = False
        self.new_found = False

        self.links = []

        self.current_href = None
        self.current_link_text = ""

    def handle_starttag(self, tag, attrs):

        attrs = dict(attrs)

        # 見出し
        if tag.lower() in ("h1", "h2", "h3"):

            self.current_tag = tag.lower()
            self.text_buffer = ""

            return

        # リンク
        if tag.lower() == "a":

            href = attrs.get("href")

            if href:
                self.current_href = href
                self.current_link_text = ""

    def handle_endtag(self, tag):

        tag = tag.lower()

        # 見出し終了
        if self.current_tag == tag:

            text = re.sub(
                r"\s+",
                " ",
                self.text_buffer
            ).strip()

            # Top Stories
            if text == "Top Stories":

                self.active_section = "top"
                self.top_found = True

            # 新着記事
            elif text == "新着記事":

                # 最初の新着記事だけ採用
                if not self.new_found:

                    self.active_section = "new"
                    self.new_found = True

                else:

                    self.active_section = None

            # 別の見出しに到達
            else:

                if self.active_section in ("top", "new"):
                    self.active_section = None

            self.current_tag = None
            self.text_buffer = ""

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
            self.current_link_text = ""

    def handle_data(self, data):

        if self.current_tag:
            self.text_buffer += data


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

    # EE Times記事URLだけ
    if not ARTICLE_PATTERN.search(url):
        return None

    return url.split("#")[0]


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
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        }
    )

    with urlopen(req, timeout=TIMEOUT) as response:

        data = response.read()

    return decode_html(data)


# --------------------------------------------------
# 日付
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
# 公開日時を記事HTMLから取得
# --------------------------------------------------

def extract_published_datetime(html):

    patterns = [

        # Open Graph
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',

        # datePublished
        r'"datePublished"\s*:\s*"([^"]+)"',
        r"'datePublished'\s*:\s*'([^']+)'",

        # publish date
        r'"publishDate"\s*:\s*"([^"]+)"',
        r"'publishDate'\s*:\s*'([^']+)'",

        # published
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
            .replace("Z", "+00:00")
        )

        try:

            dt = datetime.fromisoformat(value)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)

            return dt.astimezone(JST)

        except Exception:
            pass

    # --------------------------------------------------
    # 日本語の公開日時表記
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

    # og:title
    patterns = [

        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',

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

            # サイト名部分を除去
            title = re.sub(
                r"\s*[|｜]\s*EE Times Japan.*$",
                "",
                title,
                flags=re.IGNORECASE
            ).strip()

            return title

    return ""


# --------------------------------------------------
# 記事情報取得
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

        # 実際の公開日時が取れなければURL日付
        if published is None:

            published = fallback_date_from_url(url)

            if published is None:
                return None

            print(
                "公開日時なし → URL日付:",
                title
            )

        else:

            print(
                "公開日時取得:",
                published.strftime("%Y-%m-%d %H:%M"),
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
# 既存JSON読み込み
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
    # トップページ
    # ----------------------------------------------

    try:

        html = fetch_html(BASE_URL)

        print(
            "トップページ取得成功:",
            len(html),
            "bytes相当"
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

    # ----------------------------------------------
    # セクション解析
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

    if not parser.top_found or not parser.new_found:

        print(
            "必要なセクションを確認できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # ----------------------------------------------
    # URL整理
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
            (
                url,
                section
            )
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
    # 記事取得
    # ----------------------------------------------

    articles = []

    for index, (url, section) in enumerate(urls):

        print(
            f"[{index + 1}/{len(urls)}]",
            url
        )

        article = fetch_article(url)

        if article:

            article["_section"] = section

            articles.append(article)

        # アクセス間隔
        time.sleep(0.2)

    # ----------------------------------------------
    # 取得失敗時
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
    # 重複除去
    # ----------------------------------------------

    unique = {}

    for article in articles:

        unique[article["link"]] = article

    articles = list(
        unique.values()
    )

    # ----------------------------------------------
    # 実際の公開日時順
    # ----------------------------------------------

    articles.sort(
        key=lambda x: x.get(
            "_datetime",
            ""
        ),
        reverse=True
    )

    # ----------------------------------------------
    # 最大件数
    # ----------------------------------------------

    articles = articles[:MAX_ITEMS]

    # ----------------------------------------------
    # 不要な内部項目を削除
    # ----------------------------------------------

    output_items = []

    for article in articles:

        output_items.append(
            {
                "title": article["title"],
                "link": article["link"],
                "pubDate": article["pubDate"],
            }
        )

    # ----------------------------------------------
    # 保存
    # ----------------------------------------------

    temp_file = OUTPUT + ".tmp"

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

    # ----------------------------------------------
    # 結果表示
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
