import GithubSlugger from "github-slugger";
import { flatNav, docHref } from "./nav";
import { rawDoc } from "./docs";

export type SearchDoc = {
  id: string;
  href: string;
  page: string;
  section: string;
  heading: string;
  text: string;
};

/** Markdown or MDX to plain text, keeping words people search for (commands, flags). */
export function plain(md: string): string {
  return md
    .replace(/^import .*$/gm, "")
    .replace(/<[A-Z][^>]*\/>/g, " ")
    .replace(/<\/?[A-Za-z][^>]*>/g, " ")
    .replace(/```[a-z]*\n?/g, " ")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`>#|]/g, " ")
    .replace(/\{[^}]*\}/g, (m) => (m.length < 20 ? m : " "))
    .replace(/-{3,}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export async function buildSearchIndex(): Promise<SearchDoc[]> {
  const out: SearchDoc[] = [];
  for (const item of flatNav) {
    const { title, description, body } = await rawDoc(item);
    const href = docHref(item.slug);
    const slugger = new GithubSlugger();
    // Split at level-2 headings, ignoring "## " lines inside fenced code.
    const parts: string[] = [""];
    let fenced = false;
    for (const line of body.split("\n")) {
      if (/^\s*```/.test(line)) fenced = !fenced;
      if (!fenced && /^##\s/.test(line)) parts.push("");
      parts[parts.length - 1] += line + "\n";
    }
    parts.forEach((part, i) => {
      const m = /^##\s+(.+)$/m.exec(part);
      const heading = i === 0 || !m ? "" : plain(m[1]);
      const id = heading ? slugger.slug(heading) : "";
      const text = plain(i === 0 && description ? `${description} ${part}` : part.replace(/^##.*$/m, ""));
      if (!text && !heading) return;
      out.push({
        id: `${item.slug || "index"}#${id || i}`,
        href: id ? `${href}#${id}` : href,
        page: title,
        section: item.section,
        heading,
        text: text.slice(0, 2400),
      });
    });
  }
  return out;
}
