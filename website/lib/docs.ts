import fs from "node:fs/promises";
import path from "node:path";
import { cache } from "react";
import { evaluate } from "@mdx-js/mdx";
import * as runtime from "react/jsx-runtime";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import rehypeShiki from "@shikijs/rehype";
import { visit } from "unist-util-visit";
import type { Element, Root as HastRoot } from "hast";
import type { MDXContent } from "mdx/types";
import { findItem, repoFileToSlug, type NavItem } from "./nav";
import { links, repo } from "./site";
import { codeThemes, colorReplacements } from "./highlight";

export const siteRoot = process.cwd();
export const repoRoot = path.resolve(/*turbopackIgnore: true*/ siteRoot, "..");
const contentDir = path.join(/*turbopackIgnore: true*/ siteRoot, "content", "docs");

export type TocEntry = { id: string; text: string; depth: 2 | 3 };
export type Frontmatter = { title?: string; description?: string; status?: string };

export type LoadedDoc = {
  item: NavItem & { section: string };
  title: string;
  description?: string;
  experimental: boolean;
  /** Repository path of the file this page is made from, for "Edit this page". */
  sourcePath: string | null;
  raw: string;
  Content: MDXContent | null;
  toc: TocEntry[];
};

/** Flat `key: value` frontmatter between --- lines; no nesting is used. */
export function parseFrontmatter(text: string): { data: Frontmatter; body: string } {
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(text);
  if (!m) return { data: {}, body: text };
  const data: Record<string, string> = {};
  for (const line of m[1].split("\n")) {
    const kv = /^([a-z_]+):\s*(.*)$/.exec(line.trim());
    if (kv) data[kv[1]] = kv[2].replace(/^["']|["']$/g, "");
  }
  return { data, body: text.slice(m[0].length) };
}

// Other repository files that have an equivalent page here.
const repoAliases: Record<string, string> = {
  "docs/ci/README.md": "ci/github-actions",
  "docs/releasing.md": "releases",
  "examples/cheat-demo/README.md": "run-the-demo",
};

/** Turn a link inside a repository file into a site page or a GitHub URL. */
export function rewriteRepoLink(href: string, fromFile: string): string {
  if (/^(https?:|mailto:|#)/.test(href)) {
    const own = `${repo.url}#`;
    return href.startsWith(own) ? `/docs` : href;
  }
  const [p, hash] = href.split("#");
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(fromFile), p));
  const slug = repoFileToSlug[resolved] ?? repoAliases[resolved];
  if (slug !== undefined) return `/docs/${slug}`.replace(/\/$/, "") + (hash ? `#${hash}` : "");
  const looksLikeDir = !path.posix.extname(resolved) || p.endsWith("/");
  const url = looksLikeDir ? links.tree(resolved.replace(/\/$/, "")) : links.blob(resolved);
  return url + (hash ? `#${hash}` : "");
}

function rehypeRepoLinks(fromFile: string) {
  return () => (tree: HastRoot) => {
    visit(tree, "element", (node: Element) => {
      if (node.tagName === "a" && typeof node.properties?.href === "string") {
        node.properties.href = rewriteRepoLink(node.properties.href, fromFile);
      }
    });
  };
}

function textOf(node: Element | HastRoot): string {
  let out = "";
  visit(node, "text", (t: { value: string }) => {
    out += t.value;
  });
  return out;
}

/** Collect h2/h3 for the on-page contents, and give each heading a permalink. */
function rehypeHeadings(toc: TocEntry[]) {
  return () => (tree: HastRoot) => {
    visit(tree, "element", (node: Element) => {
      const depth = node.tagName === "h2" ? 2 : node.tagName === "h3" ? 3 : 0;
      if (!depth || typeof node.properties?.id !== "string") return;
      const id = node.properties.id;
      const text = textOf(node);
      toc.push({ id, text, depth: depth as 2 | 3 });
      node.children.push({
        type: "element",
        tagName: "a",
        properties: {
          href: `#${id}`,
          className: ["anchor"],
          ariaLabel: `Link to "${text}"`,
        },
        children: [{ type: "text", value: "#" }],
      });
    });
  };
}

/** Markdown and MDX share one pipeline: GFM tables, slugs, highlighted code. */
export async function compile(source: string, opts: { format: "md" | "mdx"; repoFile?: string }) {
  const toc: TocEntry[] = [];
  const rehypePlugins: unknown[] = [
    rehypeSlug,
    rehypeHeadings(toc),
    [
      rehypeShiki,
      {
        themes: codeThemes,
        colorReplacements,
        defaultColor: false,
        fallbackLanguage: "text",
        addLanguageClass: true,
        transformers: [
          {
            pre(this: { options: { lang: string } }, node: Element) {
              node.properties["data-lang"] = this.options.lang;
            },
          },
        ],
      },
    ],
  ];
  if (opts.repoFile) rehypePlugins.unshift(rehypeRepoLinks(opts.repoFile));
  const mod = await evaluate(source, {
    ...runtime,
    format: opts.format,
    remarkPlugins: [remarkGfm],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rehypePlugins: rehypePlugins as any,
  });
  return { Content: mod.default, toc };
}

/** A repository file: its first "# " heading becomes the page title. */
async function readRepoFile(file: string) {
  const text = await fs.readFile(path.join(/*turbopackIgnore: true*/ repoRoot, file), "utf8");
  const m = /^#\s+(.+)\n/m.exec(text);
  return { heading: m?.[1]?.trim(), body: m ? text.replace(m[0], "") : text };
}

export const loadDoc = cache(async (slug: string): Promise<LoadedDoc | null> => {
  const item = findItem(slug);
  if (!item) return null;
  const src = item.source;
  if (src.kind === "cli") {
    return {
      item,
      title: item.title,
      description: "Every command and option of the released ohx command, read from its own parser.",
      experimental: false,
      sourcePath: `${repo.siteDir}/content/generated/cli.json`,
      raw: "",
      Content: null,
      toc: [],
    };
  }
  if (src.kind === "repo") {
    const { heading, body } = await readRepoFile(src.file);
    const { Content, toc } = await compile(body, { format: "md", repoFile: src.file });
    return {
      item,
      title: item.title,
      description: heading && heading !== item.title ? heading : undefined,
      experimental: false,
      sourcePath: src.file,
      raw: body,
      Content,
      toc,
    };
  }
  const text = await fs.readFile(path.join(/*turbopackIgnore: true*/ contentDir, src.file), "utf8");
  const { data, body } = parseFrontmatter(text);
  const { Content, toc } = await compile(body, { format: "mdx" });
  return {
    item,
    title: data.title ?? item.title,
    description: data.description,
    experimental: data.status === "experimental",
    sourcePath: `${repo.siteDir}/content/docs/${src.file}`,
    raw: body,
    Content,
    toc,
  };
});

/** Raw text of a page for the search index and llms.txt, without compiling it. */
export async function rawDoc(item: NavItem): Promise<{ title: string; description?: string; body: string }> {
  const src = item.source;
  if (src.kind === "repo") {
    const { body } = await readRepoFile(src.file);
    return { title: item.title, body };
  }
  if (src.kind === "cli") {
    const cli = JSON.parse(
      await fs.readFile(path.join(/*turbopackIgnore: true*/ siteRoot, "content", "generated", "cli.json"), "utf8"),
    ) as { commands: { command: string; help: string; options: { flags: string[]; help: string | null }[] }[] };
    const body = cli.commands
      .map(
        (c) =>
          `## ${c.command}\n\n${c.help}\n\n` +
          c.options.map((o) => `${o.flags.join(", ")}: ${o.help ?? ""}`).join("\n"),
      )
      .join("\n\n");
    return { title: item.title, body };
  }
  const text = await fs.readFile(path.join(/*turbopackIgnore: true*/ contentDir, src.file), "utf8");
  const { data, body } = parseFrontmatter(text);
  return { title: data.title ?? item.title, description: data.description, body };
}

export async function readRepoText(file: string) {
  return fs.readFile(path.join(/*turbopackIgnore: true*/ repoRoot, file), "utf8");
}
