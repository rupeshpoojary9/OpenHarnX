import Link from "next/link";
import { Verdict } from "@/components/Verdict";

export default function NotFound() {
  return (
    <div className="sheet">
      <div className="wrap notfound">
        <Verdict v="UNKNOWN" size="lg" />
        <h1>No page at this address.</h1>
        <p>
          The link may be old or mistyped. Search the documentation with <kbd>/</kbd> or <kbd>⌘ K</kbd>, or start from
          one of these:
        </p>
        <ul>
          <li><Link href="/docs">Documentation <span aria-hidden="true">→</span></Link></li>
          <li><Link href="/docs/installation">Installation <span aria-hidden="true">→</span></Link></li>
          <li><Link href="/docs/reference/cli">CLI reference <span aria-hidden="true">→</span></Link></li>
          <li><Link href="/">Home <span aria-hidden="true">→</span></Link></li>
        </ul>
      </div>
    </div>
  );
}
