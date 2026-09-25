import json
import urllib.request
import urllib.error
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

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()

    except urllib.error.HTTPError as e:
        print(f"RSS取得失敗: HTTP {e.code}")
        return None

    except urllib.error.URLError as e:
        print(f"RSS取得失敗: {e.reason}")
        return None

    except TimeoutError:
        print("RSS取得失敗: タイムアウト")
        return None

    except Exception as e:
        print(f"RSS取得失敗: {e}")
        return None


# ===== RSS解析 =====

def parse_rss(xml_data):
    try:
        root = ET.fromstring(xml_data)

    except ET.ParseError as e:
        print(f"RSS解析失敗: {e}")
        return []

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
    print("URL:", RSS_URL)

    xml_data = fetch_rss()

    # ===== RSS取得失敗 =====
    # 既存のrss-data.jsonには一切触れない

    if xml_data is None:
        print("RSS取得失敗")
        print("前回正常な rss-data.json を維持します。")
        return

    print("RSS取得完了")

    # ===== RSS解析 =====

    items = parse_rss(xml_data)

    print("取得記事数:", len(items))

    # ===== 取得した記事を確認 =====
    # GitHub Actionsのログに全記事を表示

    print("===== 取得した記事一覧 =====")

    for i, item in enumerate(items, 1):
        print(
            f"{i}. {item['pubDate']} | {item['title']}"
        )

    print("==========================")

    # ===== 記事0件の場合 =====
    # 異常とみなし、既存データを維持する

    if len(items) == 0:
        print("記事が0件です。")
        print("前回正常な rss-data.json を維持します。")
        return

    # ===== 新しい順に並べる =====

    items.sort(
        key=lambda x: x.get("pubDate", ""),
        reverse=True
    )

    # ===== 最大件数 =====

    items = items[:MAX_ITEMS]

    # ===== 新しいJSON =====

    data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "items": items
    }

    # ===== 一時ファイルに保存 =====
    # 保存途中で異常が起きても本体は壊さない

    TEMP_OUTPUT = OUTPUT + ".tmp"

    try:

        with open(
            TEMP_OUTPUT,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        # 正常に書き込みできた場合だけ
        # rss-data.jsonを置き換える

        import os
        os.replace(TEMP_OUTPUT, OUTPUT)

    except Exception as e:

        print(f"JSON保存失敗: {e}")
        print("前回正常な rss-data.json を維持します。")

        try:
            import os
            if os.path.exists(TEMP_OUTPUT):
                os.remove(TEMP_OUTPUT)
        except Exception:
            pass

        return

    print("JSON更新完了")
    print("保存記事数:", len(items))


if __name__ == "__main__":
    main()
