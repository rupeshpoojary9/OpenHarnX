import fs from "node:fs/promises";
import path from "node:path";
import GithubSlugger from "github-slugger";
import { compile, siteRoot, type TocEntry } from "@/lib/docs";
import { mdxComponents } from "./mdx-components";
import { Callout } from "./Callout";

type Opt = {
  flags: string[];
  positional: boolean;
  metavar: string | null;
  takes_value: boolean;
  choices: string[] | null;
  default: string | number | null;
  required: boolean;
  repeatable: boolean;
  help: string | null;
};
type Command = { command: string; help: string; usage: string; options: Opt[] };

const experimental = /^ohx (bug|trace)\b/;

// Notes written for this site, next to what the parser says. Keyed by command.
const notes: Record<string, string> = {
  "ohx doctor": "Checks Python (3.12 or newer), git and the platform. Exit 0 when every required check passes, 10 when one fails. In 0.1.0 it does not check `srt` or Node; `ohx verify --sandbox srt` reports a missing `srt` itself.",
  "ohx init": "Creates the evidence store for the repository under `~/.openharnx` (or `OHX_HOME`). With `--lock-tests`, the suite as it is now becomes the contract and its per-test results become the baseline. Run it again to accept a deliberate test change.",
  "ohx hook install": "Adds a Stop hook to `.claude/settings.local.json` in the current repository. Keep that file out of git: it holds paths on your machine.",
  "ohx contract accept": "Validates a contract TOML file you wrote and accepts it: the acceptance tests it names are copied into the store and the regression baseline is recorded.",
  "ohx contract new": "Writes `contracts/NNNN-<title>.toml` from `ohx.toml` and the acceptance tests you name. `--acceptance` can be given more than once. `--mode` defaults to `bugfix`. With `--accept` the contract is accepted at once.",
  "ohx verify": "Runs every check of the accepted contract against the working tree and prints the report. Exit 0 for READY and NO REGRESSIONS, 10 for BLOCKED, UNKNOWN, INVALID or STALE, 2 for a usage error such as `--sandbox srt` without `srt` installed.",
  "ohx approve-tests": "Signs \"test changes approved for commit X\" with your SSH key and stores the signature as a git note in `refs/notes/ohx-approvals`, or in a file with `--out`.",
  "ohx history": "Walks recent commits and writes what the gate would have said about each to `ohx-history/history.md` and `.json`. Commits made by coding agents are marked.",
  "ohx gate": "For CI. Judges the checked-out change against `--base`: the base's tests run as locked copies, the base's `ohx.toml` is the policy, and nothing the change adds to them is used. Writes `report.json`, `report.md` and `evidence/` to `--out`.",
  "ohx audit": "Lists who did what from the evidence store: contracts accepted, suites locked, verifications and the files they touched.",
  "ohx report": "Prints the latest report for the repository, re-checking it against the store. A report made before the files changed shows as STALE.",
  "ohx store check": "Verifies the hash chain, every record's digest and the signatures. `--signer` pins the key that must have signed.",
};

function optName(o: Opt) {
  if (o.positional) return o.metavar ?? o.flags[0];
  const value = o.takes_value ? ` ${o.choices ? `{${o.choices.join(",")}}` : (o.metavar ?? o.flags[0].replace(/^--/, "").toUpperCase())}` : "";
  return o.flags.join(", ") + value;
}

export async function cliData() {
  return JSON.parse(await fs.readFile(path.join(/*turbopackIgnore: true*/ siteRoot, "content/generated/cli.json"), "utf8")) as {
    version: string;
    commands: Command[];
  };
}

export function cliToc(commands: Command[]): TocEntry[] {
  const s = new GithubSlugger();
  return commands.map((c) => ({ id: s.slug(c.command), text: c.command, depth: 2 }));
}

export async function CliReference() {
  const { version, commands } = await cliData();
  const toc = cliToc(commands);
  const rendered = await Promise.all(
    commands.map(async (c) => {
      const note = notes[c.command];
      return note ? (await compile(note, { format: "md" })).Content : null;
    }),
  );
  return (
    <div className="prose">
      <p>
        Generated from the argument parser of <code>ohx {version}</code>, so every command and option below exists in
        that release. <code>ohx --help</code> and <code>ohx &lt;command&gt; --help</code> print the same. Global options:{" "}
        <code>--version</code> and <code>--help</code>.
      </p>
      <h2 id="exit-codes">Exit codes</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Code</th><th>Meaning</th></tr></thead>
          <tbody>
            <tr><td><code>0</code></td><td>Success: READY or NO REGRESSIONS</td></tr>
            <tr><td><code>10</code></td><td>A valid result that does not pass: BLOCKED, UNKNOWN, INVALID or STALE</td></tr>
            <tr><td><code>2</code></td><td>Usage or input error</td></tr>
            <tr><td><code>1</code></td><td>Internal failure</td></tr>
          </tbody>
        </table>
      </div>
      {commands.map((c, i) => {
        const Note = rendered[i];
        return (
          <section key={c.command} className="cli-cmd" aria-labelledby={toc[i].id}>
            <div className="cli-cmd__head">
              <h2 id={toc[i].id}>
                {c.command}
                <a className="anchor" href={`#${toc[i].id}`} aria-label={`Link to ${c.command}`}>#</a>
              </h2>
              <p>{c.help.charAt(0).toUpperCase() + c.help.slice(1)}.</p>
            </div>
            <pre className="cli-usage">{c.usage}</pre>
            {c.options.length ? (
              <table className="cli-opts">
                <tbody>
                  {c.options.map((o) => (
                    <tr key={o.flags.join()}>
                      <td>
                        {optName(o)}
                        {o.required && !o.positional ? <span className="req">required</span> : null}
                      </td>
                      <td>
                        {o.help ? o.help.charAt(0).toUpperCase() + o.help.slice(1) : o.positional ? "Argument." : ""}
                        {o.repeatable ? " Repeatable." : ""}
                        {o.default !== null && o.default !== undefined ? (
                          <> Default: <code>{String(o.default)}</code>.</>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {experimental.test(c.command) || Note ? (
              <div className="cli-extra">
                {experimental.test(c.command) ? (
                  <Callout type="experimental">
                    <p>Outside the {version} release boundary. Works and is tested, with no claim of protection. <code>ohx bug</code> drives a coding agent, which calls a model and can cost money (<code>--budget</code> caps it).</p>
                  </Callout>
                ) : null}
                {Note ? <Note components={mdxComponents} /> : null}
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}
