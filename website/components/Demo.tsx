"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Cell, DemoStep } from "@/lib/demo";
import { Verdict } from "./Verdict";

const STEP_MS = 5200;

const cellText: Record<Cell, string> = {
  na: "no such check",
  pass: "passed",
  fail: "failed",
  skip: "skipped",
  edited: "edited",
  none: "not run",
  baseline: "passed (baseline)",
};
const cellClass: Record<Cell, string> = {
  na: "st--none",
  pass: "st--pass",
  fail: "st--fail",
  skip: "st--skip",
  edited: "st--skip",
  none: "st--none",
  baseline: "st--none",
};
const cellIcon: Record<Cell, string> = { na: "–", pass: "✓", fail: "✕", skip: "⊘", edited: "✎", none: "·", baseline: "✓" };

function Status({ c }: { c: Cell }) {
  return (
    <span className={`st ${cellClass[c]}`}>
      <span aria-hidden="true">{cellIcon[c]}</span>
      {cellText[c]}
    </span>
  );
}

export function Demo({ steps }: { steps: DemoStep[] }) {
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [seen, setSeen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const started = useRef<number>(0);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // Start playing the first time the demo is on screen, unless motion is reduced.
  useEffect(() => {
    const el = root.current;
    if (!el || seen) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setSeen(true);
          if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) setPlaying(true);
          io.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [seen]);

  useEffect(() => {
    if (!playing) return;
    started.current = performance.now() - elapsed;
    let raf = 0;
    const tick = (now: number) => {
      const e = now - started.current;
      if (e >= STEP_MS) {
        setElapsed(0);
        setAt((a) => {
          if (a >= steps.length - 1) {
            setPlaying(false);
            return a;
          }
          return a + 1;
        });
        started.current = now;
      } else {
        setElapsed(e);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, steps.length]);

  const go = useCallback((i: number) => {
    setPlaying(false);
    setElapsed(0);
    setAt(i);
  }, []);

  const replay = () => {
    setElapsed(0);
    setAt(0);
    setPlaying(true);
  };

  const step = steps[at];
  const last = at === steps.length - 1;
  const progress = playing ? Math.min(elapsed / STEP_MS, 1) : 0;

  return (
    <div ref={root}>
      <div className="frame">
        <div className="frame__bar">
          <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span className="tag">Scripted demonstration</span>
            <span>examples/cheat-demo · output captured from ohx 0.1.0 · no model, nothing runs in your browser</span>
          </span>
          <span className="demo__controls">
            <button
              type="button"
              className="icon-btn"
              onClick={() => (last && !playing ? replay() : setPlaying((p) => !p))}
              aria-label={playing ? "Pause" : last ? "Replay" : "Play"}
              title={playing ? "Pause" : last ? "Replay" : "Play"}
            >
              {playing ? (
                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M4 2.5v9M10 2.5v9" stroke="currentColor" strokeWidth="2" /></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3.5 2.2v9.6L11.5 7z" fill="currentColor" /></svg>
              )}
            </button>
            <button type="button" className="icon-btn" onClick={replay} aria-label="Replay from the start" title="Replay from the start">
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M2.6 7A4.4 4.4 0 1 0 4 3.8" fill="none" stroke="currentColor" strokeWidth="1.6" /><path d="M2.3 1.6v2.8h2.8" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
            </button>
          </span>
        </div>
        <div className="demo">
          <ol className="demo__steps" aria-label="Demonstration steps">
            {steps.map((s, i) => (
              <li key={s.title}>
                <button type="button" className="demo__step" aria-current={i === at ? "step" : undefined} onClick={() => go(i)}>
                  <span className="n">{i === 0 ? "00" : String(i).padStart(2, "0")}</span>
                  <span>{s.title}</span>
                  {i === at ? <span className="progress" style={{ transform: `scaleX(${progress})` }} aria-hidden="true" /> : null}
                </button>
              </li>
            ))}
          </ol>
          <div className="demo__body" aria-live="polite">
            <div className="demo__pane">
              <p className="demo__caption">{step.caption}</p>
              <pre className={`term${reduced ? "" : " animate"}`} key={at} aria-label={`Output for step ${at}: ${step.title}`}>
                {step.lines.map((l, i) => (
                  <span key={i} className={`line ${l.kind ?? ""}`} style={{ ["--i" as string]: i }}>
                    {l.text}
                  </span>
                ))}
              </pre>
            </div>
            <div className="demo__pane">
              <table className="ledger">
                <caption className="visually-hidden">Each locked test, as plain pytest and as OpenHarnX see it at this step</caption>
                <thead>
                  <tr>
                    <th scope="col">Locked test</th>
                    <th scope="col">Plain pytest</th>
                    <th scope="col">OpenHarnX</th>
                  </tr>
                </thead>
                <tbody>
                  {step.ledger.map((r) => (
                    <tr key={r.name}>
                      <td className="name">{r.name.replace(/_/g, "_\u200b")}</td>
                      <td>
                        <Status c={r.plain} />
                        {r.note ? <span className="note">{r.note}</span> : null}
                      </td>
                      <td>
                        <Status c={r.ohx} />
                        {r.ohxNote ? <span className="note">{r.ohxNote}</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="demo__verdict">
                {step.verdict ? (
                  <>
                    <span className="stamp" key={`v${at}`}>
                      <Verdict v={step.verdict.name} size="lg" />
                    </span>
                    <span className="exit">{step.verdict.exit}</span>
                  </>
                ) : (
                  <span className="exit">
                    {step.plainSummary ? `plain pytest: ${step.plainSummary}` : "the agent is changing files"}
                    {at === 0 ? " · OpenHarnX: baseline recorded" : " · OpenHarnX: not run yet"}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
