"""Every rule this project enforces has evidence, and the evidence names it.

A rule here is one line of source marked ``# RULE: what it says``. Three things
have to be true of each, and none of them is true by writing the rule:

* it has a row, in a file of its own under ``scripts/mutations/``, so something
  switches it off;
* a test carries the rule's own words as its name;
* switching it off turns *that* test red, which ``scripts/mutate.py`` checks.

The second is what makes the third readable. A mutation breaks whatever it
breaks, and a kill only means something when the test that went red is the one
that names the rule — otherwise a documented example that happened to change can
leave a rule looking guarded while nothing guards it.
"""

import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).parent.parent
MARKER = re.compile(r"^[ \t]*#\s*RULE:\s*(.+?)\s*$")


def _mutate():
    """The mutation runner, loaded by path: scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("mutate", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def marked_rules() -> set[str]:
    """Every rule the source marks, by the words the marker gives it."""
    found = set()
    # The checks this project added count too; the scripts the start-repo
    # skill ships carry rules that skill proves.
    scripts = [ROOT / "scripts" / n for n in ("no_session_links.py", "private_data_scan.py", "ratchet.py")]
    sources = [*(ROOT / "src").rglob("*.py"), *scripts]
    for source in sorted(sources):
        for line in source.read_text().splitlines():
            match = MARKER.search(line)
            if match:
                found.add(match.group(1))
    return found


def rowed_rules() -> set[str]:
    """Every rule the mutation rows claim to switch off."""
    return {str(rule["name"]) for rule in _mutate().all_rows()}


def defined_test_names() -> set[str]:
    """Every test function this suite defines.

    Not called ``test_names``: pytest collects anything starting with ``test_``,
    and a helper that returns a set would be reported as a test that forgot to
    assert.
    """
    found = set()
    for module in sorted((ROOT / "tests").rglob("test_*.py")):
        found.update(re.findall(r"^(?:async )?def (test_\w+)", module.read_text(), re.MULTILINE))
    return found


def test_every_rule_in_the_source_has_a_row_in_the_mutation_table():
    """Without this the evidence falls behind the code and nobody sees it happen."""
    marked, rowed = marked_rules(), rowed_rules()
    assert marked - rowed == set(), f"marked in the source and never switched off: {marked - rowed}"
    assert rowed - marked == set(), f"a row for a rule no longer in the source: {rowed - marked}"


def test_every_rule_has_a_test_named_after_it():
    """A kill is only evidence about a rule when the test that went red names it."""
    name_for = _mutate().test_name_for
    named = defined_test_names()
    missing = sorted(rule for rule in marked_rules() if name_for(rule) not in named)
    wanted = ", ".join(f"{name_for(rule)}()" for rule in missing)
    assert not missing, f"rules with no test named after them — write {wanted}"


def _row(name, file="src/tv_mcp/server.py"):
    return f"[[rule]]\nname = \"{name}\"\nfile = \"{file}\"\nfind = 'x'\nreplace = 'y'\n"


def _place(folder, path, text):
    (folder / path).parent.mkdir(parents=True, exist_ok=True)
    (folder / path).write_text(text)


def test_every_row_is_read_from_a_file_of_its_own(tmp_path):
    """A file per row only meets another pull request adding the same rule.

    Two pull requests that each added a row at the end of one shared file collided.
    """
    folder = tmp_path / "mutations"
    _place(folder, "src/tv_mcp/server.py/one.toml", _row("one"))
    _place(folder, "src/tv_mcp/service.py/two.toml", _row("two", "src/tv_mcp/service.py"))
    assert [rule["name"] for rule in _mutate().all_rows(folder)] == ["one", "two"]


def test_the_same_rule_with_two_rows_is_refused(tmp_path):
    """A rule with two rows would be switched off twice and counted twice."""
    folder = tmp_path / "mutations"
    _place(folder, "src/tv_mcp/server.py/twice.toml", _row("twice"))
    _place(folder, "src/tv_mcp/service.py/twice.toml", _row("twice", "src/tv_mcp/service.py"))
    with pytest.raises(SystemExit) as refused:
        _mutate().all_rows(folder)
    said = str(refused.value)
    assert "mutations/src/tv_mcp/server.py/twice.toml" in said
    assert "mutations/src/tv_mcp/service.py/twice.toml" in said
    assert "delete one" in said


def test_a_rule_with_no_letter_or_digit_is_refused_a_row_file():
    with pytest.raises(SystemExit, match="no letter or digit"):
        _mutate().row_path({"name": "--", "file": "src/tv_mcp/server.py"})


def test_a_row_file_sits_under_its_source_file_s_whole_path_under_its_own_name(tmp_path):
    """Where a row lives is never a choice.

    Its folder is the row's `file` exactly, extension included; its name is the rule's words.
    """
    folder = tmp_path / "mutations"
    _place(folder, "src/tv_mcp/server.py/in-place.toml", _row("in place"))
    _place(folder, "server/wrong-folder.toml", _row("wrong folder"))
    _place(folder, "src/tv_mcp/server.py/a-wrong-name.toml", _row("named otherwise"))
    _place(folder, "src/tv_mcp/server.py/two-rows.toml", _row("two rows") + _row("in one file"))
    found = " ".join(_mutate().misfiled(folder))
    assert "server/wrong-folder.toml should be src/tv_mcp/server.py/wrong-folder.toml" in found
    here = "src/tv_mcp/server.py"
    assert f"{here}/a-wrong-name.toml should be {here}/named-otherwise.toml" in found
    assert "src/tv_mcp/server.py/two-rows.toml holds 2 rows" in found
    assert "in-place" not in found


def test_every_row_file_in_the_repository_is_where_its_rule_says():
    misfiled = _mutate().misfiled()
    assert not misfiled, "row files out of place: " + "; ".join(misfiled)
    assert not (ROOT / "scripts/mutations.toml").exists(), "the shared table is gone; give each row a file"
