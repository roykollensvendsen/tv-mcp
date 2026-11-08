# SPDX-License-Identifier: GPL-3.0-or-later
"""The layers: core, then drivers and tools, then the server and the command line.

The core knows no brand of TV and no MCP; a driver knows one brand and the
core; a tool knows the core and MCP, and never a driver. Only the command line
puts drivers and tools together. Every import, including those made only for
type checking, is counted, because a contributor's driver must be swappable
without touching anything else.
"""

import ast
import pathlib

PACKAGE = pathlib.Path(__file__).parent.parent / "src" / "tv_mcp"
CORE = {
    "settings",
    "driver",
    "media",
    "service",
    "power",
    "conformance",
    "discovery",
    "simulator",
    "__init__",
    "_version",
}
TOP = {"server", "cli"}


def _layer(module: str) -> str:
    parts = module.split(".")
    if parts[0] == "drivers" and len(parts) > 1:
        return "drivers"
    if parts[0] == "tools":
        return "tools"
    if parts[0] in TOP:
        return "top"
    if parts[0] in CORE or parts[0] == "drivers":
        return "core"
    return "unassigned"


#: Which layers each layer may import from this package.
ALLOWED = {
    "core": {"core"},
    "drivers": {"core"},
    "tools": {"core", "tools"},
    "top": {"core", "tools", "drivers", "top"},
}
#: Outside packages a layer must never import.
FORBIDDEN_OUTSIDE = {"core": {"mcp"}, "drivers": {"mcp"}}


def _modules():
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).with_suffix("")
        yield ".".join(relative.parts), path


def _imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_every_module_has_a_layer():
    assert [m for m, _ in _modules() if _layer(m) == "unassigned"] == []


def test_each_layer_imports_only_the_layers_below_it():
    wrong = []
    for module, path in _modules():
        layer = _layer(module)
        for name in _imports(path):
            top = name.split(".")[0]
            if top == "tv_mcp" and "." in name:
                target = _layer(name.removeprefix("tv_mcp."))
                if target not in ALLOWED[layer]:
                    wrong.append(f"{module} ({layer}) imports {name} ({target})")
            elif top in FORBIDDEN_OUTSIDE.get(layer, set()):
                wrong.append(f"{module} ({layer}) imports {name}")
    assert wrong == []


def test_the_core_never_imports_a_driver():
    core = [path for module, path in _modules() if _layer(module) == "core"]
    assert core, "no core modules found; the layer map is out of date"
    assert [str(p) for p in core if any(n.startswith("tv_mcp.drivers.") for n in _imports(p))] == []
