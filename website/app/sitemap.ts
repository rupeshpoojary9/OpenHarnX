import type { MetadataRoute } from "next";
import { flatNav, docHref } from "@/lib/nav";
import { siteUrl } from "@/lib/site";

export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();
  return [
    { url: `${base}/`, priority: 1 },
    { url: `${base}/examples`, priority: 0.7 },
    ...flatNav.map((i) => ({ url: `${base}${docHref(i.slug)}`, priority: i.slug ? 0.6 : 0.9 })),
  ];
}
