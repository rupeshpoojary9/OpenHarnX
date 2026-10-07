"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export const primaryNav = [
  { href: "/docs", label: "Docs", match: (p: string) => p.startsWith("/docs") && !/^\/docs\/(trust|roadmap)/.test(p) },
  { href: "/examples", label: "Examples", match: (p: string) => p.startsWith("/examples") },
  { href: "/docs/trust/security-model", label: "Trust", match: (p: string) => p.startsWith("/docs/trust") },
  { href: "/docs/roadmap", label: "Roadmap", match: (p: string) => p.startsWith("/docs/roadmap") },
];

export function NavLinks({ className }: { className?: string }) {
  const path = usePathname() ?? "/";
  return (
    <nav className={className} aria-label="Main">
      {primaryNav.map((n) => (
        <Link key={n.href} href={n.href} aria-current={n.match(path) ? "page" : undefined}>
          {n.label}
        </Link>
      ))}
      <a href="https://github.com/rupeshpoojary9/OpenHarnX">GitHub</a>
    </nav>
  );
}
