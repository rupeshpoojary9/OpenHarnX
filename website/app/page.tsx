import Link from "next/link";
import { Demo } from "@/components/Demo";
import { BriefPreview, type BriefTab } from "@/components/BriefPreview";
import { Cmd } from "@/components/CodeBlock";
import { mdxComponents } from "@/components/mdx-components";
import { briefs, capturedText, demoSteps } from "@/lib/demo";
import { compile } from "@/lib/docs";
import { links, release } from "@/lib/site";

export const metadata = { alternates: { canonical: "/" } };

function FlowDiagram() {
  const nodes = [
    { x: 60, label: "LOCK", sub: "agreed tests copied away" },
    { x: 333, label: "CHANGE", sub: "your agent, as usual" },
    { x: 606, label: "VERIFY", sub: "locked copies, in srt" },
    { x: 880, label: "REVIEW", sub: "brief + evidence" },
  ];
  return (
    <svg className="flow-diagram" viewBox="0 0 940 150" role="img" aria-labelledby="flow-title">
      <title id="flow-title">
        Lock, then change, then verify, then review. A blocked verification goes back to the change step with what failed.
      </title>
      <path className="rule" d="M 60 40 H 880" strokeWidth="1" />
      <path className="back" d="M 606 52 C 606 112, 333 112, 333 52" strokeWidth="1.2" strokeDasharray="4 4" />
      <path className="back" d="M 327 60 L 333 51 L 339 60" strokeWidth="1.2" />
      <text className="back-label" x="470" y="140" textAnchor="middle" style={{ fill: "var(--blocked)" }}>
        BLOCKED: back to the agent with what failed
      </text>
      {nodes.map((n, i) => (
        <g key={n.label}>
          <rect className={`node${i === 2 ? " node--accent" : ""}`} x={n.x - 34} y={26} width={68} height={28} strokeWidth={i === 2 ? 2 : 1} />
          <text x={n.x} y={44.5} textAnchor="middle">{n.label}</text>
          <text className="small" x={n.x} y={14} textAnchor="middle">{n.sub}</text>
        </g>
      ))}
      <circle className="pulse" r="4" cx="0" cy="0" />
    </svg>
  );
}

export default async function Home() {
  const steps = demoSteps();
  const tabs: BriefTab[] = await Promise.all(
    briefs().map(async (b) => ({
      key: b.key,
      verdict: b.verdict,
      exit: b.exit,
      summary: b.summary,
      raw: b.raw,
      sections: await Promise.all(
        b.sections.map(async (s) => {
          // Shown as text: placeholders such as <tmp> and names such as __pycache__ are not markup.
          // Output links point to evidence files beside report.md, which are not published
          // here, so they are shown as the file they name.
          const md = s.md
            .replace(/<tmp>/g, "&lt;tmp&gt;")
            .replace(/__pycache__/g, "\\_\\_pycache\\_\\_")
            .replace(/\[output\]\((evidence\/[^)]+)\)/g, "output: `$1`");
          const { Content } = await compile(md, { format: "md" });
          return { title: s.title, kind: s.kind, body: <Content components={{ table: mdxComponents.table }} /> };
        }),
      ),
    })),
  );

  return (
    <div className="sheet">
      {/* Hero */}
      <section className="hero">
        <div className="wrap">
          <div className="hero__inner">
            <div className="hero__tags">
              <span className="tag">Open source · Apache-2.0</span>
              <span className="tag tag--outline">No model calls</span>
            </div>
            <h1>
              Your coding agent says the tests pass. <em>Check what actually passed.</em>
            </h1>
            <div className="hero__row">
              <div>
                <p className="hero__lede">
                  OpenHarnX protects agreed tests and produces a review brief showing what was verified, what remains
                  uncertain and what needs your judgment.
                </p>
                <div className="hero__actions">
                  <Link className="btn btn--primary" href="/docs/installation">
                    Get started <span className="arrow" aria-hidden="true">→</span>
                  </Link>
                  <a className="btn" href="#demo">
                    Watch the demo <span className="arrow" aria-hidden="true">↓</span>
                  </a>
                </div>
              </div>
              <dl className="spec" aria-label="Current release">
                <dt>Release</dt>
                <dd>
                  <a href={links.release}>{release.tag}</a> · {release.date}
                </dd>
                <dt>Supported</dt>
                <dd>Python + pytest · macOS arm64 locally · Linux in CI</dd>
                <dt>Sandbox</dt>
                <dd>srt {release.srt}</dd>
                <dt>Works with</dt>
                <dd>any agent via CLI or CI · Claude Code hook built in</dd>
                <dt>Experimental</dt>
                <dd>TypeScript, JavaScript, Go</dd>
              </dl>
            </div>
          </div>
        </div>
      </section>

      {/* Demonstration */}
      <section className="section" id="demo" aria-labelledby="demo-title">
        <div className="wrap">
          <div className="section-head">
            <h2 id="demo-title">Green tests, blocked change.</h2>
            <p>
              A coding agent breaks existing behaviour, edits and skips the tests that would show it, and reports success.
              Plain pytest agrees. OpenHarnX runs the locked copies instead.
            </p>
          </div>
          <Demo steps={steps} />
          <div className="demo__foot">
            <span>
              READY additionally requires acceptance tests agreed before the change. Without them, the best a change can
              get is NO REGRESSIONS. <a href="#brief">See the READY brief</a>.
            </span>
            <span>
              <a href={links.cheatDemo}>Reproduce it: examples/cheat-demo</a> ·{" "}
              <Link href="/docs/run-the-demo">run the demo</Link>
            </span>
          </div>
          <details className="transcript">
            <summary>Read the full transcript as text</summary>
            <pre>{capturedText("transcript.txt")}</pre>
          </details>
        </div>
      </section>

      {/* How it works */}
      <section className="section" aria-labelledby="how-title">
        <div className="wrap">
          <div className="section-head">
            <h2 id="how-title">Lock. Change. Verify. Review.</h2>
            <p>
              The tests that must keep passing are decided before the agent starts, and they run where the agent's
              code cannot touch them.
            </p>
          </div>
          <FlowDiagram />
          <ol className="flow" style={{ listStyle: "none", margin: 0, padding: 0 }}>
            <li className="flow__step">
              <span className="flow__n">1</span>
              <h3>Lock</h3>
              <p>
                The existing suite, or acceptance tests agreed for the task, are copied into OpenHarnX's store. A
                baseline records which tests passed.
              </p>
              <code>ohx init --lock-tests</code>
            </li>
            <li className="flow__step">
              <span className="flow__n">2</span>
              <h3>Change</h3>
              <p>Your agent works as it normally does. Any agent: OpenHarnX reads files and test runs, not the agent.</p>
            </li>
            <li className="flow__step">
              <span className="flow__n">3</span>
              <h3>Verify</h3>
              <p>
                The locked copies run in the srt sandbox, from an interpreter the change cannot replace. Per-test results
                are compared with the baseline and weakening is flagged.
              </p>
              <code>ohx verify --sandbox srt</code>
            </li>
            <li className="flow__step">
              <span className="flow__n">4</span>
              <h3>Review</h3>
              <p>
                A verdict and a brief bound to the exact files judged. Blocked work goes back to the agent; passing work
                comes to you with what is left to decide.
              </p>
              <code>ohx report</code>
            </li>
          </ol>
        </div>
      </section>

      {/* Review brief */}
      <section className="section" id="brief" aria-labelledby="brief-title">
        <div className="wrap">
          <div className="section-head">
            <h2 id="brief-title">A brief that says what it does not know.</h2>
            <p>
              Every report opens with five sections, built from records with no model involved. Facts, limits and the
              decisions left to you are kept apart, and every verified claim links to the check's output.
            </p>
          </div>
          <BriefPreview tabs={tabs} />
        </div>
      </section>

      {/* Fit */}
      <section className="section" aria-labelledby="fit-title">
        <div className="wrap">
          <div className="section-head">
            <h2 id="fit-title">Keep the agent you use.</h2>
            <p>
              Verification depends on the files and the test runs, not on which agent wrote the code. Integrations differ,
              and this is what exists today.
            </p>
          </div>
          <div className="fit">
            <div className="fit__col">
              <span className="tag tag--accent">Built-in hook</span>
              <h3>Claude Code</h3>
              <p>
                A Stop hook verifies when the agent says it is done. A blocked agent gets the failing tests and error lines
                back, up to three times; you get the verdict. Tested end to end.
              </p>
              <span className="cmd-wrap"><Cmd>ohx hook install</Cmd></span>
              <p style={{ marginTop: 12 }}><Link className="more" href="/docs/workflows/claude-code-hook">Use the Claude Code hook →</Link></p>
            </div>
            <div className="fit__col">
              <span className="tag tag--outline">CLI</span>
              <h3>Codex, Cursor, OpenCode and others</h3>
              <p>
                Run <code>ohx verify</code> when the agent finishes and use its exit code. No built-in integration yet,
                and not tested with these agents yet.
              </p>
              <span className="cmd-wrap"><Cmd>ohx verify --sandbox srt</Cmd></span>
              <p style={{ marginTop: 12 }}><Link className="more" href="/docs/workflows/other-agents">Use other agents →</Link></p>
            </div>
            <div className="fit__col">
              <span className="tag tag--outline">CI gate</span>
              <h3>Any agent that opens pull requests</h3>
              <p>
                The base branch's tests run against the change and the base's policy decides. A GitHub Action, with GitLab
                CI and Jenkins examples. GitHub Copilot's merged pull requests were checked in replays.
              </p>
              <Link className="more" href="/docs/ci/github-actions">Add the CI gate →</Link>
            </div>
          </div>
          <p className="fit__note">
            OpenHarnX checks one agent's work. It is not an agent, and it does not plan, delegate or orchestrate agents.
          </p>
        </div>
      </section>

      {/* Evidence */}
      <section className="section" aria-labelledby="evidence-title">
        <div className="wrap">
          <div className="section-head">
            <h2 id="evidence-title">Evidence, with its denominators.</h2>
            <p>
              Replays of public agent work, published with what OpenHarnX missed, what it blocked that was legitimate and
              where the replay itself failed. Each figure links to its record.
            </p>
          </div>
          <div className="records">
            <article className="record">
              <div>
                <span className="tag tag--outline">Replay · T89</span>
                <h3>Impossible tasks</h3>
                <p className="src">
                  <a href="https://github.com/DimitrovK/impossible-tasks">DimitrovK/impossible-tasks</a>: 102 runs of five
                  models on 8 impossible and 2 solvable projects. <a href={links.blob("docs/tasks/T89.md")}>Record</a>
                </p>
              </div>
              <ul className="figures">
                <li><span className="num">43<small>/52</small></span><span className="what">fake fixes caught with zero setup, of the 80 runs that could be replayed</span></li>
                <li><span className="num">26<small>/26</small></span><span className="what">fakes that changed the tests were caught</span></li>
                <li><span className="num">17<small>/26</small></span><span className="what">fakes that changed only the code were caught; 5 of 11 on the held-out half</span></li>
                <li><span className="num">6<small>/6</small></span><span className="what">genuine fixes passed</span></li>
              </ul>
              <div className="limits">
                <h4>Exclusions and limits</h4>
                <ul>
                  <li>22 of 102 runs were excluded: they add files the dataset does not record.</li>
                  <li>9 fakes passed: 6 leave a test failing as before, which zero setup reads as nothing regressed; 3 change behaviour only a specification could tell apart.</li>
                  <li>The checks for code-only tricks were written from half of the runs.</li>
                  <li>8 legitimate test edits were blocked until a person accepted them.</li>
                </ul>
              </div>
            </article>
            <article className="record">
              <div>
                <span className="tag tag--outline">Replay · T90, T92</span>
                <h3>Merged agent pull requests</h3>
                <p className="src">
                  Judged after the fact by the gate. <a href={links.blob("docs/tasks/T90.md")}>T90</a> ·{" "}
                  <a href={links.blob("docs/tasks/T92.md")}>T92</a>
                </p>
              </div>
              <ul className="figures">
                <li><span className="num">9<small>/20</small></span><span className="what">merged Copilot pull requests in github/spec-kit passed; 7 more passed once their intended test changes were approved</span></li>
                <li><span className="num">28<small>/31</small></span><span className="what">agent commits in anthropics/claude-agent-sdk-python passed, most of them changelog updates; 3 were intended test changes</span></li>
              </ul>
              <div className="limits">
                <h4>Exclusions and limits</h4>
                <ul>
                  <li>4 of the 20 spec-kit pull requests failed because of the replay's own environment.</li>
                  <li>These are changes people had already merged. They show how often legitimate work passes or needs approval, not what reviewers would have caught.</li>
                </ul>
              </div>
            </article>
            <article className="record">
              <div>
                <span className="tag tag--outline">Dogfooding · T100</span>
                <h3>Its own development</h3>
                <p className="src">
                  Every change verified by an earlier installed version. <a href={links.blob("docs/tasks/T100.md")}>Record</a>
                </p>
              </div>
              <ul className="figures">
                <li><span className="num">READY</span><span className="what">under srt before each commit; the commit names the contract and the digest judged</span></li>
                <li><span className="num">4</span><span className="what">defects the CI gate found in the 0.1.0 release candidate that local runs had missed</span></li>
              </ul>
              <div className="limits">
                <h4>Limits</h4>
                <ul>
                  <li>One project, one maintainer. Agreement with its own checks is not independent validation.</li>
                </ul>
              </div>
            </article>
          </div>
          <div className="not-claimed">
            <div><strong>No production users yet.</strong>Tested on its own development, replays of public agent work and simulated users.</div>
            <div><strong>No measured time savings.</strong>Whether the brief saves review time is not measured. A study with reviewers is on the roadmap.</div>
            <div><strong>No guarantee.</strong>A passing verdict is evidence about the checks that ran. It does not make a change safe or authorize a merge.</div>
          </div>
        </div>
      </section>

      {/* Invitation */}
      <section className="invite" aria-labelledby="invite-title">
        <div className="wrap">
          <h2 id="invite-title">
            Try OpenHarnX on one change. <span className="quiet">Tell us what it caught and where it got in your way.</span>
          </h2>
          <div className="hero__actions">
            <Link className="btn btn--primary" href="/docs/first-verification">
              Verify your first change <span className="arrow" aria-hidden="true">→</span>
            </Link>
            <a className="btn" href={links.trialReport}>
              Send a trial report
            </a>
            <a className="btn" href={links.github}>
              GitHub
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
