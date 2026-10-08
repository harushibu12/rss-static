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


def decode_html(data):
    candidates = []

    for enc in ("utf-8", "cp932", "shift_jis", "euc_jp"):
        try:
            text = data.decode(enc)
            candidates.append((text.count("\ufffd"), text, enc))
        except Exception:
            pass

    if not candidates:
        return data.decode("utf-8", errors="replace")

    candidates.sort(key=lambda x: x[0])

    print("文字コード:", candidates[0][2])

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

    with urlopen(req, timeout=TIMEOUT) as response:
        data = response.read()

    return decode_html(data)


def extract_article_urls(html):
    urls = []
    seen = set()

    pattern = re.compile(
        r'href\s*=\s*["\']([^"\']+)["\']',
        re.IGNORECASE
    )

    for m in pattern.finditer(html):
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
            re.IGNORECASE | re.DOTALL
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
            r"\s*[|｜]\s*EE Times Japan.*$",
            "",
            title,
            flags=re.IGNORECASE
        ).strip()

        if title:
            return title

    return None


def extract_datetime(html):
    patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"publishDate"\s*:\s*"([^"]+)"',
        r'"published_time"\s*:\s*"([^"]+)"',
        r'(\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2})',
        r'(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})',
        r'(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})'
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

        for fmt in (
            "%Y年%m月%d日 %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M"
        ):
            try:
                return datetime.strptime(
                    value,
                    fmt
                ).replace(tzinfo=JST)
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

    yy, month, day = m.groups()

    try:
        return datetime(
            2000 + int(yy),
            int(month),
            int(day),
            tzinfo=JST
        )
    except Exception:
        return None


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
    print("EE Times RSS更新開始")

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

    urls = extract_article_urls(html)

    print(
        "対象記事URL:",
        len(urls)
    )

    if not urls:
        print(
            "記事URLを取得できませんでした。"
        )

        print(
            "既存JSONを維持します。"
        )

        return

    items = []

    for index, url in enumerate(urls, 1):
        print(
            f"[{index}/{len(urls)}]",
            url
        )

        item = fetch_article(url)

        if item:
            items.append(item)

        time.sleep(0.2)

    print(
        "取得成功記事:",
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

    unique = {}

    for item in items:
        unique[item["link"]] = item

    items = list(unique.values())

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

    temp_file = OUTPUT + ".tmp"

    try:
        with open(
            temp_file,
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
            temp_file,
            OUTPUT
        )

    except Exception as e:
        print(
            "JSON保存失敗:",
            str(e)
        )

        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass

        print(
            "既存JSONを維持します。"
        )

        return

    print(
        "取得完了:",
        len(output),
        "件"
    )

    if output:
        print(
            "最新記事:",
            output[0]["pubDate"]
        )

        print(
            output[0]["title"]
        )

        print(
            output[0]["link"]
        )


if __name__ == "__main__":
    main()
