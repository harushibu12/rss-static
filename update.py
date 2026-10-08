import json
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://eetimes.itmedia.co.jp/"
OUTPUT = "rss-data.json"
MAX_ITEMS = 20
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
        content_type = response.headers.get(
            "Content-Type",
            ""
        )

    # まずHTTPヘッダーのcharsetを確認
    m = re.search(
        r"charset\s*=\s*([A-Za-z0-9._-]+)",
        content_type,
        re.IGNORECASE
    )

    if m:
        encoding = m.group(1)

        try:
            html = data.decode(
                encoding,
                errors="strict"
            )
            print("文字コード:", encoding)
            return html
        except (UnicodeDecodeError, LookupError):
            pass

    # HTML先頭のcharsetを確認
    head = data[:10000].decode(
        "ascii",
        errors="ignore"
    )

    m = re.search(
        r"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)",
        head,
        re.IGNORECASE
    )

    if m:
        encoding = m.group(1)

        try:
            html = data.decode(
                encoding,
                errors="strict"
            )
            print("文字コード:", encoding)
            return html
        except (UnicodeDecodeError, LookupError):
            pass

    # charsetが明記されていない場合はUTF-8を最優先
    try:
        html = data.decode(
            "utf-8",
            errors="strict"
        )
        print("文字コード: utf-8")
        return html
    except UnicodeDecodeError:
        pass

    # UTF-8で読めない場合だけCP932を試す
    try:
        html = data.decode(
            "cp932",
            errors="strict"
        )
        print("文字コード: cp932")
        return html
    except UnicodeDecodeError:
        pass

    # 最終手段
    print("文字コード: utf-8 / replace")
    return data.decode(
        "utf-8",
        errors="replace"
    )


def clean_text(text):
    text = re.sub(
        r"<[^>]+>",
        "",
        text
    )

    replacements = {
        "&amp;": "&",
        "&quot;": '"',
        "&#39;": "'",
        "&lt;": "<",
        "&gt;": ">",
        "&nbsp;": " "
    }

    for old, new in replacements.items():
        text = text.replace(
            old,
            new
        )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def find_section(html, heading, next_headings):
    # h2の見出しを探す
    pattern = re.compile(
        r"<h2[^>]*>\s*"
        + re.escape(heading)
        + r"\s*</h2>",
        re.IGNORECASE
    )

    start_match = pattern.search(html)

    if not start_match:
        print(
            "見出しが見つかりません:",
            heading
        )
        return None

    start = start_match.end()
    end = len(html)

    # 次のh2までを区画とする
    for next_heading in next_headings:
        pattern2 = re.compile(
            r"<h2[^>]*>\s*"
            + re.escape(next_heading)
            + r"\s*</h2>",
            re.IGNORECASE
        )

        next_match = pattern2.search(
            html,
            start
        )

        if next_match and next_match.start() < end:
            end = next_match.start()

    return html[start:end]


def extract_articles(section_html):
    articles = []
    seen = set()

    # EE Timesの見出しリンク
    pattern = re.compile(
        r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL
    )

    for match in pattern.finditer(section_html):
        href = match.group(1).strip()
        inner = match.group(2)

        if "/ee/articles/" not in href:
            continue

        if href.startswith("//"):
            url = "https:" + href
        elif href.startswith("/"):
            url = urljoin(
                BASE_URL,
                href
            )
        else:
            url = urljoin(
                BASE_URL,
                href
            )

        url = url.split("?")[0]
        url = url.split("#")[0]

        if not url.startswith(
            "https://eetimes.itmedia.co.jp/ee/articles/"
        ):
            continue

        title = clean_text(inner)

        if not title:
            continue

        if url in seen:
            continue

        seen.add(url)

        articles.append({
            "title": title,
            "link": url
        })

    return articles


def get_article_date(url):
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


def main():
    print("EE Times取得開始")

    # ---------------------------------------------
    # トップページ取得
    # ---------------------------------------------

    try:
        html = fetch_html(
            BASE_URL
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

    print(
        "トップページ取得:",
        len(html),
        "文字"
    )

    # ---------------------------------------------
    # Top Stories
    # ---------------------------------------------

    top_html = find_section(
        html,
        "Top Stories",
        [
            "新着記事",
            "FEATURES"
        ]
    )

    if top_html is None:
        top_items = []
    else:
        top_items = extract_articles(
            top_html
        )

    print(
        "Top Stories:",
        len(top_items),
        "件"
    )

    # ---------------------------------------------
    # 新着記事
    # ---------------------------------------------

    new_html = find_section(
        html,
        "新着記事",
        [
            "FEATURES",
            "先端技術",
            "デバイス",
            "通信技術",
            "センシング",
            "部品/材料",
            "テスト/計測"
        ]
    )

    if new_html is None:
        new_items = []
    else:
        new_items = extract_articles(
            new_html
        )

    print(
        "新着記事:",
        len(new_items),
        "件"
    )

    # ---------------------------------------------
    # 2セクションを結合
    # ---------------------------------------------

    all_items = []
    seen = set()

    for item in top_items + new_items:
        if item["link"] in seen:
            continue

        seen.add(
            item["link"]
        )

        all_items.append(item)

    print(
        "合計:",
        len(all_items),
        "件"
    )

    # ---------------------------------------------
    # どちらも取得できなかった場合
    # ---------------------------------------------

    if not all_items:
        print(
            "記事を取得できませんでした。"
        )
        print(
            "既存JSONを維持します。"
        )
        return

    # ---------------------------------------------
    # URLの日付で並べる
    #
    # FC2側でも並べ替えるので、
    # ここでは基本的な順序を作るだけ。
    # ---------------------------------------------

    def sort_key(item):
        dt = get_article_date(
            item["link"]
        )

        if dt is None:
            return datetime(
                1970,
                1,
                1,
                tzinfo=JST
            )

        return dt

    all_items.sort(
        key=sort_key,
        reverse=True
    )

    # 最大20件
    all_items = all_items[:MAX_ITEMS]

    # ---------------------------------------------
    # JSON作成
    # ---------------------------------------------

    output = []

    for item in all_items:
        dt = get_article_date(
            item["link"]
        )

        if dt is None:
            dt = datetime(
                1970,
                1,
                1,
                tzinfo=JST
            )

        output.append({
            "title": item["title"],
            "link": item["link"],
            "pubDate": dt.strftime(
                "%a, %d %b %Y %H:%M:%S +0900"
            )
        })

    # ---------------------------------------------
    # 最新記事をログに表示するだけ
    # JSONは複数件保存する
    # ---------------------------------------------

    print(
        "保存件数:",
        len(output)
    )

    if output:
        print(
            "先頭記事:",
            output[0]["title"]
        )
        print(
            "URL:",
            output[0]["link"]
        )

    # ---------------------------------------------
    # JSONを安全に保存
    # ---------------------------------------------

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
            if os.path.exists(
                temp_file
            ):
                os.remove(
                    temp_file
                )
        except Exception:
            pass

        print(
            "既存JSONを維持します。"
        )
        return

    print(
        "RSS更新完了"
    )


if __name__ == "__main__":
    main()
