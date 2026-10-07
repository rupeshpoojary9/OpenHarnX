"use client";
import { useEffect, useState } from "react";
import type { TocEntry } from "@/lib/docs";

export function Toc({ toc }: { toc: TocEntry[] }) {
  const [active, setActive] = useState<string | null>(toc[0]?.id ?? null);
  useEffect(() => {
    if (!toc.length) return;
    const els = toc.map((t) => document.getElementById(t.id)).filter(Boolean) as HTMLElement[];
    const onScroll = () => {
      const y = 96;
      let current = els[0]?.id ?? null;
      for (const el of els) if (el.getBoundingClientRect().top - y <= 0) current = el.id;
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [toc]);
  if (toc.length < 2) return <aside className="docs-toc" aria-hidden="true" />;
  return (
    <aside className="docs-toc">
      <nav aria-label="On this page">
        <h2>On this page</h2>
        <ul>
          {toc.map((t) => (
            <li key={t.id}>
              <a href={`#${t.id}`} className={`depth-${t.depth}`} data-active={active === t.id}>
                {t.text}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
