import Link from "next/link";
import { Logo } from "./Logo";
import { links, release } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="wrap site-footer__grid">
        <div>
          <Logo height={20} />
          <p className="fine">
            An open-source verifier for changes written by coding agents. Apache-2.0. Release{" "}
            <a href={links.release}>{release.tag}</a>, {release.date}. A verdict is evidence about the checks
            that ran. It never authorizes a merge, a deploy or a release.
          </p>
        </div>
        <div>
          <h2>Start</h2>
          <ul>
            <li><Link href="/docs/installation">Installation</Link></li>
            <li><Link href="/docs/run-the-demo">Run the demo</Link></li>
            <li><Link href="/docs/first-verification">Verify your first change</Link></li>
            <li><Link href="/docs/reference/cli">CLI reference</Link></li>
          </ul>
        </div>
        <div>
          <h2>Trust</h2>
          <ul>
            <li><Link href="/docs/trust/security-model">Security model</Link></li>
            <li><Link href="/docs/trust/threat-model">Threat model</Link></li>
            <li><Link href="/docs/trust/data-handling">Data handling</Link></li>
            <li><Link href="/docs/trust/vulnerability-reporting">Report a vulnerability</Link></li>
          </ul>
        </div>
        <div>
          <h2>Project</h2>
          <ul>
            <li><a href={links.github}>GitHub</a></li>
            <li><a href={links.trialReport}>Send a trial report</a></li>
            <li><Link href="/docs/roadmap">Roadmap</Link></li>
            <li><Link href="/docs/contributing">Contributing</Link></li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
