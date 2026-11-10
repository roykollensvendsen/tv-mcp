# SPDX-License-Identifier: GPL-3.0-or-later
"""Each rule of the voice plugins' shared standard has a test here named after it.

The standard is claude-voice's docs/plugin-standard.md. Rules 1 to 11 each map
to the tests that guard them in tv-mcp; renaming or deleting one of those
tests turns this red, so a rule cannot lose its guard quietly. Rule 12 is this
file, and its second half, asking the voice what it sees after a change to a
name or a first line, is a step in the add-tv-feature skill.
"""

import ast
import pathlib

TESTS = pathlib.Path(__file__).parent

#: Each rule of the standard, and the tests in tv-mcp that guard it.
STANDARD = {
    1: ["test_tool_names.py::test_no_two_tool_names_can_be_confused"],
    2: ["test_tool_openings.py::test_every_tool_opens_with_a_whole_sentence_the_voice_sees_in_full"],
    3: ["test_voice_time_limit.py::test_a_tools_longest_wait_fits_in_the_voices_time"],
    4: [
        "test_next_step.py::test_every_refusal_ends_with_what_to_do_next",
        "test_next_step.py::test_every_tool_answers_with_a_sentence_even_when_it_fails",
    ],
    5: [
        "test_power.py::test_a_switch_is_done_only_once_the_tv_is_seen_in_its_new_state",
        "test_input.py::test_the_answer_says_the_tv_shows_the_input_only_once_it_was_read_back",
    ],
    6: ["test_power.py::test_a_switch_is_refused_when_the_tv_state_is_not_known"],
    7: [
        "test_power.py::test_nothing_switches_without_the_token_from_the_question",
        "test_power.py::test_a_power_token_works_once",
        "test_power.py::test_a_power_token_expires_after_thirty_seconds",
        "test_power.py::test_a_token_is_kept_when_nothing_reached_the_tv",
    ],
    8: ["test_service.py::test_a_hands_off_tv_is_never_contacted"],
    9: ["test_read_only_tools.py::test_the_tools_that_only_look_are_marked_read_only_and_no_others"],
    10: ["test_private_data_scan.py::test_a_value_from_the_settings_file_is_never_committed"],
    11: ["test_server.py::test_every_simulated_answer_says_simulated_first"],
}


def _defined(file):
    tree = ast.parse((TESTS / file).read_text())
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_each_rule_has_a_test_named_after_it():
    assert set(STANDARD) == set(range(1, 12))
    missing = [
        f"rule {rule}: {test}"
        for rule, tests in STANDARD.items()
        for test in tests
        if test.split("::")[1] not in _defined(test.split("::")[0])
    ]
    assert not missing, missing
