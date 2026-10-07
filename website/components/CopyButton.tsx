"use client";
import { useState } from "react";

/** Copies the code of the nearest .code block, or `text` when given. */
export function CopyButton({ text, label = "Copy" }: { text?: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <button
      type="button"
      className="copy-btn"
      data-copied={state === "copied"}
      aria-label={state === "copied" ? "Copied" : `${label} to clipboard`}
      onClick={async (e) => {
        const value =
          text ??
          (e.currentTarget.closest(".code, .cmd")?.querySelector("pre, code") as HTMLElement | null)?.innerText ??
          "";
        try {
          await navigator.clipboard.writeText(value.replace(/\n$/, ""));
          setState("copied");
        } catch {
          setState("failed");
        }
        setTimeout(() => setState("idle"), 1600);
      }}
    >
      <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true">
        {state === "copied" ? (
          <path d="m3 8.5 3 3 7-7" fill="none" stroke="currentColor" strokeWidth="1.8" />
        ) : (
          <>
            <rect x="5" y="5" width="8.5" height="8.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
            <path d="M3 10.5V3h7.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
          </>
        )}
      </svg>
      <span aria-live="polite">{state === "copied" ? "Copied" : state === "failed" ? "Select and copy" : label}</span>
    </button>
  );
}
