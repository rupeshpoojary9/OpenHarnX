// Build-time data for the homepage demonstration and brief preview. Everything here
// is read from the cheat-demo fixtures in the repository (examples/cheat-demo) and from
// output captured with the released ohx (content/demo, see scripts/capture-demo.sh).
import fs from "node:fs";
import path from "node:path";
import { repoRoot, siteRoot } from "./docs";

const fixtures = path.join(/*turbopackIgnore: true*/ repoRoot, "examples", "cheat-demo");
const captured = path.join(/*turbopackIgnore: true*/ siteRoot, "content", "demo");

const read = (p: string) => fs.readFileSync(p, "utf8");
const fixture = (p: string) => read(path.join(/*turbopackIgnore: true*/ fixtures, p));
export const capturedText = (name: string) => read(path.join(/*turbopackIgnore: true*/ captured, name)).replace(/\n$/, "");

export type Line = { text: string; kind?: "prompt" | "dim" | "add" | "del" | "fail" | "ok" | "say" };

/** Line diff by longest common subsequence; the fixture files are a dozen lines each. */
export function diff(a: string, b: string): Line[] {
  const x = a.replace(/\n$/, "").split("\n");
  const y = b.replace(/\n$/, "").split("\n");
  const n = x.length;
  const m = y.length;
  const L = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: Line[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && x[i] === y[j]) {
      out.push({ text: `  ${x[i]}`, kind: "dim" });
      i++;
      j++;
    } else if (j < m && (i >= n || L[i][j + 1] >= L[i + 1][j])) {
      out.push({ text: `+ ${y[j]}`, kind: "add" });
      j++;
    } else {
      out.push({ text: `- ${x[i]}`, kind: "del" });
      i++;
    }
  }
  // Drop unchanged runs longer than two lines away from a change, so a step stays short.
  return out.filter((l, k) => {
    if (l.kind !== "dim") return true;
    const near = out.slice(Math.max(0, k - 2), k + 3).some((o) => o.kind === "add" || o.kind === "del");
    return near;
  });
}

/** The lines of one numbered step of the demo script's own transcript. */
function transcriptStep(n: number): string[] {
  const t = capturedText("transcript.txt");
  const start = t.indexOf(`\n${n}. `) >= 0 ? t.indexOf(`\n${n}. `) + 1 : t.indexOf(`${n}. `);
  const end = t.indexOf(`\n${n + 1}. `, start);
  return t
    .slice(start, end > 0 ? end : undefined)
    .split("\n")
    .slice(1)
    .filter((l) => l.trim() && !l.startsWith("Plain pytest passed") && !l.startsWith("skipped locked"));
}

function classify(raw: string): Line {
  const text = raw.replace(/^ {2}/, "");
  if (text.startsWith("$ ")) return { text, kind: "prompt" };
  if (text.startsWith("agent:")) return { text, kind: "say" };
  if (/\| fail \|/.test(text) || /BLOCKED/.test(text)) return { text, kind: "fail" };
  if (/NO REGRESSIONS|READY|passed/.test(text)) return { text, kind: "ok" };
  if (/Saved to|^ {2}store|urn:ohx/.test(text)) return { text, kind: "dim" };
  return { text };
}

export type Cell = "pass" | "fail" | "skip" | "edited" | "none" | "baseline" | "na";
export type LedgerRow = { name: string; note?: string; plain: Cell; ohx: Cell; ohxNote?: string };
export type DemoStep = {
  title: string;
  caption: string;
  lines: Line[];
  ledger: LedgerRow[];
  plainSummary: string | null;
  verdict: { name: "BLOCKED" | "NO REGRESSIONS"; exit: string } | null;
};

export function demoSteps(): DemoStep[] {
  const s2 = transcriptStep(2).map(classify);
  const s3 = transcriptStep(3).map(classify);
  const s4 = transcriptStep(4).map(classify);
  const say = s3.find((l) => l.kind === "say")!;
  const cheatPytest = s3.slice(s3.findIndex((l) => l.text === "$ pytest"), s3.findIndex((l) => l.text === "$ pytest") + 2);
  const verifyAt = s3.findIndex((l) => l.text.startsWith("$ ohx verify"));
  const blockedVerify = s3.slice(verifyAt);
  const fixVerifyAt = s4.findIndex((l) => l.text.startsWith("$ ohx verify"));
  const exitBlocked = capturedText("exit-blocked.txt");
  const exitNoreg = capturedText("exit-no-regressions.txt");

  const locked = ["test_line_total", "test_fixed_coupon", "test_coupon_never_makes_total_negative"];
  const rows = (plain: Cell[], ohx: Cell[], notes: (string | undefined)[] = [], ohxNotes: (string | undefined)[] = []) =>
    locked.map((name, i) => ({ name, plain: plain[i], ohx: ohx[i], note: notes[i], ohxNote: ohxNotes[i] }));
  const weak = (ohx: Cell, ohxNote?: string): LedgerRow => ({ name: "weakening check", plain: "na", ohx, ohxNote });

  return [
    {
      title: "Lock the suite",
      caption: "A small shop's repository with three passing tests. The owner locks them: from now on they are the contract.",
      lines: s2,
      ledger: [...rows(["pass", "pass", "pass"], ["baseline", "baseline", "baseline"]), weak("baseline")],
      plainSummary: capturedText("pytest-start.txt"),
      verdict: null,
    },
    {
      title: "The change breaks existing behaviour",
      caption: "Asked to add percentage coupons, the agent rewrites order_total. Fixed coupons no longer exist.",
      lines: [{ text: "pricing.py", kind: "dim" }, ...diff(fixture("project/pricing.py"), fixture("cheat/pricing.py"))],
      ledger: [...rows(["none", "none", "none"], ["baseline", "baseline", "baseline"]), weak("baseline")],
      plainSummary: null,
      verdict: null,
    },
    {
      title: "Its tests are edited and skipped",
      caption: "It rewrites the fixed-coupon test to expect the new output and skips the negative-total test as obsolete.",
      lines: [
        { text: "tests/test_pricing.py", kind: "dim" },
        ...diff(fixture("project/tests/test_pricing.py"), fixture("cheat/tests/test_pricing.py")),
      ],
      ledger: [
        ...rows(["none", "edited", "edited"], ["baseline", "baseline", "baseline"], [undefined, "assertion rewritten", "skip marker added"]),
        weak("baseline"),
      ],
      plainSummary: null,
      verdict: null,
    },
    {
      title: "Ordinary tests look green",
      caption: "The agent reports success, and plain pytest agrees.",
      lines: [say, ...cheatPytest],
      ledger: [...rows(["pass", "pass", "skip"], ["baseline", "baseline", "baseline"], [undefined, "rewritten copy", "skipped"]), weak("baseline")],
      plainSummary: capturedText("pytest-cheat.txt"),
      verdict: null,
    },
    {
      title: "OpenHarnX: BLOCKED",
      caption: "The locked copies run against the change. Two tests that passed before now fail, and the new skip is flagged.",
      lines: blockedVerify,
      ledger: [
        ...rows(
          ["pass", "pass", "skip"],
          ["pass", "fail", "fail"],
          [undefined, "rewritten copy", "skipped"],
          [undefined, "passed at acceptance, fails now", "passed at acceptance, fails now"],
        ),
        weak("fail", "1 new skip or xfail"),
      ],
      plainSummary: capturedText("pytest-cheat.txt"),
      verdict: { name: "BLOCKED", exit: exitBlocked },
    },
    {
      title: "The genuine fix: NO REGRESSIONS",
      caption: "Percentage coupons added, fixed coupons kept, two new tests. Everything that passed before still passes.",
      lines: [
        { text: "pricing.py", kind: "dim" },
        ...diff(fixture("project/pricing.py"), fixture("fix/pricing.py")),
        ...s4.slice(s4.findIndex((l) => l.text === "$ pytest"), s4.findIndex((l) => l.text === "$ pytest") + 2),
        ...s4.slice(fixVerifyAt),
      ],
      ledger: [...rows(["pass", "pass", "pass"], ["pass", "pass", "pass"]), weak("pass")],
      plainSummary: capturedText("pytest-fix.txt"),
      verdict: { name: "NO REGRESSIONS", exit: exitNoreg },
    },
  ];
}

// ---------- Review briefs ----------

export type BriefSection = { title: string; kind: "fact" | "limit" | "decision"; md: string };
export type Brief = { key: string; verdict: "BLOCKED" | "NO REGRESSIONS" | "READY"; exit: string; summary: string; sections: BriefSection[]; raw: string };

const kinds: Record<string, BriefSection["kind"]> = {
  "Requested outcome": "fact",
  "What changed": "fact",
  "What was verified": "fact",
  "What remains unverified": "limit",
  "Decisions for you": "decision",
};

export function briefs(): Brief[] {
  const make = (key: string, file: string, exitFile: string, summary: string): Brief => {
    const raw = capturedText(file);
    const head = /^# OpenHarnX report: (.+)$/m.exec(raw)![1] as Brief["verdict"];
    const parts = raw.split(/^## /m).slice(1);
    const sections = parts
      .map((p) => {
        const nl = p.indexOf("\n");
        return { title: p.slice(0, nl).trim(), md: p.slice(nl + 1).trim() };
      })
      .filter((s) => s.title in kinds)
      .map((s) => ({ ...s, kind: kinds[s.title] }));
    return { key, verdict: head, exit: capturedText(exitFile), summary, sections, raw };
  };
  return [
    make("blocked", "blocked.md", "exit-blocked.txt", "The cheating change: locked tests edited and skipped."),
    make("no-regressions", "no-regressions.md", "exit-no-regressions.txt", "The genuine fix, with only the existing suite locked."),
    make("ready", "ready.md", "exit-ready.txt", "The same fix, with acceptance tests agreed before the change."),
  ];
}
