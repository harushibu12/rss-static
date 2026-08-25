import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

RSS_URL = "https://politepaul.com/fd/9LUDxoAjTgKj.xml"
OUTPUT = "rss-data.json"

def main():
    req = urllib.request.Request(
        RSS_URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)

    items = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")

        items.append({
            "title": title,
            "link": link,
            "pubDate": pub_date
        })

    data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "items": items
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
