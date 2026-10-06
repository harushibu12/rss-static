function rssMain(rssId, rssUrls, ng1, ng2, ng3, ngChar) {

  Promise.allSettled(
    rssUrls.map(url =>
      fetch(url, { cache: "no-store" })
        .then(r => {
          if (!r.ok) {
            throw new Error("HTTP " + r.status);
          }
          return r.json();
        })
        .catch(() => null)
    )
  )
  .then(results => {

    let items = [];

    results.forEach(r => {

      if (r.status !== "fulfilled") return;
      if (!r.value) return;

      /*
       * rss-data.json が配列の場合
       *
       * [
       *   {
       *     "title": "...",
       *     "link": "...",
       *     "pubDate": "..."
       *   }
       * ]
       */

      if (Array.isArray(r.value)) {

        items = items.concat(r.value);

        return;
      }

      /*
       * { items: [...] } 形式にも対応
       */

      if (Array.isArray(r.value.items)) {

        items = items.concat(r.value.items);

      }

    });

    /*
     * 公開日時の新しい順に並べる
     */

    items.sort((a, b) => {

      const da = Date.parse(
        a.pubDate ||
        a.pubdate ||
        a.isoDate ||
        ""
      ) || 0;

      const db = Date.parse(
        b.pubDate ||
        b.pubdate ||
        b.isoDate ||
        ""
      ) || 0;

      return db - da;

    });

    /*
     * NGワード除外
     */

    const filtered = items.filter(i => {

      const title = String(
        i.title || ""
      );

      if (ng1 && ng1.test(title)) {
        return false;
      }

      if (ng2 && ng2.test(title)) {
        return false;
      }

      if (ng3 && ng3.test(title)) {
        return false;
      }

      if (ngChar && ngChar.test(title)) {
        return false;
      }

      return true;

    });

    const target =
      document.getElementById(rssId);

    if (!target) return;

    /*
     * 最新1件だけ表示
     */

    const showItems =
      filtered.slice(0, 1);

    if (!showItems.length) {

      target.innerHTML = "";

      return;

    }

    target.innerHTML =
      showItems.map(i => `

        <div class="item">

          <a
            href="${i.link}"
            target="_blank"
            rel="noopener noreferrer"
          >
            ${i.title || ""}
          </a>

        </div>

      `).join("");

  })
  .catch(() => {

    const target =
      document.getElementById(rssId);

    if (target) {

      target.innerHTML = "";

    }

  });

}
