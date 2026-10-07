/* eslint-disable @next/next/no-img-element */
// The existing OpenHarnX logo (docs/assets), cropped without its tagline; one
// version per theme, as on GitHub.
export function Logo({ height = 22 }: { height?: number }) {
  const width = Math.round((height * 1668) / 270);
  return (
    <>
      <img className="logo-light" src="/brand/logo-lockup-light-sm.png" alt="OpenHarnX" width={width} height={height} style={{ height }} />
      <img className="logo-dark" src="/brand/logo-lockup-dark-sm.png" alt="OpenHarnX" width={width} height={height} style={{ height }} />
    </>
  );
}
