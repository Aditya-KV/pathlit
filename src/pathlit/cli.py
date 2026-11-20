"""One friendly entry point:  pathlit <command>

    pathlit                start Pathlit (same as: pathlit run)
    pathlit setup          first-time check: .env file, packages, Azure keys
    pathlit doctor         is everything ready? keys, Blender link, other copies running
    pathlit stop           close any running copy of Pathlit
    pathlit blender        install the Blender add-on (autoload); "pathlit blender remove" to undo
    pathlit collect        take the evaluation screenshots (Blender window only)
    pathlit label          label the screenshots
    pathlit eval           run every evaluation and rebuild docs/results.md
    pathlit results        rebuild docs/results.md only
    pathlit test           run the tests ("pathlit test fast" skips the ones that call Azure)
    pathlit shortcut       put a Pathlit icon on your Desktop
"""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

# command -> (script, extra arguments, one-line help)
SCRIPT_COMMANDS: dict[str, tuple[str, list[str], str]] = {
    "collect": ("collect_screens.py", [], "take the 50 evaluation screenshots"),
    "label": ("label_tool.py", [], "label the screenshots"),
    "eval": ("run_all_evals.py", [], "run every evaluation and rebuild docs/results.md"),
    "results": ("make_results.py", [], "rebuild docs/results.md"),
    "latency": ("measure_latency.py", [], "measure hotkey-to-voice speed"),
}
REQUIRED_KEYS = ["AZURE_VISION_ENDPOINT", "AZURE_VISION_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]
OPTIONAL_KEYS = ["GROQ_API_KEY", "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY"]


def run_script(name: str, args: list[str]) -> None:
    path = SCRIPTS / name
    sys.argv = [str(path), *args]
    runpy.run_path(str(path), run_name="__main__")


def find_running(processes: list[dict], own_pid: int) -> list[int]:
    """Pids of running Pathlit copies. Pure, so it can be tested. Never includes this process or a `pathlit stop` itself."""
    root = str(ROOT).lower()
    out = []
    for p in processes:
        cmd = (p.get("CommandLine") or "").lower()
        pid = int(p["ProcessId"])
        if pid == own_pid or not cmd:
            continue
        runs_pathlit = "-m pathlit" in cmd or "scripts\\run.py" in cmd or "pathlit.main" in cmd or (root in cmd and "run.py" in cmd)
        is_a_helper_command = any(w in cmd for w in (" stop", " doctor", " setup", " test", " eval", " collect", " label", " results"))
        if runs_pathlit and not is_a_helper_command:
            out.append(pid)
    return out


def list_python_processes() -> list[dict]:
    if sys.platform != "win32":
        return []
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' } | "
          "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20).stdout
        data = json.loads(out) if out.strip() else []
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def cmd_stop() -> int:
    pids = find_running(list_python_processes(), os.getpid())
    if not pids:
        print("Pathlit is not running.")
        return 0
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    print(f"Closed {len(pids)} Pathlit process(es).")
    return 0


def key_status() -> tuple[list[str], list[str]]:
    from .config import env
    return [k for k in REQUIRED_KEYS if not env(k)], [k for k in OPTIONAL_KEYS if not env(k)]


def cmd_doctor() -> int:
    from .config import load_settings
    ok = True
    print(f"Python {sys.version.split()[0]}  |  project: {ROOT}")
    env_file = ROOT / ".env"
    print(f".env file       : {'found' if env_file.exists() else 'MISSING (copy .env.example to .env and fill it in)'}")
    ok &= env_file.exists()
    missing, optional_missing = key_status()
    print(f"Azure keys      : {'all set' if not missing else 'MISSING ' + ', '.join(missing)}")
    ok &= not missing
    print(f"Groq key        : {'set' if 'GROQ_API_KEY' not in optional_missing else 'not set (lessons use their own text; typed tasks need it)'}")
    print(f"Manual search   : {'configured' if 'AZURE_SEARCH_KEY' not in optional_missing else 'off (optional)'}")
    s = load_settings()
    from .blender_bridge import BlenderBridge
    up = BlenderBridge(s["blender_port"], 1.5).ping()
    print(f"Blender link    : {'connected' if up else 'not connected (open Blender; run: pathlit blender)'}")
    if up:
        api = BlenderBridge(s["blender_port"], 1.5).api_version()
        ok_api = api is not None and api >= BlenderBridge.REQUIRED_API
        print(f"Blender add-on  : {'up to date (v' + str(api) + ')' if ok_api else 'OUT OF DATE: run  pathlit blender  and restart Blender'}")
        ok &= bool(ok_api)
    running = find_running(list_python_processes(), os.getpid())
    print(f"Pathlit running : {'yes (' + str(len(running)) + ' process(es)); stop with: pathlit stop' if running else 'no'}")
    print("\nReady." if ok else "\nFix the items marked MISSING, then run: pathlit doctor")
    return 0 if ok else 1


def cmd_setup() -> int:
    print("Pathlit first-time setup\n")
    env_file, example = ROOT / ".env", ROOT / ".env.example"
    if not env_file.exists() and example.exists():
        env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example. Open it and paste in your keys (Azure Vision, Azure Speech, Groq).")
        print("Then run: pathlit setup   again.")
        return 1
    missing, _ = key_status()
    if missing:
        print("Still missing in .env: " + ", ".join(missing))
        return 1
    print("Keys found. Checking Azure...\n")
    run_script("check_azure.py", [])
    print("\nNext: pathlit blender   (installs the Blender add-on), then: pathlit")
    return 0


def cmd_shortcut(dest: str | None) -> int:
    if sys.platform != "win32":
        print("Desktop shortcuts are only supported on Windows.")
        return 1
    folder = Path(dest) if dest else Path(os.path.expanduser("~")) / "Desktop"
    folder.mkdir(parents=True, exist_ok=True)
    lnk = folder / "Pathlit.lnk"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{t}';"
          "$s.WorkingDirectory='{w}';$s.Description='Start Pathlit';$s.Save()").format(
        lnk=str(lnk).replace("'", "''"), t=str(ROOT / "pathlit.cmd").replace("'", "''"), w=str(ROOT).replace("'", "''"))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not lnk.exists():
        print("Could not create the shortcut:", (r.stderr or r.stdout).strip()[:200])
        return 1
    print(f"Created {lnk}")
    return 0


def ensure_shim(scripts_dir: Path | None = None) -> Path | None:
    """Puts a small `pathlit.cmd` into the virtual environment's Scripts folder. That folder is on PATH whenever the venv is
    active (VS Code activates it for you), so plain `pathlit` then works in PowerShell and Command Prompt alike."""
    if sys.platform != "win32":
        return None
    folder = scripts_dir or Path(sys.executable).parent
    if folder.name.lower() != "scripts" or not folder.exists():
        return None                                              # not running from a venv
    shim = folder / "pathlit.cmd"
    crlf = chr(13) + chr(10)
    text = "@echo off" + crlf + '"' + str(ROOT / "pathlit.cmd") + '" %*' + crlf
    try:
        data = text.encode("utf-8")
        if not shim.exists() or shim.read_bytes() != data:           # bytes, so line endings do not cause rewrites
            shim.write_bytes(data)
    except OSError:
        return None
    return shim


def usage() -> str:
    return __doc__ or ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if argv is None:
        ensure_shim()                                            # makes plain `pathlit` work from the next terminal on
    cmd = args[0].lower() if args else "run"
    rest = args[1:]
    if cmd in ("-h", "--help", "help"):
        print(usage())
        return 0
    if cmd == "run":
        from .main import main as run_app
        run_app()
        return 0
    if cmd == "stop":
        return cmd_stop()
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "setup":
        return cmd_setup()
    if cmd == "shortcut":
        return cmd_shortcut(rest[rest.index("--dest") + 1] if "--dest" in rest else None)
    if cmd == "blender":
        run_script("install_addon.py", ["--remove"] if rest[:1] == ["remove"] else ["--autoload"])
        return 0
    if cmd == "test":
        extra = ["-m", "not live"] if rest[:1] == ["fast"] else []
        return subprocess.call([sys.executable, "-m", "pytest", "-q", *extra], cwd=ROOT)
    if cmd in SCRIPT_COMMANDS:
        script, extra, _ = SCRIPT_COMMANDS[cmd]
        run_script(script, [*extra, *rest])
        return 0
    print(f"Unknown command: {cmd}\n\n{usage()}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
