"""Static pre-check on model-generated code (architecture 8.4 item 1).

This is a cheap first filter — belt and suspenders, NOT a substitute for the VM
boundary. It rejects code containing obviously out-of-scope constructs (os,
subprocess, socket, raw file opens outside the I/O helpers, dunder escapes)
before the code ever reaches the sandbox.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Modules the analysis runtime is allowed to touch (architecture 8.3 pinned set).
ALLOWED_IMPORTS = {
    "pandas", "numpy", "scipy", "statsmodels", "matplotlib", "seaborn",
    "math", "statistics", "json", "datetime", "collections", "itertools",
    "functools", "re", "random", "decimal", "fractions",
    # provided I/O helpers namespace
    "weave_io",
}

# Names that are dangerous regardless of context.
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "ctypes",
    "importlib", "pickle", "marshal", "requests", "urllib", "http",
}

# Attribute chains that indicate an escape attempt.
FORBIDDEN_ATTRS = {
    "__globals__", "__builtins__", "__subclasses__", "__bases__", "__mro__",
    "__class__", "__code__", "__closure__", "__dict__", "__reduce__",
    "__getattribute__", "system", "popen", "fork", "spawn",
}


@dataclass
class PrecheckResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def static_precheck(code: str) -> PrecheckResult:
    violations: list[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return PrecheckResult(ok=False, violations=[f"syntax error: {exc.msg} (line {exc.lineno})"])

    for node in ast.walk(tree):
        # imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    violations.append(f"disallowed import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                violations.append(f"disallowed import-from: {node.module}")

        # bare name use of forbidden builtins/modules
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            violations.append(f"forbidden name: {node.id}")

        # attribute-based escapes: x.__globals__, obj.__class__.__bases__ ...
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            violations.append(f"forbidden attribute access: .{node.attr}")

    # de-dup, keep order
    seen = set()
    deduped = [v for v in violations if not (v in seen or seen.add(v))]
    return PrecheckResult(ok=not deduped, violations=deduped)
