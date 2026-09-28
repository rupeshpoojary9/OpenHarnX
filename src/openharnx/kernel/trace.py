"""Source tracing: every line of a requirements source is accounted for.

Sources (a BRD, interrogation decisions) are split into units by rule, never by
a model, so nothing can be skipped. Each unit must be a requirement proven by a
test, or a drop (context or excluded) approved by the owner. Coverage is
computed against the source text, not against anyone's summary of it.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from openharnx.kernel.canonical import digest

STATUSES = frozenset({"unmarked", "requirement", "context", "question", "excluded"})
DROPS = frozenset({"context", "excluded"})

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@dataclass(frozen=True)
class SourceUnit:
    source: str
    section: str
    text: str
    digest: str


def _unit(source: str, section: str, text: str) -> SourceUnit:
    text = " ".join(text.split())
    return SourceUnit(source, section, text, digest({"text": text}))


def split_units(source: str, text: str) -> list[SourceUnit]:
    """Split Markdown or plain text into sentence-level units.

    Headings name the section and are not units. Each bullet and each table
    body row is a unit, split further into sentences. Table header and
    separator rows are skipped. Fenced code blocks are one unit each.
    """
    units: list[SourceUnit] = []
    section = ""
    para: list[str] = []
    bullet: list[str] = []
    fence: list[str] | None = None
    prev_table = False

    def flush() -> None:
        for block in (para, bullet):
            if block:
                for sentence in _SENTENCE_END.split(" ".join(block)):
                    if sentence.strip():
                        units.append(_unit(source, section, sentence))
                block.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith("```"):
                if fence:
                    units.append(_unit(source, section, "\n".join(fence)))
                fence = None
            else:
                fence.append(line)
            continue
        if stripped.startswith("```"):
            flush()
            fence = []
            continue
        is_table = stripped.startswith("|")
        if is_table:
            flush()
            if not prev_table or _TABLE_SEPARATOR.match(stripped):
                prev_table = True  # header row or separator: not a unit
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            units.append(_unit(source, section, " | ".join(c for c in cells if c)))
            continue
        prev_table = False
        if not stripped:
            flush()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            section = heading.group(1).strip()
            continue
        item = _BULLET.match(line)
        if item:
            flush()
            bullet.append(item.group(1))
        elif bullet and line[:1].isspace():
            bullet.append(stripped)  # continuation of the current bullet
        else:
            if bullet:
                flush()
            para.append(stripped)
    flush()
    if fence:
        units.append(_unit(source, section, "\n".join(fence)))
    return units


@dataclass(frozen=True)
class TraceEntry:
    id: str
    source: str
    text: str
    digest: str
    status: str
    tests: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class UnitResult:
    id: str
    source: str
    text: str
    state: str
    reason: str


@dataclass(frozen=True)
class TraceReport:
    results: tuple[UnitResult, ...]
    counts: Mapping[str, int]
    drops_digest: str
    ok: bool


BLOCKING = frozenset(
    {"not built", "open", "dropped (not approved)", "untracked", "stale", "invalid"}
)


def drops_digest(entries: Sequence[TraceEntry]) -> str:
    """Identity of the set of dropped units; approval is bound to exactly this set."""
    drops = sorted((e.id, e.digest, e.status, e.note) for e in entries if e.status in DROPS)
    return digest({"drops": [list(d) for d in drops]})


def evaluate_trace(
    units: Sequence[SourceUnit],
    entries: Sequence[TraceEntry],
    approved_drops: str | None,
    test_results: Mapping[str, bool] | None,
) -> TraceReport:
    """Judge coverage. `test_results` maps test node IDs to pass (None: not run)."""
    in_source = Counter((u.source, u.digest) for u in units)
    in_trace = Counter((e.source, e.digest) for e in entries)
    current = drops_digest(entries)
    results: list[UnitResult] = []

    for u in units:
        key = (u.source, u.digest)
        if in_trace[key] < in_source[key]:
            in_trace[key] += 1  # report each missing occurrence once
            results.append(UnitResult("(new)", u.source, u.text, "untracked", "not in trace"))

    for e in entries:
        key = (e.source, e.digest)
        if in_source[key] <= 0:
            results.append(UnitResult(e.id, e.source, e.text, "stale", "no longer in source"))
            continue
        in_source[key] -= 1
        results.append(_judge(e, current, approved_drops, test_results))

    counts = Counter(r.state for r in results)
    ok = not any(r.state in BLOCKING for r in results)
    return TraceReport(tuple(results), dict(counts), current, ok)


def _judge(
    e: TraceEntry,
    current_drops: str,
    approved_drops: str | None,
    test_results: Mapping[str, bool] | None,
) -> UnitResult:
    def result(state: str, reason: str = "") -> UnitResult:
        return UnitResult(e.id, e.source, e.text, state, reason)

    if e.status not in STATUSES:
        return result("invalid", f"unknown status {e.status!r}")
    if e.status in ("unmarked", "question"):
        return result("open", e.status)
    if e.status in DROPS:
        if e.status == "excluded" and not e.note.strip():
            return result("dropped (not approved)", "excluded without a reason")
        if approved_drops != current_drops:
            return result("dropped (not approved)", "owner has not approved this set")
        return result("dropped (approved)", e.note or e.status)
    if not e.tests:
        return result("not built", "no test linked")
    if test_results is None:
        return result("linked", ", ".join(e.tests))
    missing = [t for t in e.tests if t not in test_results]
    if missing:
        return result("not built", "test not found: " + ", ".join(missing))
    failed = [t for t in e.tests if not test_results[t]]
    if failed:
        return result("not built", "test failed: " + ", ".join(failed))
    return result("verified", ", ".join(e.tests))
