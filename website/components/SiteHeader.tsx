import Link from "next/link";
import { Logo } from "./Logo";
import { NavLinks } from "./NavLinks";
import { ThemeToggle } from "./ThemeToggle";
import { SearchButton } from "./SearchButton";
import { links, release } from "@/lib/site";

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="wrap site-header__inner">
        <Link href="/" className="brand" aria-label="OpenHarnX home">
          <Logo />
        </Link>
        <a className="release-pill" href={links.release} title={`Released ${release.date}`}>
          {release.tag}
        </a>
        <NavLinks className="main-nav" />
        <div className="header-actions">
          <SearchButton />
          <ThemeToggle />
          <Link className="btn btn--primary btn--sm" href="/docs/installation">
            Get started
          </Link>
          <details className="mobile-menu">
            <summary className="icon-btn" aria-label="Menu">
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.4" />
              </svg>
            </summary>
            <div className="mobile-menu__panel">
              <NavLinks />
              <Link className="btn btn--primary" href="/docs/installation">
                Get started
              </Link>
            </div>
          </details>
        </div>
      </div>
    </header>
  );
}
