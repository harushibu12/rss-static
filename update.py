import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ===== 設定 =====

RSS_URL = "https://rss.itmedia.co.jp/rss/2.0/eetimes.xml"
OUTPUT = "rss-data.json"

# 保存する記事数
MAX_ITEMS = 50


# ===== RSS取得 =====

def fetch_rss():
    req = urllib.request.Request(
        RSS_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


# ===== RSS解析 =====

def parse_rss(xml_data):
    root = ET.fromstring(xml_data)

    items = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()

        if not title or not link:
            continue

        items.append({
            "title": title,
            "link": link,
            "pubDate": pub_date
        })

    return items


# ===== メイン =====

def main():

    print("RSS取得開始")

    xml_data = fetch_rss()

    print("RSS取得完了")

    items = parse_rss(xml_data)

    print("取得記事数:", len(items))

    # 念のため新しい順に並べる
    items.sort(
        key=lambda x: x.get("pubDate", ""),
        reverse=True
    )

    # 最大件数
    items = items[:MAX_ITEMS]

    data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "items": items
    }

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("JSON更新完了")
    print("保存記事数:", len(items))


if __name__ == "__main__":
    main()
