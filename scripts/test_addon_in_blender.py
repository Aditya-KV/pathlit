"""Verifies the add-on inside a REAL Blender 4.1 (opens a Blender window for a few seconds).

Uses a throw-away scripts folder and --factory-startup, so it never touches your Blender settings or add-ons.
Usage: python scripts/test_addon_in_blender.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe")
PORT = "8799"

INSIDE = r'''
import bpy, json, threading, urllib.request, time, sys, os
out = os.environ["PATHLIT_RESULT"]
res = {}
if os.environ.get("PATHLIT_AUTOLOAD") != "1":
    bpy.ops.preferences.addon_enable(module="pathlit_bridge")
def fetch(tag):
    try:
        res[tag] = json.loads(urllib.request.urlopen("http://127.0.0.1:%s/state" % os.environ["PATHLIT_PORT"], timeout=2).read())
        res[tag + "_ping"] = urllib.request.urlopen("http://127.0.0.1:%s/ping" % os.environ["PATHLIT_PORT"], timeout=2).read().decode()
    except Exception as e:
        res[tag] = "ERR %r" % e
def step1():
    threading.Thread(target=fetch, args=("object_mode",)).start(); return None
def to_edit():
    bpy.ops.object.mode_set(mode="EDIT"); return None
def step2():
    threading.Thread(target=fetch, args=("edit_mode",)).start(); return None
def add_mod():
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.objects.active.modifiers.new("S", "SUBSURF")
        res["add_mod"] = "ok"
    except Exception as e:
        res["add_mod"] = "ERR %r" % e
    return None
def step3():
    threading.Thread(target=fetch, args=("with_modifier",)).start(); return None
def finish():
    json.dump(res, open(out, "w")); bpy.ops.wm.quit_blender(); return None
for t, f in [(3.0, step1), (3.5, to_edit), (5.0, step2), (5.5, add_mod), (7.0, step3), (11.0, finish)]:
    bpy.app.timers.register(f, first_interval=t)
'''


def main() -> None:
    if not BLENDER.exists():
        sys.exit(f"Blender not found at {BLENDER}")
    tmp = Path(tempfile.mkdtemp(prefix="pathlit_addon_test_"))
    try:
        addons = tmp / "scripts" / "addons"
        addons.mkdir(parents=True)
        shutil.copytree(ROOT / "blender_addon" / "pathlit_bridge", addons / "pathlit_bridge")
        autoload = "--autoload" in sys.argv
        if autoload:
            (tmp / "scripts" / "startup").mkdir(parents=True)
            shutil.copy2(ROOT / "blender_addon" / "startup" / "pathlit_autoload.py", tmp / "scripts" / "startup")
        script = tmp / "inside.py"
        script.write_text(INSIDE, encoding="utf-8")
        result = tmp / "result.json"
        env = dict(os.environ, BLENDER_USER_SCRIPTS=str(tmp / "scripts"), PATHLIT_PORT=PORT, PATHLIT_RESULT=str(result), PATHLIT_AUTOLOAD="1" if autoload else "0")
        # --factory-startup skips user startup scripts, so the autoload test uses a throw-away config folder instead
        (tmp / "config").mkdir()
        env["BLENDER_USER_CONFIG"] = str(tmp / "config")
        flags = [] if autoload else ["--factory-startup"]
        subprocess.run([str(BLENDER), *flags, "--python", str(script)], env=env, timeout=90,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not result.exists():
            sys.exit("Blender produced no result (add-on did not load?)")
        print(json.dumps(json.loads(result.read_text(encoding="utf-8")), indent=1))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
