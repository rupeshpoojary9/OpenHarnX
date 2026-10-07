import { codeToHtml } from "shiki";
import { readRepoText } from "@/lib/docs";
import { links } from "@/lib/site";
import { codeThemes, colorReplacements } from "@/lib/highlight";
import { CopyButton } from "./CopyButton";

/** Shows a file from the OpenHarnX repository verbatim, read at build time. */
export async function RepoFile({ path, lang, from, to }: { path: string; lang: string; from?: string; to?: string }) {
  let text = await readRepoText(path);
  if (from) text = text.slice(text.indexOf(from));
  if (to) text = text.slice(0, text.indexOf(to) + to.length);
  const html = await codeToHtml(text.replace(/\n$/, ""), {
    lang,
    themes: codeThemes,
        colorReplacements,
    defaultColor: false,
  });
  return (
    <div className="code">
      <div className="code__bar">
        <a href={links.blob(path)} style={{ color: "inherit", textTransform: "none" }}>
          {path}
        </a>
        <CopyButton />
      </div>
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
