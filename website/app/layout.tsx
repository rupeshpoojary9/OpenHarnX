import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Instrument_Sans, Schibsted_Grotesk } from "next/font/google";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";
import { SearchDialog } from "@/components/Search";
import { description, siteUrl } from "@/lib/site";
import "./globals.css";

const display = Schibsted_Grotesk({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-schibsted",
  display: "swap",
});
const body = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-instrument",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: {
    default: "OpenHarnX: check what your coding agent actually passed",
    template: "%s | OpenHarnX",
  },
  description,
  applicationName: "OpenHarnX",
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: "OpenHarnX",
    title: "OpenHarnX: check what your coding agent actually passed",
    description,
    url: "/",
  },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f2ed" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1416" },
  ],
};

// Runs before paint so the stored or system theme applies without a flash.
const themeScript = `(function(){try{var t=localStorage.getItem('ohx-theme');if(t!=='light'&&t!=='dark'){t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme='light'}})()`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      data-theme="light"
      className={`${display.variable} ${body.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <SiteHeader />
        <main id="main">{children}</main>
        <SiteFooter />
        <SearchDialog />
      </body>
    </html>
  );
}
