import type { Metadata } from "next";
import Link from "next/link";
import { links } from "@/lib/site";
import { Verdict } from "@/components/Verdict";

export const metadata: Metadata = {
  title: "Examples",
  description: "Reproducible OpenHarnX examples and published evaluation records, with their limits.",
  alternates: { canonical: "/examples" },
};

const examples = [
  {
    tag: "Run it · 15 seconds",
    title: "The cheat demo",
    body: "A scripted agent breaks fixed coupons, rewrites one test and skips another. Plain pytest passes; OpenHarnX blocks it. The genuine fix passes.",
    verdicts: ["BLOCKED", "NO REGRESSIONS"] as const,
    points: ["No model, no network, a temporary folder", "Exits 1 if any verdict differs from what it shows", "Run by the repository's own test suite"],
    links: [
      { href: "/docs/run-the-demo", label: "Run the demo" },
      { href: links.cheatDemo, label: "examples/cheat-demo" },
    ],
  },
  {
    tag: "Read it",
    title: "Review briefs, before and after",
    body: "Five cases in throwaway repositories: passing acceptance tests, regressions only, a failed mandatory check, changed code no test imported, and a change made after verification.",
    verdicts: ["READY", "NO REGRESSIONS", "BLOCKED", "STALE"] as const,
    points: ["Made by a script in the repository, without the sandbox", "Shows what the brief added to the earlier report"],
    links: [
      { href: links.blob("docs/tasks/T96.md#before-and-after"), label: "docs/tasks/T96.md" },
      { href: "/#brief", label: "The demo's briefs" },
    ],
  },
  {
    tag: "Replay",
    title: "Impossible tasks",
    body: "80 of 102 public agent runs replayed with zero setup. 43 of 52 fake fixes caught; all 6 genuine fixes passed; 8 legitimate test edits blocked until accepted.",
    verdicts: [] as const,
    points: ["22 runs excluded: they add files the dataset does not record", "Code-only checks: 5 of 11 caught on the held-out half"],
    links: [{ href: links.blob("docs/tasks/T89.md"), label: "docs/tasks/T89.md" }],
  },
  {
    tag: "Replay",
    title: "Merged agent pull requests",
    body: "20 merged Copilot pull requests in github/spec-kit and 31 agent commits in anthropics/claude-agent-sdk-python, judged after the fact by the gate.",
    verdicts: [] as const,
    points: ["4 spec-kit replays failed in the replay's own environment", "Changes already merged: not a measure of what reviewers would catch"],
    links: [
      { href: links.blob("docs/tasks/T90.md"), label: "docs/tasks/T90.md" },
      { href: links.blob("docs/tasks/T92.md"), label: "docs/tasks/T92.md" },
    ],
  },
  {
    tag: "Recorded run",
    title: "A real agent, sent back",
    body: "Claude Code with Haiku 4.5 was asked to change a function and make the whole suite pass. The Stop hook blocked it; the agent restored the code and test and asked for the test to be unlocked.",
    verdicts: ["BLOCKED"] as const,
    points: ["One recorded run, not a frequency"],
    links: [{ href: links.blob("docs/tasks/T80.md"), label: "docs/tasks/T80.md" }],
  },
  {
    tag: "Dogfooding",
    title: "OpenHarnX verifying itself",
    body: "Every change to OpenHarnX is verified READY under srt by an earlier installed version before it is committed. The 0.1.0 release candidate passed the gate in CI.",
    verdicts: ["READY"] as const,
    points: ["The commit message names the contract and the candidate digest", "The CI gate found four defects local runs missed"],
    links: [
      { href: links.blob("docs/tasks/T100.md"), label: "docs/tasks/T100.md" },
      { href: links.tree("contracts"), label: "contracts/" },
    ],
  },
];

export default function Examples() {
  return (
    <div className="sheet">
      <div className="wrap">
        <header className="page-head">
          <p className="eyebrow">Examples and evidence</p>
          <h1>Reproduce it, or read the record.</h1>
          <p>
            Every example here can be run from the repository or traced to a published record that states its exclusions
            and limits. Records live in <a href={links.tree("docs/tasks")}>docs/tasks</a>.
          </p>
        </header>
        <div className="example-grid">
          {examples.map((e) => (
            <article className="frame example" key={e.title}>
              <span className="tag tag--outline">{e.tag}</span>
              <h2>{e.title}</h2>
              <p>{e.body}</p>
              {e.verdicts.length ? (
                <p style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {e.verdicts.map((v) => (
                    <Verdict key={v} v={v} />
                  ))}
                </p>
              ) : null}
              <ul>
                {e.points.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
              <p style={{ display: "flex", gap: 16, flexWrap: "wrap", margin: 0 }}>
                {e.links.map((l) =>
                  l.href.startsWith("/") ? (
                    <Link key={l.href} href={l.href}>{l.label} →</Link>
                  ) : (
                    <a key={l.href} href={l.href}>{l.label} →</a>
                  ),
                )}
              </p>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
