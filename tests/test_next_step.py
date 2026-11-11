# SPDX-License-Identifier: GPL-3.0-or-later
"""Every refusal tells the owner what to do next (the plugin standard's rule 4).

A refusal read aloud that only says what went wrong leaves the owner with
nothing to do. So the last sentence of each refusal is either a question or
starts with something to do. The refusals are read from the source, so a new
one cannot slip past.

Since 2026-11-11 the owner's rule for every plugin goes further: every
failure, not only a refusal, says what is wrong and what to do next, and a
bare question ("Is it on?") is not a next step. Every answer that is not a
success is read from all of the source, and its last sentence must start
with something to do.
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
        if not last.startswith(NEXT_STEPS):
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


def test_a_tool_still_working_at_the_deadline_says_it_carries_on(monkeypatch):
    # The Claude app gives up on a call after about 15 seconds (the plugin standard's rule 3).
    import asyncio  # noqa: PLC0415

    from tv_mcp import server  # noqa: PLC0415
    from tv_mcp.simulator import simulated_service  # noqa: PLC0415

    monkeypatch.setattr(server, "ANSWER_WITHIN", 0.01)
    finish, finished = asyncio.Event(), []
    service = simulated_service()

    async def slow(name):
        await finish.wait()
        finished.append(name)
        return []

    service.status = slow

    async def call_then_finish():
        built = server.build_server(service)
        result = await asyncio.wait_for(built.call_tool("tv_status", {}), 2)  # never hang the suite
        finish.set()
        for _ in range(3):
            await asyncio.sleep(0)
        return result.structured_content

    answer = asyncio.run(call_then_finish())
    assert answer["outcome"] == "working"
    assert "carries on" in answer["say"]
    assert finished == [None]


#: Answers that are not a failure, though they are not "done" either.
SUCCESSES = {"done", "playing", "starting", "found", "listed", "on", "off", "question"}
#: The errors whose words are read aloud as a refusal.
SPOKEN_ERRORS = {"UnknownTvError", "AmbiguousTvError", "UnknownFeatureError"}
#: The start of a sentence that says what to do next.
NEXT = (*NEXT_STEPS, "Run", "Pair", "Close", "Give", "Restart", "Look", "Keep", "Turn")


def _assigned(name, scope):
    """What `name` is set to anywhere in `scope`."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            yield node.value
        if (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and getattr(node.target, "id", None) == name
        ):
            yield node.value


def _returned(helper):
    """What `helper` returns."""
    for node in ast.walk(helper):
        if isinstance(node, ast.Return) and node.value is not None:
            yield node.value


def _all_texts(node, scope, module):
    """Every text `node` can be, following names to what they were set to and helpers to what they return."""
    constants, functions = module
    if isinstance(node, ast.BinOp):
        yield from _all_texts(node.right, scope, module)
    elif isinstance(node, ast.IfExp):
        yield from _all_texts(node.body, scope, module)
        yield from _all_texts(node.orelse, scope, module)
    elif isinstance(node, ast.Name) and scope is not None and (values := list(_assigned(node.id, scope))):
        for value in values:
            yield from _all_texts(value, scope, module)
    elif isinstance(node, ast.Name) and node.id in constants:
        yield constants[node.id], node.id
    elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in functions:
        helper = functions[node.func.id]
        for value in _returned(helper):
            yield from _all_texts(value, helper, module)
    elif not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "str"):
        # str(error) is a spoken error passed on; its own words are checked where it is raised.
        yield _text(node, {}), ast.unparse(node)


def _said(node):
    """What `node` reads aloud as a failure, if it is one."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_refused" and node.args:
        yield node.args[0]
    if isinstance(node, ast.Dict):
        keys = {
            k.value: v for k, v in zip(node.keys, node.values, strict=True) if isinstance(k, ast.Constant)
        }
        outcome, success = keys.get("outcome"), keys.get("success")
        failed = isinstance(outcome, ast.Constant) and outcome.value not in SUCCESSES
        unsuccessful = isinstance(success, ast.Constant) and success.value is False
        if "say" in keys and (failed or unsuccessful):
            yield keys["say"]
    if (
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and node.exc.args
        and getattr(node.exc.func, "id", None) in SPOKEN_ERRORS
    ):
        yield node.exc.args[0]


def _module(tree):
    """A module's constant texts, and its functions by name."""
    constants = {
        t.id: _text(n.value, {})
        for n in tree.body
        if isinstance(n, ast.Assign) and _text(n.value, {}) is not None
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return constants, functions


def _failures():
    """Every failure text in tv-mcp, with where it is."""
    for source in sorted(pathlib.Path(tv_mcp.__file__).parent.rglob("*.py")):
        tree = ast.parse(source.read_text())
        module = _module(tree)
        owner = {id(c): f for f in module[1].values() for c in ast.walk(f)}
        for node in ast.walk(tree):
            scope = owner.get(id(node))
            if getattr(scope, "name", None) == "_refused":
                continue  # the helper itself; its callers are each checked
            for arg in _said(node):
                for text, raw in _all_texts(arg, scope, module):
                    yield f"{source.name}:{arg.lineno}", text, raw


def test_every_failure_says_what_to_do_next():
    missing = []
    for where, text, raw in _failures():
        if text is None:
            missing.append(f"{where}: cannot read {raw}")
        elif not _last_sentence(text).startswith(NEXT):
            missing.append(f"{where}: {text!r}")
    assert not missing, "\n".join(sorted(set(missing)))


def test_the_failures_are_found_at_all():
    assert sum(1 for _ in _failures()) > 40
