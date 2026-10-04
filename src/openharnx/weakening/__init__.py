"""The built-in weakening check (T77 item 9; owner proposals 1 and 2).

An agent can make checks pass by lowering the bar instead of fixing the code:
loosening lint, type or pytest configuration, adding a `conftest.py` that
rewrites results, or adding suppressions, skip markers or removing tests.
At contract acceptance a baseline is recorded; at verification the candidate
is compared with it. Any finding blocks until a contract revision is accepted.

Adding tests needs no approval: a new test file is checked only for
suppressions, and more tests or assertions in an existing file are fine.
Python, TypeScript, JavaScript and Go (T82); counts are per file, so moving a
suppression within one file is not seen. Baselines made before TypeScript
support (version 1) are compared on Python only, before Go support
(version 2) without Go, and before the source checks (version 3) without them, so their
contracts judge as they did.

Scope (T90a, spec-kit replay, 2026-10-04): a suppression counts only when the contract
runs the checker it silences (`active_checkers`); with any command that is not
recognised, every suppression counts. Skips count only when unconditional: a `skipif`
with a condition, a skip inside an `if` or `except`, or `importorskip` skip nothing on
the platform where they matter, and skipping a test that passed is caught by the
no-new-failures check. Baselines made before this (version 4) counted every skip, so
they are compared with the old count. `ohx.toml` is configuration from version 6.

Source checks (impossible-tasks replay, 2026-10-04): code outside the tests can also lower
the bar. In Python files that are not tests, a new patch of an imported module (the code
replacing `random.randint` the test uses) or a new `__eq__` that can hide a wrong result
(it returns a constant, belongs to a subclass of a builtin value, or compares the other
value with something computed only when the test compares) is a finding.
"""

from __future__ import annotations

import ast
import configparser
import hashlib
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

BASELINE_VERSION = 6

# Files that configure checkers, wherever they are (ruff and pytest read nested ones).
CONFIG_NAMES = frozenset(
    {
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
        ".pytest.ini",
        "ruff.toml",
        ".ruff.toml",
        "mypy.ini",
        ".mypy.ini",
        ".flake8",
        ".coveragerc",
        ".importlinter",
        "pyrightconfig.json",
        # OpenHarnX's own policy: checks, interpreter, approvers (T90e). A pull request's
        # copy is never read by its own gate, but it would bind every later one.
        "ohx.toml",
        # Code that runs inside the checker or at interpreter start-up.
        "conftest.py",
        "sitecustomize.py",
        "usercustomize.py",
    }
)

# TypeScript and JavaScript (T82). Checker configuration found by name pattern, since each
# tool accepts several file names and extensions.
JS_SOURCE = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
_JS_CONFIG = re.compile(
    r"^(?:tsconfig(?:\.[\w-]+)*\.json|jsconfig\.json"
    r"|(?:vitest|vite|jest|babel|playwright)\.(?:config|workspace|setup)\.[cm]?[jt]s"
    r"|vitest\.workspace\.json|jest\.setup\.[cm]?[jt]s|setupTests\.[cm]?[jt]sx?"
    r"|\.eslintrc(?:\.(?:js|cjs|json|ya?ml))?|eslint\.config\.[cm]?[jt]s"
    r"|biome\.jsonc?|\.babelrc(?:\.json)?|\.mocharc(?:\.\w+)?|\.c8rc(?:\.json)?|\.nycrc(?:\.\w+)?)$"
)
# package.json keys that configure checkers; scripts only when they run checks.
_PACKAGE_KEYS = ("jest", "eslintConfig", "mocha", "c8", "nyc", "ava", "vitest")
_CHECK_SCRIPT = re.compile(r"^(?:test|lint|type|check|format|ci|verify)", re.IGNORECASE)

# Go (T82). A build constraint is counted in test files only: there it can switch a test
# file off, while in other files it is the ordinary way to write platform code.
GO_CONFIG = re.compile(r"^(?:\.golangci\.(?:ya?ml|toml|json)|staticcheck\.conf)$")
GO_SUPPRESSIONS = {
    "nolint": re.compile(r"//\s*nolint\b"),
    "lint:ignore": re.compile(r"//\s*lint:(?:file-)?ignore\b"),
    "#nosec": re.compile(r"#nosec\b"),
    "skipped test": re.compile(r"\b\w+\.(?:Skip|SkipNow|Skipf)\s*\("),
}
GO_TEST_ONLY = {"build constraint": re.compile(r"^//\s*(?:go:build|\+build)\b", re.MULTILINE)}
_GO_TESTS = re.compile(r"^func\s+(?:Test|Fuzz|Example)\w*\s*\(", re.MULTILINE)
_GO_CHECKS = re.compile(
    r"\b[tbf]\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\b(?:assert|require)\.\w+\s*\("
)

JS_SUPPRESSIONS = {
    "@ts-ignore": re.compile(r"@ts-ignore\b"),
    "@ts-expect-error": re.compile(r"@ts-expect-error\b"),
    "@ts-nocheck": re.compile(r"@ts-nocheck\b"),
    "eslint-disable": re.compile(r"\beslint-disable(?:-next-line|-line)?\b"),
    "biome-ignore": re.compile(r"\bbiome-ignore\b"),
    "coverage ignore": re.compile(r"\b(?:istanbul|c8|v8)\s+ignore\b"),
    "skipped or focused test": re.compile(
        r"(?<![\w$])(?:it|test|describe|suite|context|bench)\s*\.\s*"
        r"(?:skip|only|fails|skipIf|runIf|todo)\b"
        r"|(?<![\w$.])(?:xit|xtest|xdescribe|fit|fdescribe)\s*\("
        r"|\b(?:skip|only|todo)\s*:\s*(?:true|['\"`])"
        r"|(?<![\w$])t\s*\.\s*(?:skip|todo)\s*\("
    ),
}
_JS_TESTS = re.compile(r"(?<![\w$.])(?:it|test)\s*(?:\.\s*(?:concurrent|each\s*\([^)]*\)))?\s*\(")
_JS_CHECKS = re.compile(r"(?<![\w$.])(?:expect|assert)\s*(?:\.\s*\w+\s*)?\(")
_JS_TEST_FILE = re.compile(r"\.(?:test|spec)\.[cm]?[jt]sx?$")

SUPPRESSIONS = {
    "noqa": re.compile(r"#\s*noqa\b", re.IGNORECASE),
    "file-level noqa": re.compile(r"#\s*(?:ruff|flake8)\s*:\s*noqa\b", re.IGNORECASE),
    "type: ignore": re.compile(r"#\s*type\s*:\s*ignore\b"),
    "pyright: ignore": re.compile(r"#\s*pyright\s*:\s*ignore\b"),
    "inline mypy setting": re.compile(r"#\s*mypy\s*:"),
    "pragma: no cover": re.compile(r"#\s*pragma\s*:\s*no\s*cover\b"),
    "skip or xfail": re.compile(
        r"\b(?:pytest\.(?:mark\.)?(?:skip|skipif|xfail|importorskip)"
        r"|unittest\.(?:skip\w*|expectedFailure))\b"
    ),
    "pytest_plugins": re.compile(r"\bpytest_plugins\b"),
}
_TESTS = re.compile(r"^\s*(?:async\s+)?def\s+test\w*\s*\(", re.MULTILINE)
_CHECKS = re.compile(
    r"^\s*assert\b|\bself\.assert\w*\s*\(|\bpytest\.(?:raises|warns)\s*\(", re.MULTILINE
)


SKIP = "skip or xfail"
# The checkers that read each suppression (T90a). Kinds not listed count always.
KIND_CHECKERS: dict[str, frozenset[str]] = {
    "noqa": frozenset({"ruff", "flake8"}),
    "file-level noqa": frozenset({"ruff", "flake8"}),
    "type: ignore": frozenset({"mypy", "pyright"}),
    "pyright: ignore": frozenset({"pyright"}),
    "inline mypy setting": frozenset({"mypy"}),
    "pragma: no cover": frozenset({"coverage"}),
    "@ts-ignore": frozenset({"tsc", "vue-tsc"}),
    "@ts-expect-error": frozenset({"tsc", "vue-tsc"}),
    "@ts-nocheck": frozenset({"tsc", "vue-tsc"}),
    "eslint-disable": frozenset({"eslint"}),
    "biome-ignore": frozenset({"biome"}),
    "coverage ignore": frozenset({"coverage"}),
    "nolint": frozenset({"golangci-lint"}),
    "lint:ignore": frozenset({"staticcheck", "golangci-lint"}),
    "#nosec": frozenset({"gosec", "golangci-lint"}),
}
# Commands whose suppressions are known; anything else makes every suppression count.
KNOWN_CHECKERS = frozenset(
    {
        "pytest", "ruff", "flake8", "pylint", "mypy", "pyright", "coverage", "lint-imports",
        "tsc", "vue-tsc", "eslint", "biome", "vitest", "jest", "node",
        "go", "golangci-lint", "staticcheck", "gosec",
    }
)  # fmt: skip
_RUNS = {"uv": "run", "poetry": "run", "pipx": "run", "pdm": "run", "hatch": "run"}
_PYTEST_PLUGINS = {"--mypy": "mypy", "--flake8": "flake8", "--ruff": "ruff", "--pylint": "pylint"}


def _name(arg: str) -> str:
    return PurePosixPath(arg.replace("\\", "/")).name


def _command_checkers(argv: list[str]) -> set[str] | None:
    args = [a for a in argv if a]
    while args and (_name(args[0]) in _RUNS or _name(args[0]) in ("npx", "pnpx", "bunx")):
        if _name(args[0]) in _RUNS:
            if len(args) < 2 or args[1] != _RUNS[_name(args[0])]:
                return None
            args = args[2:]
        else:
            args = args[1:]
        while args and args[0].startswith("-"):
            args = args[1:]
    if not args:
        return None
    tool, rest = _name(args[0]), args[1:]
    if tool == "{python}" or tool.startswith("python"):
        if len(rest) < 2 or rest[0] != "-m":
            return None
        tool, rest = rest[1], rest[2:]
    if tool not in KNOWN_CHECKERS:
        return None
    found = {tool}
    if tool == "coverage" and "-m" in rest and rest.index("-m") + 1 < len(rest):
        inner = rest[rest.index("-m") + 1]
        if inner not in KNOWN_CHECKERS:
            return None
        found.add(inner)
    if any(a.startswith("--cov") or a == "--coverage" for a in rest):
        found.add("coverage")
    return found


def _pytest_addopts(root: Path) -> list[str]:
    opts: list[str] = []
    try:
        tool = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("tool", {})
        value = tool.get("pytest", {}).get("ini_options", {}).get("addopts", [])
        opts += value.split() if isinstance(value, str) else [str(v) for v in value]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, AttributeError):
        pass
    for name, section in (
        ("pytest.ini", "pytest"),
        ("tox.ini", "pytest"),
        ("setup.cfg", "tool:pytest"),
    ):
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(root / name, encoding="utf-8")
            opts += parser.get(section, "addopts", fallback="").split()
        except (configparser.Error, UnicodeDecodeError):
            continue
    return opts


def active_checkers(obligations: list[dict[str, Any]], root: Path) -> frozenset[str] | None:
    """The checkers the contract's commands run, or None when a command is not recognised
    (a script, `make`, `npm test`), so that every suppression counts (T90a). Pytest
    options in the project's configuration add the checkers they turn on."""
    found: set[str] = set()
    for ob in obligations:
        if ob.get("builtin"):
            continue
        tools = _command_checkers([str(a) for a in ob.get("command", [])])
        if tools is None:
            return None
        found |= tools
    if "pytest" in found:
        for opt in _pytest_addopts(root):
            if opt.startswith("--cov"):
                found.add("coverage")
            elif opt.split("=")[0] in _PYTEST_PLUGINS:
                found.add(_PYTEST_PLUGINS[opt.split("=")[0]])
    return frozenset(found)


def _dotted(node: ast.expr) -> tuple[str, ...]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


# Names as parts, so that this file holds no text the skip pattern above would count.
_MARK, _UNITTEST = ("pytest", "mark"), ("unittest",)
_ALWAYS_SKIP = {(*_MARK, "skip"), (*_UNITTEST, "skip"), (*_UNITTEST, "expectedFailure")}
_SKIP_CALLS = {("pytest", "skip"), ("pytest", "xfail")}


def _always(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value) and not isinstance(node.value, str)


def _skips(tree: ast.Module) -> int:
    """Unconditional pytest and unittest skips and expected failures."""
    calls = {id(n.func): n for n in ast.walk(tree) if isinstance(n, ast.Call)}
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        name = _dotted(node)
        call = calls.get(id(node))
        condition = None
        if call is not None:
            kw = {k.arg: k.value for k in call.keywords}
            condition = call.args[0] if call.args else kw.get("condition")
        if name in _ALWAYS_SKIP:
            count += 1
        elif name == (*_MARK, "xfail"):
            count += condition is None or _always(condition)
        elif name == (*_MARK, "skipif"):
            count += call is not None and _always(condition)
    # A skip or xfail call, or self.skipTest(), as a statement of its own in a function or
    # module body; inside an if, try, loop or with it is conditional.
    for body_owner in ast.walk(tree):
        if not isinstance(body_owner, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for stmt in body_owner.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                if _dotted(func) in _SKIP_CALLS or (
                    isinstance(func, ast.Attribute) and func.attr == "skipTest"
                ):
                    count += 1
    return count


PATCH = "patch of an imported module"
EQUALITY = "__eq__ that can hide a wrong result"
SOURCE_CHECKS = (PATCH, EQUALITY)
_BUILTIN_VALUES = frozenset(
    {"str", "bytes", "int", "float", "complex", "bool", "list", "tuple", "dict", "set", "frozenset"}
)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _scopes(tree: ast.Module) -> list[tuple[ast.AST, set[str]]]:
    """Each function body and the module, with the names bound locally in it that are
    not module imports (parameters and assignments shadow the module name)."""
    found: list[tuple[ast.AST, set[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            params = {x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs]}
            params |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
            found.append((node, params))
    return found


def _patches(tree: ast.Module) -> int:
    """Assignments to, or deletions of, attributes of a module imported with `import`."""
    modules = {
        (alias.asname or alias.name.split(".")[0])
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    if not modules:
        return 0
    shadowed: dict[int, set[str]] = {}
    for scope, params in _scopes(tree):
        for inner in ast.walk(scope):
            shadowed[id(inner)] = shadowed.get(id(inner), set()) | params
    count = 0
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, (ast.Assign, ast.Delete)):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("setattr", "delattr")
            and node.args
        ):
            targets = [ast.Attribute(value=node.args[0], attr="?", ctx=ast.Store())]
        for target in targets:
            local = shadowed.get(id(node), set())
            if isinstance(target, ast.Attribute):
                name = _root_name(target.value)
                # Redirecting sys.stdout, sys.path or a sys hook is ordinary practice.
                if name in modules and name not in local and name != "sys":
                    count += 1
            elif (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "modules"
                and _root_name(target.value) == "sys"
                and "sys" in modules
            ):
                count += 1
    return count


def _hides_result(cls: ast.ClassDef, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if any(isinstance(b, ast.Name) and b.id in _BUILTIN_VALUES for b in cls.bases):
        return True
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    if returns and all(
        isinstance(r.value, ast.Constant) and isinstance(r.value.value, bool) for r in returns
    ):
        return True
    params = [a.arg for a in fn.args.args]
    if len(params) < 2:
        return False
    other = params[1]
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and len(node.comparators) == 1:
            sides = (node.left, node.comparators[0])
            for this, that in (sides, sides[::-1]):
                if isinstance(this, ast.Name) and this.id == other and isinstance(that, ast.Call):
                    return True
    return False


def _equalities(tree: ast.Module) -> int:
    """`__eq__` and `__ne__` methods that can make a wrong result compare equal."""
    return sum(
        1
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef)
        for fn in cls.body
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and fn.name in ("__eq__", "__ne__")
        and _hides_result(cls, fn)
    )


def _python_counts(text: str, test: bool) -> dict[str, int] | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    counts = {SKIP: _skips(tree)}
    if not test:
        counts |= {PATCH: _patches(tree), EQUALITY: _equalities(tree)}
    return counts


def _source_counts(text: str) -> dict[str, int]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    return {PATCH: _patches(tree), EQUALITY: _equalities(tree)}


def is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    if name.endswith(".py"):
        return name.startswith("test_") or name.endswith("_test.py")
    if name.endswith(".go"):
        return name.endswith("_test.go")
    if name.endswith(JS_SOURCE):
        return bool(_JS_TEST_FILE.search(name)) or "__tests__" in p.parts[:-1]
    return False


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _config_digest(path: str, data: bytes) -> str | None:
    """Digest of the part of a file that configures checkers; None if it has none."""
    if PurePosixPath(path).name == "pyproject.toml":
        try:
            tool = tomllib.loads(data.decode("utf-8")).get("tool")
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            return _digest(data)  # unreadable: any change counts
        if tool is None:
            return None
        return _digest(json.dumps(tool, sort_keys=True).encode())
    if PurePosixPath(path).name == "package.json":
        try:
            package = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _digest(data)
        if not isinstance(package, dict):
            return _digest(data)
        scripts = package.get("scripts")
        checks = {
            k: v
            for k, v in (scripts if isinstance(scripts, dict) else {}).items()
            if _CHECK_SCRIPT.match(k)
        }
        part = {k: package[k] for k in _PACKAGE_KEYS if k in package}
        if checks:
            part["scripts"] = checks
        return _digest(json.dumps(part, sort_keys=True).encode()) if part else None
    name = PurePosixPath(path).name
    if PurePosixPath(path).parts[-2:] == (".claude", "settings.json"):
        return _digest(data)  # shared agent settings: where a verifying hook lives (T80)
    if name in CONFIG_NAMES or _JS_CONFIG.match(name) or GO_CONFIG.match(name):
        return _digest(data)
    return None


def snapshot(root: Path, paths: list[str]) -> dict[str, Any]:
    """Configuration digests, suppression counts and test counts for the given files."""
    config: dict[str, str] = {}
    suppressions: dict[str, dict[str, int]] = {}
    tests: dict[str, dict[str, int]] = {}
    any_skips: dict[str, int] = {}  # every skip, as baselines before version 5 counted
    for rel in sorted(paths):
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        cdig = _config_digest(rel, data)
        if cdig is not None:
            config[rel] = cdig
        if rel.endswith(".py"):
            patterns, test_re, check_re = SUPPRESSIONS, _TESTS, _CHECKS
        elif rel.endswith(JS_SOURCE):
            patterns, test_re, check_re = JS_SUPPRESSIONS, _JS_TESTS, _JS_CHECKS
        elif rel.endswith(".go"):
            patterns, test_re, check_re = GO_SUPPRESSIONS, _GO_TESTS, _GO_CHECKS
            if is_test_file(rel):
                patterns = {**GO_SUPPRESSIONS, **GO_TEST_ONLY}
        else:
            continue
        text = data.decode("utf-8", errors="replace")
        counts = {k: len(p.findall(text)) for k, p in patterns.items()}
        if rel.endswith(".py"):
            if counts.get(SKIP):
                any_skips[rel] = counts[SKIP]
            counts |= _python_counts(text, is_test_file(rel)) or {}
        counts = {k: n for k, n in counts.items() if n}
        if counts:
            suppressions[rel] = counts
        if is_test_file(rel):
            tests[rel] = {
                "tests": len(test_re.findall(text)),
                "checks": len(check_re.findall(text)),
            }
    return {
        "version": BASELINE_VERSION,
        "config": config,
        "suppressions": suppressions,
        "tests": tests,
        "any_skips": any_skips,
    }


def _as_version(snap: dict[str, Any], version: int) -> dict[str, Any]:
    """What a baseline of an earlier version would have recorded: version 1 Python only,
    version 2 without Go, version 3 without the source checks."""

    def known(path: str, config: bool = False) -> bool:
        name = PurePosixPath(path).name
        if version < 2:
            return (
                (name == "pyproject.toml" or name in CONFIG_NAMES)
                if config
                else (path.endswith(".py"))
            )
        if version < 3:
            return not (path.endswith(".go") or (config and GO_CONFIG.match(name)))
        return True

    suppressions = {k: v for k, v in snap["suppressions"].items() if known(k)}
    config = {k: v for k, v in snap["config"].items() if known(k, config=True)}
    if version < 6:  # ohx.toml was not configuration yet
        config = {k: v for k, v in config.items() if PurePosixPath(k).name != "ohx.toml"}
    if version < 4:
        suppressions = {
            k: {kind: n for kind, n in v.items() if kind not in SOURCE_CHECKS}
            for k, v in suppressions.items()
        }
    if version < 5:  # every skip counted, conditional or not
        any_skips = snap.get("any_skips", {})
        suppressions = {
            k: {
                **{kind: n for kind, n in v.items() if kind != SKIP},
                **({SKIP: any_skips[k]} if any_skips.get(k) else {}),
            }
            for k, v in suppressions.items()
        }
        for k, n in any_skips.items():
            if k not in suppressions and known(k):
                suppressions[k] = {SKIP: n}
    return {
        **snap,
        "config": config,
        "suppressions": suppressions,
        "tests": {k: v for k, v in snap["tests"].items() if known(k)},
    }


def compare(
    baseline: dict[str, Any], current: dict[str, Any], active: frozenset[str] | None = None
) -> list[str]:
    """Findings that lower the bar since the baseline; empty means none found. With
    `active`, the checkers the contract runs, a suppression for another checker does not
    count (T90a)."""
    if baseline.get("version", 1) < BASELINE_VERSION:
        current = _as_version(current, baseline.get("version", 1))
    findings: list[str] = []
    before_cfg, now_cfg = baseline["config"], current["config"]
    for path in sorted(set(before_cfg) | set(now_cfg)):
        if path not in now_cfg:
            findings.append(f"{path}: check configuration removed since acceptance")
        elif path not in before_cfg:
            findings.append(f"{path}: check configuration added since acceptance")
        elif before_cfg[path] != now_cfg[path]:
            findings.append(f"{path}: check configuration changed since acceptance")
    for path, counts in sorted(current["suppressions"].items()):
        before = baseline["suppressions"].get(path, {})
        for kind, n in sorted(counts.items()):
            readers = KIND_CHECKERS.get(kind)
            if active is not None and readers is not None and not readers & active:
                continue
            if n > before.get(kind, 0):
                findings.append(f"{path}: {n - before.get(kind, 0)} new {kind}")
    for path, before in sorted(baseline["tests"].items()):
        now = current["tests"].get(path)
        if now is None:
            findings.append(f"{path}: test file removed")
            continue
        for key, label in (("tests", "tests"), ("checks", "assertions")):
            if now[key] < before[key]:
                findings.append(f"{path}: fewer {label} ({before[key]} to {now[key]})")
    return findings
