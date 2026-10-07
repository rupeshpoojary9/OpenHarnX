import type { ComponentProps } from "react";
import { CopyButton } from "./CopyButton";

const names: Record<string, string> = {
  bash: "shell", sh: "shell", shell: "shell", console: "shell", yaml: "yaml", yml: "yaml",
  toml: "toml", text: "text", json: "json", groovy: "groovy", python: "python", markdown: "markdown",
};

export function CodeBlock(props: ComponentProps<"pre"> & { "data-lang"?: string }) {
  const lang = props["data-lang"] ?? "text";
  return (
    <div className="code">
      <div className="code__bar">
        <span>{names[lang] ?? lang}</span>
        <CopyButton />
      </div>
      <pre {...props} />
    </div>
  );
}

/** A one-line shell command with a copy button. */
export function Cmd({ children }: { children: string }) {
  return (
    <span className="cmd">
      <code>{children}</code>
      <CopyButton text={children} />
    </span>
  );
}
