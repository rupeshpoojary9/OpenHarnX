"use client";
import { useId, useRef, useState } from "react";
import { Verdict } from "./Verdict";

export type BriefTab = {
  key: string;
  verdict: "BLOCKED" | "NO REGRESSIONS" | "READY";
  exit: string;
  summary: string;
  sections: { title: string; kind: "fact" | "limit" | "decision"; body: React.ReactNode }[];
  raw: string;
};

const kindLabel = { fact: "Recorded fact", limit: "Not verified", decision: "Your judgment" } as const;

export function BriefPreview({ tabs }: { tabs: BriefTab[] }) {
  const [sel, setSel] = useState(0);
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const t = tabs[sel];
  const move = (d: number) => {
    const n = (sel + d + tabs.length) % tabs.length;
    setSel(n);
    refs.current[n]?.focus();
  };
  return (
    <div className="frame">
      <div className="frame__bar">
        <span style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span className="tag">Exhibit · report.md</span>
          <span>real output of ohx report, demo repository, srt sandbox</span>
        </span>
      </div>
      <div className="brief-tabs" role="tablist" aria-label="Example reports">
        {tabs.map((x, i) => (
          <button
            key={x.key}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            id={`${id}-tab-${x.key}`}
            aria-controls={`${id}-panel`}
            aria-selected={i === sel}
            tabIndex={i === sel ? 0 : -1}
            className="brief-tab"
            onClick={() => setSel(i)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") move(1);
              if (e.key === "ArrowLeft") move(-1);
            }}
          >
            <Verdict v={x.verdict} />
            <span>{x.key === "ready" ? "with acceptance tests" : x.key === "blocked" ? "the cheat" : "the fix"}</span>
          </button>
        ))}
      </div>
      <div className="brief" role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${t.key}`}>
        <div className="brief__doc">
          <p className="brief__title">
            <span># OpenHarnX report:</span> <Verdict v={t.verdict} /> <span>{t.exit}</span>
          </p>
          {t.sections.map((s) => (
            <section className="brief-sec" key={s.title}>
              <div className="brief-sec__label">
                <h4>{s.title}</h4>
                <span className={`kind kind--${s.kind}`}>{kindLabel[s.kind]}</span>
              </div>
              <div className="brief-sec__body">{s.body}</div>
            </section>
          ))}
        </div>
        <aside className="brief__aside">
          <h3>This report</h3>
          <p style={{ margin: "0 0 18px" }}>{t.summary}</p>
          <h3>How to read it</h3>
          <ul>
            <li><span className="kind kind--fact">Fact</span><span>What the records show: files, checks, results.</span></li>
            <li><span className="kind kind--limit">Limit</span><span>What did not pass or was never checked.</span></li>
            <li><span className="kind kind--decision">Decide</span><span>Questions only a person can answer.</span></li>
          </ul>
          <p style={{ margin: 0, fontSize: 13 }}>
            The brief is built by fixed rules over recorded results. No model writes it, and it does not replace reading the diff.
          </p>
        </aside>
      </div>
      <details className="raw-report">
        <summary>Show the whole report.md ({t.raw.split("\n").length} lines, including Details)</summary>
        <pre>{t.raw}</pre>
      </details>
    </div>
  );
}
