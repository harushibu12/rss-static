import json
import os
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


def fetch_html(url):
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9",
            "Cache-Control": "no-cache"
        }
    )

    with urlopen(req, timeout=TIMEOUT) as response:
        data = response.read()

    # EE TimesはUTF-8
    return data.decode("utf-8", errors="replace")


def extract_article_urls(html):
    urls = []
    seen = set()

    for m in re.finditer(
        r'href\s*=\s*["\']([^"\']+)["\']',
        html,
        re.IGNORECASE
    ):
        href = m.group(1).strip()

        if href.startswith("//"):
            url = "https:" + href
        elif href.startswith("/"):
            url = urljoin(BASE_URL, href)
        elif href.startswith("http"):
            url = href
        else:
            url = urljoin(BASE_URL, href)

        if not url.startswith(
            "https://eetimes.itmedia.co.jp/"
        ):
            continue

        if "/ee/articles/" not in url:
            continue

        if "/subtop/" in url:
            continue

        url = url.split("?")[0].split("#")[0]

        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def extract_meta_content(html, property_name):
    patterns = [
        r'<meta[^>]+property=["\']'
        + re.escape(property_name)
        + r'["\'][^>]+content=["\']([^"\']*)["\']',

        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']'
        + re.escape(property_name)
        + r'["\']'
    ]

    for pattern in patterns:
        m = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        if m:
            return m.group(1).strip()

    return None


def clean_title(title):
    if not title:
        return None

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
        r"\s*[|｜]\s*EE Times Japan.*$",
        "",
        title,
        flags=re.IGNORECASE
    ).strip()

    return title if title else None


def extract_title(html):
    # まず記事の正式タイトル
    title = extract_meta_content(
        html,
        "og:title"
    )

    title = clean_title(title)

    if title:
        return title

    # 念のため<title>
    m = re.search(
        r"<title[^>]*>(.*?)</title>",
        html,
        re.IGNORECASE | re.DOTALL
    )

    if m:
        title = re.sub(
            r"<[^>]+>",
            "",
            m.group(1)
        )

        title = clean_title(title)

        if title:
            return title

    return None


def extract_datetime(html):
    patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"publishDate"\s*:\s*"([^"]+)"'
    ]

    for pattern in patterns:
        m = re.search(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        if not m:
            continue

        value = m.group(1).strip()

        try:
            dt = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)

            return dt.astimezone(JST)

        except Exception:
            pass

    return None


def extract_url_datetime(url):
    m = re.search(
        r"/articles/(\d{2})(\d{2})/(\d{2})/",
        url
    )

    if not m:
        return None

    try:
        return datetime(
            2000 + int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            tzinfo=JST
        )
    except Exception:
        return None


def fetch_article(url):
    try:
        html = fetch_html(url)

        title = extract_title(html)

        if not title:
            print("タイトル取得失敗:", url)
            return None

        dt = extract_datetime(html)

        if dt is None:
            dt = extract_url_datetime(url)

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


def main():
    print("EE Times取得開始")

    try:
        html = fetch_html(BASE_URL)

        print(
            "トップページ取得:",
            len(html),
            "文字"
        )

    except Exception as e:
        print(
            "トップページ取得失敗:",
            str(e)
        )
        print("既存JSONを維持します。")
        return

    urls = extract_article_urls(html)

    print(
        "記事URL候補:",
        len(urls)
    )

    if not urls:
        print("記事URLがありません。")
        print("既存JSONを維持します。")
        return

    items = []

    for i, url in enumerate(urls, 1):
        print(
            f"{i}/{len(urls)}",
            url
        )

        item = fetch_article(url)

        if item:
            items.append(item)

        time.sleep(0.2)

    if not items:
        print("記事を取得できませんでした。")
        print("既存JSONを維持します。")
        return

    # URL重複を除去
    unique = {}

    for item in items:
        unique[item["link"]] = item

    items = list(unique.values())

    # 新しい順
    items.sort(
        key=lambda x: x["_dt"],
        reverse=True
    )

    items = items[:MAX_ITEMS]

    output = []

    for item in items:
        output.append({
            "title": item["title"],
            "link": item["link"],
            "pubDate": item["pubDate"]
        })

    # 一時ファイルに書いてから置換
    temp = OUTPUT + ".tmp"

    try:
        with open(
            temp,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                output,
                f,
                ensure_ascii=False,
                indent=2
            )
            f.write("\n")

        os.replace(
            temp,
            OUTPUT
        )

    except Exception as e:
        print(
            "JSON保存失敗:",
            str(e)
        )

        if os.path.exists(temp):
            os.remove(temp)

        print("既存JSONを維持します。")
        return

    print(
        "RSS更新完了:",
        len(output),
        "件"
    )

    print(
        "最新:",
        output[0]["title"]
    )

    print(
        output[0]["link"]
    )


if __name__ == "__main__":
    main()
