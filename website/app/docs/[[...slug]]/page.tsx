import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { loadDoc } from "@/lib/docs";
import { flatNav, docHref } from "@/lib/nav";
import { links, release } from "@/lib/site";
import { DocsSidebar } from "@/components/DocsSidebar";
import { Toc } from "@/components/Toc";
import { Callout } from "@/components/Callout";
import { mdxComponents } from "@/components/mdx-components";
import { CliReference, cliData, cliToc } from "@/components/CliReference";

type Props = { params: Promise<{ slug?: string[] }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return flatNav.map((i) => ({ slug: i.slug ? i.slug.split("/") : [] }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const slug = ((await params).slug ?? []).join("/");
  const doc = await loadDoc(slug);
  if (!doc) return {};
  const url = docHref(slug);
  return {
    title: slug ? doc.title : "Documentation",
    description: doc.description,
    alternates: { canonical: url },
    openGraph: { title: `${doc.title} | OpenHarnX docs`, description: doc.description, url },
  };
}

export default async function DocPage({ params }: Props) {
  const slug = ((await params).slug ?? []).join("/");
  const doc = await loadDoc(slug);
  if (!doc) notFound();
  const at = flatNav.findIndex((i) => i.slug === slug);
  const prev = flatNav[at - 1];
  const next = flatNav[at + 1];
  const toc = doc.item.source.kind === "cli" ? cliToc((await cliData()).commands) : doc.toc;
  const fromRepo = doc.item.source.kind === "repo";

  return (
    <div className="docs">
      <DocsSidebar />
      <div className="docs-main">
        <details className="docs-mobile-nav">
          <summary>Documentation contents</summary>
          <DocsSidebar />
        </details>
        <article className="docs-article">
          <p className="breadcrumb">{doc.item.section}</p>
          <h1 className="doc-title">{doc.title}</h1>
          {doc.description ? <p className="doc-desc">{doc.description}</p> : null}
          <div className="doc-meta">
            <span className="tag tag--outline">OpenHarnX {release.version}</span>
            {doc.experimental ? <span className="tag" style={{ background: "var(--invalid)" }}>Experimental</span> : null}
            {fromRepo ? <span className="tag tag--outline tag--path">from the repository: {doc.sourcePath}</span> : null}
          </div>
          {doc.experimental ? (
            <Callout type="experimental">
              <p>
                This page describes behaviour outside the {release.version} release boundary. It works and is tested,
                but OpenHarnX makes no claim of protection for it. See{" "}
                <Link href="/docs/reference/supported-and-experimental">supported and experimental</Link>.
              </p>
            </Callout>
          ) : null}
          {fromRepo ? (
            <Callout>
              <p>
                This page is the repository file <a href={links.blob(doc.sourcePath!)}>{doc.sourcePath}</a> on{" "}
                <code>main</code>, rendered at build time. It may describe work after {release.tag}.
              </p>
            </Callout>
          ) : null}
          {doc.item.source.kind === "cli" ? (
            <CliReference />
          ) : doc.Content ? (
            <div className="prose">
              <doc.Content components={mdxComponents} />
            </div>
          ) : null}
          <footer className="doc-footer">
            <div className="doc-footer__meta">
              {doc.sourcePath ? (
                <a href={doc.item.source.kind === "cli" ? links.blob(doc.sourcePath) : links.edit(doc.sourcePath)}>
                  {doc.item.source.kind === "cli" ? "View the generated source" : "Edit this page on GitHub"}
                </a>
              ) : null}
              <a href={links.issues}>Something wrong or missing? Open an issue</a>
            </div>
            <nav className="pager" aria-label="Previous and next pages">
              {prev ? (
                <Link href={docHref(prev.slug)} rel="prev">
                  <span className="dir">Previous</span>
                  <span className="t">{prev.title}</span>
                </Link>
              ) : null}
              {next ? (
                <Link href={docHref(next.slug)} rel="next" className="next">
                  <span className="dir">Next</span>
                  <span className="t">{next.title}</span>
                </Link>
              ) : null}
            </nav>
          </footer>
        </article>
      </div>
      <Toc toc={toc} />
    </div>
  );
}
