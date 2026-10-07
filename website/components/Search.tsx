"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import MiniSearch from "minisearch";

type Doc = { id: string; href: string; page: string; section: string; heading: string; text: string };
type Hit = Doc & { snippet: string };

const suggestions = [
  { href: "/docs/installation", label: "Installation" },
  { href: "/docs/first-verification", label: "Verify your first change" },
  { href: "/docs/concepts/verdicts", label: "Verdicts" },
  { href: "/docs/ci/github-actions", label: "GitHub Actions" },
  { href: "/docs/reference/cli", label: "CLI reference" },
];

function snippet(text: string, terms: string[]): string {
  const lower = text.toLowerCase();
  let at = -1;
  for (const t of terms) {
    at = lower.indexOf(t.toLowerCase());
    if (at >= 0) break;
  }
  const start = Math.max(0, at - 40);
  return (start > 0 ? "…" : "") + text.slice(start, start + 160);
}

function Highlight({ text, terms }: { text: string; terms: string[] }) {
  if (!terms.length) return <>{text}</>;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "ig");
  return (
    <>
      {text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>))}
    </>
  );
}

export function SearchDialog() {
  const ref = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [index, setIndex] = useState<MiniSearch<Doc> | null>(null);
  const [failed, setFailed] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);

  const open = useCallback(() => {
    const d = ref.current;
    if (!d || d.open) return;
    d.showModal();
    setTimeout(() => input.current?.select(), 0); // typing replaces the last query
    if (!index) {
      fetch("/search-index.json")
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((docs: Doc[]) => {
          const ms = new MiniSearch<Doc>({
            fields: ["page", "heading", "text"],
            storeFields: ["href", "page", "section", "heading", "text"],
            searchOptions: { boost: { page: 3, heading: 2 }, prefix: true, fuzzy: 0.15, combineWith: "AND" },
          });
          ms.addAll(docs);
          setIndex(ms);
        })
        .catch(() => setFailed(true));
    }
  }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target as HTMLElement)?.tagName ?? "");
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        open();
      } else if (e.key === "/" && !typing && !ref.current?.open) {
        e.preventDefault();
        open();
      }
    };
    const onOpen = () => open();
    window.addEventListener("keydown", onKey);
    window.addEventListener("ohx:search", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("ohx:search", onOpen);
    };
  }, [open]);

  const terms = useMemo(() => q.trim().split(/\s+/).filter((t) => t.length > 1), [q]);
  const hits: Hit[] = useMemo(() => {
    if (!index || !q.trim()) return [];
    const seen = new Set<string>();
    return index
      .search(q.trim())
      .filter((r) => !seen.has(r.href) && seen.add(r.href))
      .slice(0, 12)
      .map((r) => ({ ...(r as unknown as Doc), snippet: snippet(r.text as string, terms) }));
  }, [index, q, terms]);

  useEffect(() => setSel(0), [q]);

  const close = () => ref.current?.close();
  const go = (href: string) => {
    close();
    setQ("");
    router.push(href);
  };

  return (
    <dialog
      ref={ref}
      className="search-dialog"
      aria-label="Search the documentation"
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
    >
      <div className="search-dialog__inner">
        <div className="search-input-row">
          <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.4" />
            <path d="m10.5 10.5 3.5 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
          <input
            ref={input}
            type="search"
            placeholder="Search commands, verdicts, CI…"
            aria-label="Search"
            aria-controls="search-results"
            aria-activedescendant={hits[sel] ? `hit-${sel}` : undefined}
            role="combobox"
            aria-expanded={hits.length > 0}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel((s) => Math.min(s + 1, hits.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel((s) => Math.max(s - 1, 0));
              } else if (e.key === "Escape") {
                // In a search field the first Escape would only clear it; close instead.
                e.preventDefault();
                close();
              } else if (e.key === "Enter" && hits[sel]) {
                e.preventDefault();
                go(hits[sel].href);
              }
            }}
          />
          <kbd>Esc</kbd>
        </div>
        {failed ? (
          <div className="search-empty" role="status">
            The search index did not load. Browse the <a href="/docs">documentation</a> from its contents instead.
          </div>
        ) : !q.trim() ? (
          <div className="search-empty">
            Try <code>verify</code>, <code>STALE</code>, <code>approve-tests</code> or <code>GitLab</code>. Common pages:
            <ul>
              {suggestions.map((s) => (
                <li key={s.href}>
                  <a href={s.href} onClick={(e) => { e.preventDefault(); go(s.href); }}>{s.label}</a>
                </li>
              ))}
            </ul>
          </div>
        ) : !index ? (
          <div className="search-empty" role="status">Loading the index…</div>
        ) : hits.length === 0 ? (
          <div className="search-empty" role="status">
            Nothing matches “{q.trim()}”. Check the spelling, search for a command such as <code>ohx gate</code>, or
            read <a href="/docs/help/troubleshooting" onClick={(e) => { e.preventDefault(); go("/docs/help/troubleshooting"); }}>Troubleshooting</a>.
            If the docs should cover it, <a href="https://github.com/rupeshpoojary9/OpenHarnX/issues">open an issue</a>.
          </div>
        ) : (
          <ul className="search-results" id="search-results" role="listbox">
            {hits.map((h, i) => (
              <li key={h.href} role="presentation">
                <a
                  id={`hit-${i}`}
                  role="option"
                  aria-selected={i === sel}
                  href={h.href}
                  onMouseMove={() => i !== sel && setSel(i)}
                  onClick={(e) => { e.preventDefault(); go(h.href); }}
                >
                  <span className="path">{h.section} / {h.page}</span>
                  <span className="title"><Highlight text={h.heading || h.page} terms={terms} /></span>
                  <span className="snippet"><Highlight text={h.snippet} terms={terms} /></span>
                </a>
              </li>
            ))}
          </ul>
        )}
        <div className="search-foot" aria-hidden="true">
          <span><kbd>↑</kbd> <kbd>↓</kbd> move</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>/</kbd> or <kbd>⌘ K</kbd> search</span>
        </div>
      </div>
    </dialog>
  );
}
