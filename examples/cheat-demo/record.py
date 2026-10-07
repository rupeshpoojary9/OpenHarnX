"""Render the cheat demo as an animated terminal GIF and the blocked report as a picture.

    uv run --no-project --with pillow python examples/cheat-demo/record.py

Writes docs/assets/cheat-demo.gif and docs/assets/report-blocked.png. The lines are the
demo's own output (`demo.py --sandbox srt`, 2026-10-07) and the brief of the agent's
change, with machine-specific paths and identifiers left out. Scripted: no model ran.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
FONT_PATHS = (
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)
SIZE = 17
WIDTH, ROWS = 1180, 26
LINE, PAD = 25, 22
BG, FG = (13, 17, 23), (230, 237, 243)
COLOURS = {
    "#": (139, 148, 158),  # narration
    "$": (121, 192, 255),  # a command
    "!": (255, 123, 114),  # blocked
    "+": (86, 211, 100),  # passed
    "~": (227, 179, 65),  # the agent's claim, and decisions
    "=": (210, 168, 255),  # headings of the brief
    " ": FG,
}

# (line, seconds shown before the next one); the first character picks the colour.
SCRIPT: list[tuple[str, float]] = [
    ("# OpenHarnX cheat demo: scripted, no model ran", 2.0),
    ("# 1. A small shop's repository, with three passing tests", 1.2),
    ("$ pytest", 0.8),
    ("+   3 passed", 1.6),
    ("# 2. Lock the suite: from now on it is the contract", 1.2),
    ("$ ohx init --lock-tests", 0.8),
    ("    locked the existing tests", 1.6),
    ("# 3. An agent is asked to add percentage coupons", 1.4),
    ("~ agent: I added percentage coupons, updated the fixed-coupon test", 0.4),
    ("~        to the new API and skipped an obsolete test. All tests pass.", 2.4),
    ("$ pytest", 0.8),
    ("+   3 passed, 1 skipped          <- plain pytest agrees", 2.4),
    ("$ ohx verify --sandbox srt", 1.2),
    ("!   OpenHarnX report: BLOCKED", 1.2),
    ("!   weakening: tests/test_pricing.py: 1 new skip or xfail", 1.0),
    ("!   test_fixed_coupon passed at acceptance and fails", 1.0),
    ("!   test_coupon_never_makes_total_negative passed at acceptance and fails", 3.0),
    ("# 4. The genuine change: fixed coupons still work, new tests added", 1.4),
    ("$ pytest", 0.8),
    ("+   5 passed", 1.2),
    ("$ ohx verify --sandbox srt", 1.2),
    ("+   OpenHarnX report: NO REGRESSIONS", 2.4),
    ("# 5. The review brief: what was verified, and what is left to you", 1.4),
    ("$ ohx report", 1.0),
    ("=   What changed", 0.4),
    ("    pricing.py                    modified  code  imported by a test", 0.4),
    ("    tests/test_percent_coupon.py  added     test", 1.0),
    ("=   What was verified", 0.4),
    ("+   every test that passed before passes (locked copy and working tree)", 0.4),
    ("+   no removed test or assertion, new skip or loosened configuration", 1.2),
    ("=   Decisions for you", 0.4),
    ("~   1. Is the requested outcome done? No agreed test checks it.", 0.6),
    ("~   2. Are the changed tests right? tests/test_percent_coupon.py (added)", 6.0),
]

BLOCKED_BRIEF = [
    "= OpenHarnX report: BLOCKED",
    " ",
    "= What changed",
    "    pricing.py              modified  code   imported by a test",
    "    tests/test_pricing.py   modified  test",
    " ",
    "= What was verified",
    "+   tests (the working tree's own copy): passed",
    "#   a passing check does not show that every changed line ran",
    " ",
    "= What remains unverified",
    "!   no-new-failures-locked-tests: test_coupon_never_makes_total_negative and",
    "!     test_fixed_coupon passed at acceptance and fail       [output]",
    "!   no-new-failures-tests: test_coupon_never_makes_total_negative passed",
    "!     at acceptance and is skipped                            [output]",
    "!   weakening: tests/test_pricing.py: 1 new skip or xfail    [output]",
    " ",
    "= Decisions for you",
    "~   1. A mandatory check did not pass. Send it back to the agent with the",
    "~      output linked above, or agree a new contract revision.",
    "~      A report cannot waive a failed check.",
    "~   2. Are the changed tests right? tests/test_pricing.py (modified)",
]


def _font() -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).is_file():
            return ImageFont.truetype(path, SIZE)
    raise SystemExit("no monospace font found; add one to FONT_PATHS")


def _draw(lines: list[str], font: ImageFont.FreeTypeFont, rows: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, PAD * 2 + LINE * rows), BG)
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines[-rows:]):
        colour = COLOURS.get(line[:1], FG)
        draw.text((PAD, PAD + i * LINE), line[1:] if line[:1] in "#$!+~=" else line, font=font,
                  fill=colour)  # fmt: skip
    return image


def gif(font: ImageFont.FreeTypeFont) -> Path:
    frames, durations, shown = [], [], []
    for line, seconds in SCRIPT:
        shown.append(line if line[:1] != "$" else "$$ " + line[2:])
        frames.append(_draw(shown, font, ROWS))
        durations.append(int(seconds * 1000))
    out = ASSETS / "cheat-demo.gif"
    palette = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=16) for f in frames]
    palette[0].save(out, save_all=True, append_images=palette[1:], duration=durations, loop=0)
    return out


def picture(font: ImageFont.FreeTypeFont) -> Path:
    out = ASSETS / "report-blocked.png"
    _draw(BLOCKED_BRIEF, font, len(BLOCKED_BRIEF)).save(out, optimize=True)
    return out


if __name__ == "__main__":
    font = _font()
    for path in (gif(font), picture(font)):
        print(path.relative_to(ROOT), path.stat().st_size // 1024, "KB")
