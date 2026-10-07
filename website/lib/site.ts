// Facts about the release this site documents. Change them only together with the
// generated CLI reference (content/generated/cli.json) and the demo transcripts
// (content/demo), which are captured from the same installed release.
export const release = {
  version: "0.1.0",
  tag: "v0.1.0",
  commit: "01626665a341812ded02c0559f5428c2e71d5ef1",
  date: "2026-10-06",
  srt: "0.0.77",
  python: "3.12",
  node: "20",
} as const;

export const repo = {
  url: "https://github.com/rupeshpoojary9/OpenHarnX",
  branch: "main",
  // Where this website's own sources live inside the repository.
  siteDir: "website",
} as const;

export const links = {
  github: repo.url,
  releases: `${repo.url}/releases`,
  release: `${repo.url}/releases/tag/${release.tag}`,
  trialReport: `${repo.url}/issues/new?template=trial-report.yml`,
  issues: `${repo.url}/issues`,
  advisory: `${repo.url}/security/advisories/new`,
  cheatDemo: `${repo.url}/tree/${repo.branch}/examples/cheat-demo`,
  blob: (p: string) => `${repo.url}/blob/${repo.branch}/${p}`,
  tree: (p: string) => `${repo.url}/tree/${repo.branch}/${p}`,
  edit: (p: string) => `${repo.url}/edit/${repo.branch}/${p}`,
} as const;

export const installCommand = `uv tool install git+${repo.url}@${release.tag}`;

/** Absolute site origin for canonical URLs, the sitemap and Open Graph tags. */
export function siteUrl(): string {
  const explicit = process.env.SITE_URL;
  if (explicit) return explicit.replace(/\/$/, "");
  const vercel = process.env.VERCEL_PROJECT_PRODUCTION_URL;
  if (vercel) return `https://${vercel}`;
  return "http://localhost:3000";
}

export const description =
  "OpenHarnX is an open-source verifier for changes written by coding agents. It protects agreed tests, runs verification in a sandbox and produces an evidence-backed review brief. No model calls.";
