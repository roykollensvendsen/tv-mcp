# SPDX-License-Identifier: GPL-3.0-or-later
"""Every refusal tells the owner what to do next (the plugin standard's rule 4).

A refusal read aloud that only says what went wrong leaves the owner with
nothing to do. So the last sentence of each refusal is either a question or
starts with something to do. The refusals are read from the source, so a new
one cannot slip past.
"""

import ast
import pathlib
import re

import tv_mcp

SOURCES = [pathlib.Path(tv_mcp.__file__).parent / name for name in ("service.py", "power.py")]
#: How a sentence that says what to do next can start.
NEXT_STEPS = (
    "Ask",
    "Say",
    "Try",
    "Open",
    "Pick",
    "Plug",
    "Add",
    "Switch",
    "Start",
    "Check",
    "Choose",
    "Name",
    "Wait",
    "Use",
    "Remove",
)
#: Refusals passed on from elsewhere, each with where its own next step is checked.
PASSED_ON = {
    "str(refusal)": "settings: the TV names are listed, or a choice asked for",
    "_another(tv)": "test_another_tv_at_the_address_says_where_to_look",
}


def _text(node, constants):
    """The words of a refusal, with each {placeholder} kept as X."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return None


def _refusals():
    for source in SOURCES:
        tree = ast.parse(source.read_text())
        constants = {
            t.id: n.value.value
            for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_refused" and node.args:
                arg = node.args[0]
                if ast.unparse(arg) in PASSED_ON:
                    continue
                yield f"{source.name}:{node.lineno}", _text(arg, constants), ast.unparse(arg)


def _last_sentence(text):
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    return sentences[-1] if sentences else ""


def test_every_refusal_ends_with_what_to_do_next():
    missing = []
    for where, text, source in _refusals():
        if text is None:
            missing.append(f"{where}: cannot read {source}")
            continue
        last = _last_sentence(text)
        if not (last.endswith("?") or last.startswith(NEXT_STEPS)):
            missing.append(f"{where}: {text!r}")
    assert not missing, "\n".join(missing)


def test_the_refusals_are_found_at_all():
    assert sum(1 for _ in _refusals()) > 30


def test_another_tv_at_the_address_says_where_to_look():
    from tv_mcp.service import _another  # noqa: PLC0415 - the one refusal built by a helper
    from tv_mcp.settings import Tv  # noqa: PLC0415

    assert _last_sentence(_another(Tv(key="k", names=("the den",)))).startswith(NEXT_STEPS)


def test_every_tool_answers_with_a_sentence_even_when_it_fails():
    import asyncio  # noqa: PLC0415

    import httpx  # noqa: PLC0415

    from tv_mcp.server import build_server  # noqa: PLC0415
    from tv_mcp.simulator import simulated_service  # noqa: PLC0415

    service = simulated_service()

    async def drops(name):
        message = "connection reset"
        raise httpx.ConnectError(message)

    service.status = drops
    result = asyncio.run(build_server(service).call_tool("tv_status", {}))
    answer = result.structured_content or {}  # empty when the tool raised
    assert answer["success"] is False
    assert "try again" in answer["say"].casefold()


def test_every_tool_is_guarded_so_no_failure_reaches_the_voice_bare():
    import asyncio  # noqa: PLC0415

    from tv_mcp import server  # noqa: PLC0415
    from tv_mcp.simulator import simulated_service  # noqa: PLC0415
    from tv_mcp.tools import FEATURES  # noqa: PLC0415

    built = server.build_server(simulated_service(), features=list(FEATURES))
    names = {t.name for t in asyncio.run(built.list_tools())}
    assert names == set(built.guarded)
