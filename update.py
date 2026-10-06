import json
import re
import time
from datetime import datetime, timezone, timedelta
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
# Top Stories ～ FEATURES直前
# --------------------------------

def find_main_article_area(html):

    start = html.find(
        "Top Stories"
    )

    if start < 0:
        return None

    # Top Storiesより後ろにある
    # 最初のFEATURESを探す
    end = html.find(
        "FEATURES",
        start
    )

    if end < 0:

        # FEATURESが見つからない場合の保険
        end = min(
            len(html),
            start + 100000
        )

    return html[start:end]


# --------------------------------
# 記事URL取得
# --------------------------------

def extract_article_urls(section):

    if not section:
        return []

    urls = []

    # hrefを全部調べる
    for match in re.finditer(
        r'href\s*=\s*["\']([^"\']+)["\']',
        section,
        re.IGNORECASE
    ):

        href = match.group(1).strip()

        # 相対URL
        if href.startswith("/"):

            url = urljoin(
                BASE_URL,
                href
            )

        # //eetimes...
        elif href.startswith("//"):

            url = "https:" + href

        # 完全URL
        elif href.startswith("http"):

            url = href

        else:

            url = urljoin(
                BASE_URL,
                href
            )

        # EE Times記事だけ
        if not url.startswith(
            "https://eetimes.itmedia.co.jp/"
        ):
            continue

        if "/ee/articles/" not in url:
            continue

        # 広告・その他を除外
        if "/subtop/" in url:
            continue

        # クエリ・フラグメント除去
        url = url.split("?")[0]
        url = url.split("#")[0]

        if url not in urls:

            urls.append(url)

    return urls


# --------------------------------
# 記事タイトル取得
# --------------------------------

def extract_title(html):

    patterns = [

        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',

        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',

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

        title = m.group(1)

        title = re.sub(
            r"<[^>]+>",
            "",
            title
        )

        title = (
            title
            .replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
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
            flags=re.IGNORECASE
        ).strip()

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
# 記事取得
# --------------------------------

def fetch_article(url):

    try:

        html = fetch_html(
            url
        )

        title = extract_title(
            html
        )

        if not title:

            print(
                "  タイトル取得失敗"
            )

            return None

        dt = extract_datetime(
            html
        )

        if dt is None:

            # URLの日付を予備利用
            m = re.search(
                r"/articles/(\d{2})(\d{2})/(\d{2})/",
                url
            )

            if m:

                dt = datetime(
                    2000 + int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
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
            "pubDate": dt.strftime(
                "%a, %d %b %Y %H:%M:%S +0900"
            ),
            "_dt": dt
        }

    except Exception as e:

        print(
            "  記事取得失敗:",
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
    # トップページ
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
    # Top Stories～FEATURES直前
    # --------------------------------

    section = find_main_article_area(
        html
    )

    print(
        "Top Stories～新着記事範囲:",
        section is not None
    )

    if not section:

        print(
            "記事範囲を取得できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    # --------------------------------
    # 記事URL
    # --------------------------------

    urls = extract_article_urls(
        section
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
    # 各記事取得
    # --------------------------------

    items = []

    for number, url in enumerate(
        urls,
        1
    ):

        print(
            f"[{number}/{len(urls)}]",
            url
        )

        item = fetch_article(
            url
        )

        if item:

            print(
                "  見出し:",
                item["title"]
            )

            items.append(
                item
            )

        time.sleep(
            0.2
        )

    # --------------------------------
    # 新しい順
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

    # 内部データ削除
    for item in items:

        del item["_dt"]

    # --------------------------------
    # JSON保存
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
        "記事URL:",
        items[0]["link"]
    )

    print(
        "JSON更新完了"
    )


if __name__ == "__main__":
    main()
