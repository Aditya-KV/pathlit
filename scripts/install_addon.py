"""Copies the Pathlit Bridge add-on into your Blender 4.1 add-ons folder. Run it once, then enable the add-on in Blender.

Writes ONLY to: %APPDATA%\\Blender Foundation\\Blender\\4.1\\scripts\\addons\\pathlit_bridge
Then in Blender: Edit > Preferences > Add-ons > search "Pathlit" > tick the box. (Close and reopen Blender if it was open.)
If the add-on checkbox cannot be ticked, add --autoload: it also installs a tiny startup script that enables the add-on
every time Blender starts (writes to .../scripts/startup/pathlit_autoload.py).
Usage: python scripts/install_addon.py [--autoload] [--remove]
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        sys.exit("APPDATA is not set (this script is for Windows).")
    scripts = Path(appdata) / "Blender Foundation" / "Blender" / "4.1" / "scripts"
    dest = scripts / "addons" / "pathlit_bridge"
    startup = scripts / "startup" / "pathlit_autoload.py"
    if "--remove" in sys.argv:
        shutil.rmtree(dest, ignore_errors=True)
        startup.unlink(missing_ok=True)
        print(f"removed {dest} and {startup}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "blender_addon" / "pathlit_bridge", dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    print(f"installed to {dest}")
    if "--autoload" in sys.argv:
        startup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "blender_addon" / "startup" / "pathlit_autoload.py", startup)
        print(f"autoload installed to {startup}")
        print("Close Blender completely and open it again. The add-on turns itself on.")
    else:
        print("Now enable it in Blender: Edit > Preferences > Add-ons > search 'Pathlit'.")


if __name__ == "__main__":
    main()
