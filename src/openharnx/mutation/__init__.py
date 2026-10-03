"""Mutants of a change's own lines, to test whether its acceptance tests pin it (T87 item 5).

A mutant is one small edit to a changed line of a source file: a comparison or
arithmetic operator swapped, `and` for `or`, a number moved by one, a boolean
flipped. Only lines the change touched are mutated, so a survivor points at
the change, not at old code the acceptance tests were never about. Each
mutant's source ends with a probe that touches a file named by
`OHX_MUTANT_PROBE` when the module is imported, so a mutant the tests never
loaded is reported as not exercised instead of as a survivor.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROBE_ENV = "OHX_MUTANT_PROBE"
MAX_MUTANTS = 10

_PROBE = (
    "\n\nimport os as _ohx_os\n"
    f"if _ohx_os.environ.get({PROBE_ENV!r}):\n"
    f"    open(_ohx_os.environ[{PROBE_ENV!r}], 'a').close()\n"
)

_COMPARE: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}
_BINARY: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
    ast.FloorDiv: ast.Mult,
    ast.Mod: ast.FloorDiv,
}
_BOOLEAN: dict[type[ast.boolop], type[ast.boolop]] = {ast.And: ast.Or, ast.Or: ast.And}


@dataclass(frozen=True)
class Mutant:
    path: str
    line: int
    before: str
    after: str
    source: str  # the whole mutated module, probe included


def is_source(path: str) -> bool:
    """Python files that are not tests."""
    p = Path(path)
    if p.suffix != ".py" or p.name == "conftest.py":
        return False
    if p.name.startswith("test_") or p.name.endswith("_test.py"):
        return False
    return not any(part in ("tests", "test") for part in p.parts[:-1])


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )


_HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", re.M)


def changed_lines(root: Path, base_commit: str, paths: list[str]) -> dict[str, set[int]]:
    """Lines of each source file in `paths` that differ from `base_commit`.

    A file the base does not have is new, and every line of it counts."""
    sources = [p for p in paths if is_source(p)]
    tracked = _git(root, "ls-tree", "-r", "--name-only", base_commit)
    if tracked.returncode != 0:
        raise ValueError(f"cannot read base commit {base_commit}")
    in_base = set(tracked.stdout.splitlines())
    result: dict[str, set[int]] = {}
    for path in sources:
        if path not in in_base:
            count = len((root / path).read_text(encoding="utf-8").splitlines())
            if count:
                result[path] = set(range(1, count + 1))
            continue
        diff = _git(root, "diff", "-U0", "--no-color", "--no-ext-diff", base_commit, "--", path)
        lines: set[int] = set()
        for m in _HUNK.finditer(diff.stdout):
            start, length = int(m.group(1)), int(m.group(2) or "1")
            lines.update(range(start, start + length))
        if lines:
            result[path] = lines
    return result


def _mutable(node: ast.AST) -> bool:
    if isinstance(node, ast.BinOp):
        return type(node.op) in _BINARY
    if isinstance(node, ast.BoolOp):
        return type(node.op) in _BOOLEAN
    return isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float))


def _sites(tree: ast.AST, lines: set[int]) -> list[tuple[ast.AST, int]]:
    """Every (node, variant) that can be mutated on `lines`, in a fixed order."""
    sites: list[tuple[ast.AST, int]] = []
    for node in ast.walk(tree):
        if getattr(node, "lineno", None) not in lines:
            continue
        if isinstance(node, ast.Compare):
            sites.extend((node, i) for i, op in enumerate(node.ops) if type(op) in _COMPARE)
        elif _mutable(node):
            sites.append((node, 0))
    return sites


def _apply(node: ast.AST, variant: int) -> None:
    if isinstance(node, ast.Compare):
        node.ops[variant] = _COMPARE[type(node.ops[variant])]()
    elif isinstance(node, ast.BinOp):
        node.op = _BINARY[type(node.op)]()
    elif isinstance(node, ast.BoolOp):
        node.op = _BOOLEAN[type(node.op)]()
    elif isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            node.value = not value
        elif isinstance(value, (int, float)):
            node.value = value + 1


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57] + "..."


def mutants_of(path: str, text: str, lines: set[int]) -> list[Mutant]:
    """Every mutant of `lines` in one file, in a fixed order."""
    try:
        count = len(_sites(ast.parse(text), lines))
    except SyntaxError:
        return []
    found = []
    for k in range(count):
        tree = ast.parse(text)
        node, variant = _sites(tree, lines)[k]
        line = getattr(node, "lineno", 0)
        before = ast.get_source_segment(text, node) or ast.unparse(node)
        _apply(node, variant)
        after = ast.unparse(node)
        found.append(Mutant(path, line, _short(before), _short(after), ast.unparse(tree) + _PROBE))
    return found


def select(root: Path, changed: dict[str, set[int]], limit: int = MAX_MUTANTS) -> list[Mutant]:
    """Up to `limit` mutants, spread over the changed lines: one per line first."""
    by_line: dict[tuple[str, int], list[Mutant]] = {}
    for path in sorted(changed):
        text = (root / path).read_text(encoding="utf-8")
        for m in mutants_of(path, text, changed[path]):
            by_line.setdefault((m.path, m.line), []).append(m)
    chosen: list[Mutant] = []
    depth = 0
    while len(chosen) < limit and any(len(ms) > depth for ms in by_line.values()):
        for key in sorted(by_line):
            if depth < len(by_line[key]) and len(chosen) < limit:
                chosen.append(by_line[key][depth])
        depth += 1
    return chosen
