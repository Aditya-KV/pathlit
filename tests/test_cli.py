"""The friendly `pathlit` command: dispatch table, process finding, shortcut, and the launcher itself."""
import subprocess
import sys
from pathlib import Path

import pytest

from pathlit import cli

ROOT = Path(__file__).resolve().parents[1]


def test_every_script_command_points_at_a_script_that_exists():
    for name, (script, _args, _help) in cli.SCRIPT_COMMANDS.items():
        assert (cli.SCRIPTS / script).exists(), f"{name}: {script} is missing"


def test_help_lists_every_command(capsys):
    assert cli.main(["help"]) == 0
    text = capsys.readouterr().out
    for word in ("run", "setup", "doctor", "stop", "blender", "collect", "label", "eval", "results", "test", "shortcut"):
        assert f"pathlit {word}" in text or word in text.split()


def test_an_unknown_command_is_explained_not_a_traceback(capsys):
    assert cli.main(["frobnicate"]) == 2
    out = capsys.readouterr().out
    assert "Unknown command: frobnicate" in out and "pathlit doctor" in out


def test_find_running_picks_pathlit_copies_but_never_itself_or_helper_commands():
    procs = [
        {"ProcessId": 10, "CommandLine": r'"C:\x\.venv\Scripts\python.exe" -u -m pathlit'},
        {"ProcessId": 11, "CommandLine": r'"C:\x\.venv\Scripts\python.exe" scripts\run.py'},
        {"ProcessId": 12, "CommandLine": r'"C:\x\.venv\Scripts\python.exe" -u -m pathlit stop'},       # this very command
        {"ProcessId": 13, "CommandLine": r'"C:\x\.venv\Scripts\python.exe" -u -m pathlit doctor'},
        {"ProcessId": 14, "CommandLine": r'"C:\Python\python.exe" some_other_script.py'},
        {"ProcessId": 15, "CommandLine": None},
        {"ProcessId": 99, "CommandLine": r'"C:\x\.venv\Scripts\python.exe" -u -m pathlit'},          # our own pid
    ]
    assert cli.find_running(procs, own_pid=99) == [10, 11]


def test_stop_with_nothing_running_is_friendly(monkeypatch, capsys):
    monkeypatch.setattr(cli, "list_python_processes", lambda: [])
    assert cli.cmd_stop() == 0 and "not running" in capsys.readouterr().out


def test_stop_closes_each_found_copy(monkeypatch, capsys):
    monkeypatch.setattr(cli, "list_python_processes", lambda: [{"ProcessId": 7, "CommandLine": "x -m pathlit"}])
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    cli.cmd_stop()
    assert calls == [["taskkill", "/PID", "7", "/F"]] and "Closed 1" in capsys.readouterr().out


def test_setup_creates_env_from_the_example_and_asks_for_keys(monkeypatch, tmp_path, capsys):
    (tmp_path / ".env.example").write_text("AZURE_VISION_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    assert cli.cmd_setup() == 1
    assert (tmp_path / ".env").exists() and "paste in your keys" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shortcuts")
def test_shortcut_is_created_where_asked_and_points_at_the_launcher(tmp_path):
    assert cli.cmd_shortcut(str(tmp_path)) == 0
    assert (tmp_path / "Pathlit.lnk").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
def test_the_launcher_runs_the_help_command_with_the_projects_python():
    r = subprocess.run(["cmd", "/c", str(ROOT / "pathlit.cmd"), "help"], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 0 and "pathlit doctor" in r.stdout and "pathlit stop" in r.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
def test_the_shim_is_written_into_a_scripts_folder_and_points_at_the_launcher(tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    shim = cli.ensure_shim(scripts)
    assert shim == scripts / "pathlit.cmd"
    text = shim.read_text(encoding="utf-8")
    assert str(ROOT / "pathlit.cmd") in text and "%*" in text
    before = shim.stat().st_mtime_ns
    assert cli.ensure_shim(scripts) == shim and shim.stat().st_mtime_ns == before          # unchanged: not rewritten


def test_the_shim_is_not_written_outside_a_scripts_folder(tmp_path):
    assert cli.ensure_shim(tmp_path) is None and not list(tmp_path.iterdir())
