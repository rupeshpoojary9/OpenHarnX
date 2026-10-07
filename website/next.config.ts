import type { NextConfig } from "next";

const config: NextConfig = {
  // Every page is prerendered. Documentation pages read files from the OpenHarnX
  // repository around this folder (docs/, ROADMAP.md, CONTRIBUTING.md, SECURITY.md)
  // at build time only, so nothing outside website/ is traced into the deployment.
  turbopack: { root: __dirname },
  poweredByHeader: false,
  async redirects() {
    return [
      { source: "/trust", destination: "/docs/trust/security-model", permanent: false },
      { source: "/roadmap", destination: "/docs/roadmap", permanent: false },
    ];
  },
};

export default config;
