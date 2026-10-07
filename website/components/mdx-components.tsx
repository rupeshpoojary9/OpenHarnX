import type { MDXComponents } from "mdx/types";
import Link from "next/link";
import { CodeBlock, Cmd } from "./CodeBlock";
import { Callout } from "./Callout";
import { Verdict } from "./Verdict";
import { RepoFile } from "./RepoFile";

export const mdxComponents: MDXComponents = {
  pre: CodeBlock as MDXComponents["pre"],
  // Focusable so a wide table can be scrolled with the keyboard.
  table: (props) => (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Table">
      <table {...props} />
    </div>
  ),
  a: ({ href = "", ...props }) =>
    href.startsWith("/") ? <Link href={href} {...props} /> : <a href={href} {...props} />,
  // Task-list items (the roadmap): a labelled mark, not an unlabeled disabled checkbox.
  input: ({ type, checked, ...props }) =>
    type === "checkbox" ? (
      <span className={`task-mark${checked ? " done" : ""}`} role="img" aria-label={checked ? "Done" : "Not done"} />
    ) : (
      <input type={type} checked={checked} {...props} />
    ),
  Callout,
  Verdict,
  RepoFile,
  Cmd,
  Steps: ({ children }: { children: React.ReactNode }) => <div className="steps-wrap">{children}</div>,
};
