import { ImageResponse } from "next/og";
import fs from "node:fs/promises";
import path from "node:path";
import { release } from "@/lib/site";

export const alt = "OpenHarnX: your coding agent says the tests pass. Check what actually passed.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OpenGraphImage() {
  const logo = await fs.readFile(path.join(/*turbopackIgnore: true*/ process.cwd(), "public/brand/logo-lockup-light-sm.png"));
  const src = `data:image/png;base64,${logo.toString("base64")}`;
  const ink = "#13191d";
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", background: "#f4f2ed", padding: 64, color: ink, border: "1px solid #d9d4ca" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} width={300} height={49} alt="" />
          <div style={{ display: "flex", fontSize: 22, background: ink, color: "#f4f2ed", padding: "4px 12px", fontFamily: "monospace" }}>{release.tag}</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 76, fontWeight: 800, lineHeight: 1.02, letterSpacing: -2 }}>
          <span>Your coding agent says the tests pass.</span>
          <span style={{ color: "#016a6e" }}>Check what actually passed.</span>
        </div>
        <div style={{ display: "flex", gap: 16, fontSize: 24, fontFamily: "monospace" }}>
          <span style={{ border: "2px solid #b42318", color: "#b42318", padding: "4px 12px" }}>BLOCKED</span>
          <span style={{ border: "2px solid #1f5f99", color: "#1f5f99", padding: "4px 12px" }}>NO REGRESSIONS</span>
          <span style={{ border: "2px solid #156b45", color: "#156b45", padding: "4px 12px" }}>READY</span>
          <span style={{ marginLeft: "auto", color: "#5e676d", padding: "6px 0" }}>open source · no model calls</span>
        </div>
      </div>
    ),
    size,
  );
}
