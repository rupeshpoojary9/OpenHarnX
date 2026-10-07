import { flatNav, docHref } from "@/lib/nav";
import { rawDoc } from "@/lib/docs";
import { description, installCommand, links, release, siteUrl } from "@/lib/site";

export const dynamic = "force-static";

export async function GET() {
  const base = siteUrl();
  const sections = new Map<string, string[]>();
  for (const item of flatNav) {
    const { title, description: d } = await rawDoc(item);
    const line = `- [${title}](${base}${docHref(item.slug)})${d ? `: ${d}` : ""}`;
    sections.set(item.section, [...(sections.get(item.section) ?? []), line]);
  }
  const body = [
    "# OpenHarnX",
    "",
    `> ${description}`,
    "",
    `Current release: ${release.tag} (${release.date}), commit ${release.commit}. Install: \`${installCommand}\`. Supported: Python projects tested with pytest, macOS arm64 locally, Linux in CI, srt ${release.srt} sandbox. TypeScript, JavaScript and Go are experimental. A verdict never authorizes a merge or deploy.`,
    "",
    ...[...sections].flatMap(([s, lines]) => [`## ${s}`, "", ...lines, ""]),
    "## Optional",
    "",
    `- [Source code](${links.github})`,
    `- [Examples](${base}/examples)`,
    "",
  ].join("\n");
  return new Response(body, { headers: { "content-type": "text/plain; charset=utf-8" } });
}
