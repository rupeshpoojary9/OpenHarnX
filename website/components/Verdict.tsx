export type VerdictName = "READY" | "NO REGRESSIONS" | "BLOCKED" | "UNKNOWN" | "INVALID" | "STALE";

const cls: Record<VerdictName, string> = {
  READY: "ready",
  "NO REGRESSIONS": "noreg",
  BLOCKED: "blocked",
  UNKNOWN: "unknown",
  INVALID: "invalid",
  STALE: "stale",
};

function Icon({ v }: { v: VerdictName }) {
  const p = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (v) {
    case "READY":
      return <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="m2.5 7.2 3 3 6-6.4" {...p} /></svg>;
    case "NO REGRESSIONS":
      return <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="M2 7h10" {...p} /><path d="m4.5 4.5-2.5 2.5 2.5 2.5" {...p} /></svg>;
    case "BLOCKED":
      return <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="m3 3 8 8M11 3l-8 8" {...p} /></svg>;
    case "UNKNOWN":
      return <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="M5 5a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6 1V9" {...p} /><circle cx="7" cy="11.6" r=".6" fill="currentColor" /></svg>;
    case "INVALID":
      return <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 1.8 12.6 12H1.4z" {...p} /><path d="M7 5.5v3" {...p} /></svg>;
    case "STALE":
      return <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden="true"><path d="M11.5 7A4.5 4.5 0 1 1 9.8 3.5" {...p} /><path d="M10 1.5v2.3h2.3" {...p} /></svg>;
  }
}

export function Verdict({ v, size }: { v: VerdictName; size?: "lg" }) {
  return (
    <span className={`verdict verdict--${cls[v]}${size ? " verdict--lg" : ""}`}>
      <Icon v={v} />
      {v}
    </span>
  );
}
