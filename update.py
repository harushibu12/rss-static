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
# HTML取得
# =========================================================

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


def fetch_html(url):

    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache"
        }
    )

    with urlopen(
        req,
        timeout=TIMEOUT
    ) as response:

        data = response.read()

    return decode_html(data)


# =========================================================
# Top Stories / 新着記事の範囲を探す
# =========================================================

def find_section(html, heading):

    # 見出し文字の位置
    pos = html.find(heading)

    if pos < 0:
        return None

    # 次の大きな見出しまでを範囲とする
    next_positions = []

    for next_heading in (
        "Top Stories",
        "新着記事",
        "Editor's",
        "ランキング",
        "おすすめ",
        "特集"
    ):

        if next_heading == heading:
            continue

        p = html.find(
            next_heading,
            pos + len(heading)
        )

        if p >= 0:
            next_positions.append(p)

    if next_positions:

        end = min(next_positions)

    else:

        # 次の見出しが見つからない場合は
        # 見出しから十分な範囲を見る
        end = min(
            len(html),
            pos + 30000
        )

    return html[pos:end]


# =========================================================
# URL抽出
# =========================================================

def extract_urls(section):

    if not section:
        return []

    urls = []

    # href="..."
    for match in re.finditer(
        r'href\s*=\s*["\']([^"\']+)["\']',
        section,
        re.IGNORECASE
    ):

        href = match.group(1)

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

        # EE Times内
        if not href.startswith(
            "https://eetimes.itmedia.co.jp/"
        ):
            continue

        # 記事らしいリンク
        if "/ee/" not in href:
            continue

        # カテゴリページなどを除外
        if "/subtop/" in href:
            continue

        if href in urls:
            continue

        urls.append(
            href.split("#")[0]
        )

    return urls


# =========================================================
# タイトル
# =========================================================

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
            re.I | re.S
        )

        if not m:
            continue

        title = m.group(1)

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
        ).strip()

        if title:
            return title

    return None


# =========================================================
# 公開日時
# =========================================================

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
            re.I | re.S
        )

        if not m:
            continue

        value = m.group(1).strip()

        # ISO
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

        # 日本語
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

        # /
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

        # -
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


# =========================================================
# 記事取得
# =========================================================

def fetch_article(url):

    try:

        html = fetch_html(url)

        title = extract_title(html)

        if not title:
            return None

        dt = extract_datetime(html)

        if dt is None:

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
    print("EE Times取得開始")
    print("================================")

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

    # -----------------------------------------------------
    # Top Stories
    # -----------------------------------------------------

    top_section = find_section(
        html,
        "Top Stories"
    )

    # -----------------------------------------------------
    # 新着記事
    # -----------------------------------------------------

    new_section = find_section(
        html,
        "新着記事"
    )

    print(
        "Top Stories:",
        top_section is not None
    )

    print(
        "新着記事:",
        new_section is not None
    )

    # -----------------------------------------------------
    # URL取得
    # -----------------------------------------------------

    urls = []

    if top_section:

        urls.extend(
            extract_urls(
                top_section
            )
        )

    if new_section:

        urls.extend(
            extract_urls(
                new_section
            )
        )

    # 重複削除
    unique_urls = []

    seen = set()

    for url in urls:

        if url in seen:
            continue

        seen.add(url)

        unique_urls.append(url)

    print(
        "対象記事URL:",
        len(unique_urls)
    )

    # -----------------------------------------------------
    # URLが取れなかった場合
    # -----------------------------------------------------

    if not unique_urls:

        print(
            "記事URLがありません。"
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
        unique_urls,
        1
    ):

        print(
            f"[{number}/{len(unique_urls)}]",
            url
        )

        item = fetch_article(
            url
        )

        if item:

            items.append(item)

        time.sleep(0.2)

    # -----------------------------------------------------
    # 新しい順
    # -----------------------------------------------------

    items.sort(
        key=lambda x: x["_dt"],
        reverse=True
    )

    items = items[:MAX_ITEMS]

    for item in items:

        del item["_dt"]

    # -----------------------------------------------------
    # 保存
    # -----------------------------------------------------

    if not items:

        print(
            "記事を取得できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

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

    print(
        "JSON更新完了"
    )


if __name__ == "__main__":

    main()
