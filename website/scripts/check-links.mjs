// Checks every link on the built site: internal pages and #anchors, and external URLs.
//   npm run build && npm start &   then   npm run check:links [-- --base http://localhost:3000]
// Exits 1 when an internal link or anchor is broken, or an external URL fails.
// Links into website/ on GitHub only exist once this folder is on the main branch;
// they are reported separately and do not fail the check.

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const base = arg("--base", "http://localhost:3000").replace(/\/$/, "");
const offline = process.argv.includes("--offline");

const sitemap = await (await fetch(`${base}/sitemap.xml`)).text();
const locs = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => new URL(m[1]));
// The origin the site was built for (SITE_URL); links to it are internal too.
const siteOrigin = locs[0]?.origin ?? base;
const pages = locs.map((u) => u.pathname);
pages.push("/llms.txt");

const html = new Map();
const internal = new Map(); // target -> set of pages linking to it
const external = new Map();
const idsOf = (text) => new Set([...text.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
const decode = (s) => s.replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/&quot;/g, '"');

for (const page of pages) {
  const res = await fetch(base + page);
  const text = await res.text();
  if (res.status !== 200) console.log(`PAGE ${res.status} ${page}`);
  html.set(page, text);
  const hrefs = page.endsWith(".txt")
    ? [...text.matchAll(/\((https?:\/\/[^)\s]+)\)/g)].map((m) => m[1])
    : [...text.matchAll(/<a\b[^>]*\bhref="([^"]+)"/g)].map((m) => decode(m[1]));
  for (const href of hrefs) {
    if (href.startsWith("mailto:")) continue;
    const own = [base, siteOrigin].find((o) => href === o || href.startsWith(o + "/") || href.startsWith(o + "#"));
    if (own) {
      const rel = href.slice(own.length) || "/";
      (internal.get(rel) ?? internal.set(rel, new Set()).get(rel)).add(page);
    } else if (/^https?:/.test(href)) {
      (external.get(href) ?? external.set(href, new Set()).get(href)).add(page);
    } else {
      const u = new URL(href, base + page);
      const target = u.pathname + u.hash;
      (internal.get(target) ?? internal.set(target, new Set()).get(target)).add(page);
    }
  }
}

let failures = 0;
for (const [target, from] of internal) {
  const [p, hash] = target.split("#");
  const path = p || "/";
  let text = html.get(path);
  if (text === undefined) {
    const res = await fetch(base + path, { redirect: "follow" });
    text = res.ok ? await res.text() : undefined;
    if (!res.ok) {
      failures++;
      console.log(`BROKEN ${res.status} ${target}  (from ${[...from][0]})`);
      continue;
    }
  }
  if (hash && !idsOf(text).has(decodeURIComponent(hash))) {
    failures++;
    console.log(`ANCHOR ${target}  (from ${[...from][0]})`);
  }
}

const pending = [];
if (!offline) {
  const entries = [...external];
  const results = await Promise.all(
    entries.map(async ([url]) => {
      try {
        let res = await fetch(url, { method: "HEAD", redirect: "follow" });
        if (res.status === 405 || res.status === 403 || res.status === 404) res = await fetch(url, { redirect: "follow" });
        return res.status;
      } catch (e) {
        return String(e.message);
      }
    }),
  );
  entries.forEach(([url, from], i) => {
    const status = results[i];
    if (status === 200) return;
    if (/\/(blob|tree|edit)\/main\/website\//.test(url)) {
      pending.push(`${status} ${url}`);
      return;
    }
    failures++;
    console.log(`EXTERNAL ${status} ${url}  (from ${[...from][0]})`);
  });
}

console.log(
  `${pages.length} pages, ${internal.size} internal targets, ${external.size} external URLs${offline ? " (not fetched)" : ""}: ${failures} broken`,
);
if (pending.length) {
  console.log(`${pending.length} links into website/ on GitHub, valid once this folder is on main:`);
  for (const p of pending.slice(0, 5)) console.log(`  ${p}`);
  if (pending.length > 5) console.log(`  ... and ${pending.length - 5} more`);
}
process.exit(failures ? 1 : 0);
