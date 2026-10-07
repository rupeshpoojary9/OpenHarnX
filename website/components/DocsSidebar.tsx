"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { nav, docHref } from "@/lib/nav";
import { release } from "@/lib/site";

export function DocsSidebar() {
  const path = (usePathname() ?? "/docs").replace(/\/$/, "");
  return (
    <nav className="docs-sidebar" aria-label="Documentation">
      <div className="version" title={`Documentation for OpenHarnX ${release.version}, released ${release.date}`}>
        <span className="tag tag--accent">{release.tag}</span>
        <span>released {release.date}</span>
      </div>
      {nav.map((s) => (
        <section key={s.title}>
          <h2>{s.title}</h2>
          <ul>
            {s.items.map((i) => {
              const href = docHref(i.slug);
              return (
                <li key={href}>
                  <Link href={href} aria-current={path === href ? "page" : undefined}>
                    <span>{i.title}</span>
                    {i.badge === "experimental" ? <span className="mini">exp</span> : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </nav>
  );
}
