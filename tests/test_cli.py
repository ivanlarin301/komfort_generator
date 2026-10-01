from __future__ import annotations

import json

from komfort_cards import cli


def last_result(capsys) -> dict:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("RESULT: ")]
    assert lines, "every command must end with a RESULT line"
    return json.loads(lines[-1][len("RESULT: "):])


def test_help_lists_all_commands(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    for name in cli.COMMANDS:
        assert name in out


def test_every_command_has_a_parser():
    parser = cli.build_parser()
    for name in cli.COMMANDS:
        args = ["prompt", "1"] if name == "prompt" else ["background", "1"] if name == "background" else [name]
        if name == "init":
            args = ["init", "--rows", "1"]
        assert parser.parse_args(args).command == name
