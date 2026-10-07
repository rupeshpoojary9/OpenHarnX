// The documentation tree. Each page has exactly one source:
// - "mdx": a guide written for this site, in website/content/docs/<file>
// - "repo": a file maintained in the OpenHarnX repository itself, rendered as is
// - "cli": generated from the released command's own parser (content/generated/cli.json)

export type Source =
  | { kind: "mdx"; file: string }
  | { kind: "repo"; file: string }
  | { kind: "cli" };

export type NavItem = {
  slug: string; // "" is /docs
  title: string;
  source: Source;
  badge?: "experimental" | "repo";
};

export type NavSection = { title: string; items: NavItem[] };

const mdx = (slug: string, title: string, badge?: NavItem["badge"]): NavItem => ({
  slug,
  title,
  source: { kind: "mdx", file: `${slug || "introduction"}.mdx` },
  badge,
});

const fromRepo = (slug: string, title: string, file: string): NavItem => ({
  slug,
  title,
  source: { kind: "repo", file },
  badge: "repo",
});

export const nav: NavSection[] = [
  {
    title: "Getting started",
    items: [
      mdx("", "Introduction"),
      mdx("supported-environments", "Supported environments"),
      mdx("installation", "Installation"),
      mdx("run-the-demo", "Run the demo"),
      mdx("first-verification", "Verify your first change"),
    ],
  },
  {
    title: "Daily workflows",
    items: [
      mdx("workflows/protect-existing-tests", "Protect an existing test suite"),
      mdx("workflows/acceptance-criteria", "Define acceptance criteria"),
      mdx("workflows/claude-code-hook", "Use the Claude Code hook"),
      mdx("workflows/other-agents", "Use other coding agents"),
      mdx("workflows/approve-test-changes", "Approve intentional test changes"),
      mdx("workflows/read-reports", "Read reports and verify again"),
    ],
  },
  {
    title: "CI",
    items: [
      mdx("ci/github-actions", "GitHub Actions"),
      mdx("ci/gitlab", "GitLab CI"),
      mdx("ci/jenkins", "Jenkins"),
      mdx("ci/trust-and-required-checks", "Trusted base and required checks"),
      mdx("ci/evidence-and-signing", "Evidence artifacts and signing"),
    ],
  },
  {
    title: "Concepts and reference",
    items: [
      mdx("concepts/verdicts", "Verdicts"),
      mdx("concepts/contracts-and-baselines", "Contracts and baselines"),
      mdx("concepts/evidence-and-stale-reports", "Evidence and stale reports"),
      { slug: "reference/cli", title: "CLI reference", source: { kind: "cli" } },
      mdx("reference/configuration", "Configuration reference"),
      mdx("reference/supported-and-experimental", "Supported and experimental"),
      fromRepo("reference/release-criteria", "Release criteria", "docs/gate-release-criteria.md"),
    ],
  },
  {
    title: "Help and trust",
    items: [
      mdx("help/troubleshooting", "Troubleshooting"),
      mdx("trust/security-model", "Security model and limits"),
      fromRepo("trust/threat-model", "Threat model", "docs/threat-model.md"),
      mdx("trust/data-handling", "Data handling"),
      fromRepo("trust/vulnerability-reporting", "Vulnerability reporting", "SECURITY.md"),
      mdx("releases", "Releases"),
      fromRepo("contributing", "Contributing", "CONTRIBUTING.md"),
      fromRepo("roadmap", "Roadmap", "ROADMAP.md"),
    ],
  },
];

export const flatNav: (NavItem & { section: string })[] = nav.flatMap((s) =>
  s.items.map((i) => ({ ...i, section: s.title })),
);

export function findItem(slug: string) {
  return flatNav.find((i) => i.slug === slug);
}

export function docHref(slug: string) {
  return slug ? `/docs/${slug}` : "/docs";
}

/** Repository files rendered on this site, so links to them stay on the site. */
export const repoFileToSlug: Record<string, string> = Object.fromEntries(
  flatNav.flatMap((i) => (i.source.kind === "repo" ? [[i.source.file, i.slug]] : [])),
);
